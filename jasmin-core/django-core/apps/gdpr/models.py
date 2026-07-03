from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.commissioning.models.mixin import AdminConfirmableMixin
from apps.shared.tenants.models import JasminModel


class DeletionLog(JasminModel):
    """
    GDPR Art. 17 — Logs every personal-data deletion request so that
    it can be replayed if a database backup is restored.
    """

    user_email = models.EmailField(
        help_text="Email of the user whose data was deleted (for audit trail)."
    )
    deleted_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(
        blank=True,
        null=True,
        help_text="What data was deleted (e.g. 'Full account anonymization').",
    )

    class Meta:
        ordering = ["-deleted_at"]

    def __str__(self):
        return f"Deletion {self.user_email} @ {self.deleted_at}"


# 24h is the standard click-to-confirm window — long enough for a user
# who reads emails once a day, short enough that a leaked token isn't
# useful indefinitely.
DELETION_TOKEN_TTL = timedelta(hours=24)


class DeletionRequestState(models.TextChoices):
    """State machine for a two-step (optionally three-step) deletion flow.

    Transitions (driven exclusively by ``GDPRService``):

        PENDING_EMAIL  ─► PENDING_ADMIN ─► APPROVED ─► EXECUTED
                       └► APPROVED      ─► EXECUTED
                       └► EXPIRED   (24h elapsed without confirm)
                       └► CANCELLED (user re-requests / admin cancels)
        PENDING_ADMIN  ─► REJECTED   (admin denies)

    States are stored explicitly (not derived from timestamps) so
    auditor reports never have to second-guess what state a row was
    in at a given time.
    """

    PENDING_EMAIL = "pending_email", "Pending email confirmation"
    PENDING_ADMIN = "pending_admin", "Pending admin approval"
    APPROVED = "approved", "Approved (ready to execute)"
    EXECUTED = "executed", "Executed"
    EXPIRED = "expired", "Expired (no email confirmation in time)"
    CANCELLED = "cancelled", "Cancelled"
    REJECTED = "rejected", "Rejected by admin"


class DeletionRequest(AdminConfirmableMixin, JasminModel):
    """A pending / completed GDPR Art. 17 deletion request.

    The request is created by the user (self-service) or by an admin
    acting on a written request. It then goes through a confirmation
    chain before ``GDPRService.anonymize_user`` is actually called:

      1. **Email confirmation** (always required) — proves the
         requester controls the inbox, defending against the
         leaked-JWT scenario.
      2. **Admin approval** (only if ``requires_admin_approval=True``)
         — extra safety net for high-risk personas (staff/admin
         deletions) or tenants who want every deletion human-reviewed.

    Reuses :class:`apps.commissioning.models.mixin.AdminConfirmableMixin`
    for the admin-approval audit fields (``admin_confirmed``,
    ``admin_confirmed_by``, ``admin_confirmed_at``,
    ``admin_rejection_reason``). One-way cross-app import is fine
    per CLAUDE.md — ``commissioning`` stays isolatable as long as
    nothing in commissioning imports back from here. The mixin's
    ``confirm()`` / ``reject()`` methods are invoked by
    ``GDPRService.admin_approve_deletion`` /
    ``admin_reject_deletion``.

    The model is the single source of truth for "is this deletion
    actually going to happen?". The token is a UUID with a 24h TTL.
    Once executed (or expired/cancelled/rejected), the row stays
    forever as part of the audit trail — paired 1:1 with the
    ``DeletionLog`` row created at execute time.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # SET_NULL (not CASCADE): this row IS the Art. 17 erasure audit trail and
        # must outlive its subject. requested_email/_at/_ip are captured below so
        # the trail still stands when ``user`` becomes NULL. (GDPR anonymizes in
        # place today, so this is defence-in-depth — and matches the sibling
        # SET_NULL FKs on this model.)
        on_delete=models.SET_NULL,
        null=True,
        related_name="deletion_requests",
    )

    # Captured at request time so the audit trail survives even if
    # ``user`` is later anonymized (email becomes ``deleted_<pk>@…``).
    requested_email = models.EmailField(
        help_text="Email at the moment the request was made — captured "
        "so the audit trail survives the anonymization itself."
    )
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Captured at request time so the burst-alert Huey task
    # (``alert_on_deletion_endpoint_bursts`` in tasks.py) can group
    # by source IP across users. The per-user throttle already
    # blocks "one user, 6th request" — this field lets us catch
    # "one IP, multiple users" patterns that the throttle can't.
    # Nullable because legacy rows pre-date the field; the alert
    # task skips ``requested_ip IS NULL`` rows to avoid false
    # positives.
    requested_ip = models.GenericIPAddressField(blank=True, null=True, db_index=True)

    state = models.CharField(
        max_length=20,
        choices=DeletionRequestState.choices,
        default=DeletionRequestState.PENDING_EMAIL,
        db_index=True,
    )

    # --- email confirmation gate -----------------------------------
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    token_expires_at = models.DateTimeField()
    email_confirmed_at = models.DateTimeField(blank=True, null=True)
    email_confirmed_ip = models.GenericIPAddressField(blank=True, null=True)

    # --- admin approval gate (only consulted if requires_admin_approval) ---
    # admin_confirmed / admin_confirmed_by / admin_confirmed_at /
    # admin_rejection_reason come from AdminConfirmableMixin.
    requires_admin_approval = models.BooleanField(
        default=True,
        help_text="True (default) means an office/admin must approve "
        "after the email-confirm step. Set at create time by "
        "``GDPRService.request_deletion`` from tenant settings + "
        "persona role; never flipped on a live request.",
    )

    # --- execution -------------------------------------------------
    executed_at = models.DateTimeField(blank=True, null=True)
    # Stamped when this request is cancelled because the user re-requested
    # (superseded). The successor row already captures the actor + time of the
    # new request; this marks WHEN the old row was retired so the Art. 17 paper
    # trail shows the transition instead of a bare, unstamped state flip.
    superseded_at = models.DateTimeField(blank=True, null=True)
    deletion_log = models.ForeignKey(
        "DeletionLog",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        help_text="Pointer to the audit-log row written when the "
        "request was actually executed.",
    )

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            # Hot path: "is there an open request for this user?" — used
            # both when superseding old requests and when the admin UI
            # filters pending rows.
            models.Index(fields=["user", "state"]),
        ]
        constraints = [
            # DB-level backstop for the lifecycle timestamp ordering enforced
            # in clean(). Bulk paths (.update() / raw SQL / imports) bypass
            # clean(), so these guard against an out-of-order stamp landing
            # directly. All NULL-tolerant: only enforced when both sides are
            # set. requested_at is non-null (auto_now_add); token_expires_at is
            # non-null (defaulted in save()).
            models.CheckConstraint(
                condition=Q(email_confirmed_at__isnull=True)
                | Q(email_confirmed_at__gte=F("requested_at")),
                name="deletionrequest_email_confirmed_after_requested",
            ),
            models.CheckConstraint(
                condition=Q(admin_confirmed_at__isnull=True)
                | Q(email_confirmed_at__isnull=True)
                | Q(admin_confirmed_at__gte=F("email_confirmed_at")),
                name="deletionrequest_admin_confirmed_after_email_confirmed",
            ),
            models.CheckConstraint(
                condition=Q(executed_at__isnull=True)
                | Q(admin_confirmed_at__isnull=True)
                | Q(executed_at__gte=F("admin_confirmed_at")),
                name="deletionrequest_executed_after_admin_confirmed",
            ),
            models.CheckConstraint(
                condition=Q(executed_at__isnull=True)
                | Q(email_confirmed_at__isnull=True)
                | Q(executed_at__gte=F("email_confirmed_at")),
                name="deletionrequest_executed_after_email_confirmed",
            ),
            models.CheckConstraint(
                condition=Q(email_confirmed_at__isnull=True)
                | Q(email_confirmed_at__lte=F("token_expires_at")),
                name="deletionrequest_email_confirmed_before_token_expiry",
            ),
            models.CheckConstraint(
                condition=Q(superseded_at__isnull=True)
                | Q(superseded_at__gte=F("requested_at")),
                name="deletionrequest_superseded_after_requested",
            ),
        ]

    def __str__(self) -> str:
        return f"DeletionRequest<{self.requested_email} {self.state}>"

    def clean(self) -> None:
        """Enforce the lifecycle timestamp ordering.

        The deletion flow stamps timestamps in a fixed order:
        ``requested_at <= email_confirmed_at <= admin_confirmed_at <=
        executed_at``. The token must be confirmed before it expires
        (``email_confirmed_at <= token_expires_at``) and a supersession
        can only happen after the request was made
        (``superseded_at >= requested_at``).

        Every comparison is NULL-tolerant: an out-of-order pair is only
        rejected when BOTH timestamps are set, so a partially-filled
        lifecycle row never trips the check.
        """
        super().clean()

        if (
            self.email_confirmed_at is not None
            and self.requested_at is not None
            and self.email_confirmed_at < self.requested_at
        ):
            raise ValidationError(
                {
                    "email_confirmed_at": "Email confirmation cannot be before "
                    "the request was made."
                }
            )

        if (
            self.admin_confirmed_at is not None
            and self.email_confirmed_at is not None
            and self.admin_confirmed_at < self.email_confirmed_at
        ):
            raise ValidationError(
                {
                    "admin_confirmed_at": "Admin approval cannot be before "
                    "email confirmation."
                }
            )

        if (
            self.executed_at is not None
            and self.admin_confirmed_at is not None
            and self.executed_at < self.admin_confirmed_at
        ):
            raise ValidationError(
                {"executed_at": "Execution cannot be before admin approval."}
            )

        if (
            self.executed_at is not None
            and self.email_confirmed_at is not None
            and self.executed_at < self.email_confirmed_at
        ):
            raise ValidationError(
                {"executed_at": "Execution cannot be before email confirmation."}
            )

        if (
            self.email_confirmed_at is not None
            and self.token_expires_at is not None
            and self.email_confirmed_at > self.token_expires_at
        ):
            raise ValidationError(
                {
                    "email_confirmed_at": "Email confirmation cannot be after "
                    "the token has expired."
                }
            )

        if (
            self.superseded_at is not None
            and self.requested_at is not None
            and self.superseded_at < self.requested_at
        ):
            raise ValidationError(
                {
                    "superseded_at": "Supersession cannot be before the "
                    "request was made."
                }
            )

    def save(self, *args, **kwargs):
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + DELETION_TOKEN_TTL
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------ #
    # Computed helpers — read-only convenience for views/serializers     #
    # ------------------------------------------------------------------ #

    @property
    def is_open(self) -> bool:
        """True while the request is still working its way toward
        execution. Once it hits any terminal state (executed / expired
        / cancelled / rejected) this turns False."""
        return self.state in (
            DeletionRequestState.PENDING_EMAIL,
            DeletionRequestState.PENDING_ADMIN,
            DeletionRequestState.APPROVED,
        )

    @property
    def is_token_expired(self) -> bool:
        return timezone.now() > self.token_expires_at
