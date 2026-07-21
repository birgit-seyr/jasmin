from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField

from apps.shared.iban_validator import validate_iban

from .base import JasminModel
from .choices import InvitationStatus
from .mixin import (
    AdminConfirmableMixin,
    CancellableMixin,
    CreatedMixin,
    PayableMixin,
    TimeBoundMixin,
    WaitingListMixin,
    nullable_date_order_constraint,
    time_bound_valid_range_constraint,
    validate_nullable_date_order,
)


class Member(
    JasminModel,
    AdminConfirmableMixin,
    CancellableMixin,
    CreatedMixin,
    WaitingListMixin,
):
    # NOT "membership is active" — a member's lifecycle is pending →
    # admin-confirmed → cancelled (see admin_confirmed / cancelled_at). This
    # flag is the GDPR soft-disable: ``gdpr.anonymization`` sets it False, and
    # the renewal sweep + office renew button skip is_active=False members
    # (SKIP_MEMBER_INACTIVE) so an anonymised member is never renewed. Do not
    # surface it as a user-facing "active members" count.
    is_active = models.BooleanField(default=True, db_index=True)
    entry_date = models.DateField(blank=True, null=True)
    is_trial = models.BooleanField(default=False)
    # When a trial member converts to a real (GenG) member — typically
    # by acquiring their first ``CoopShare``. ``None`` means either
    # "still on trial" (when ``is_trial=True``) or "joined as a full
    # member directly, never was a trial" (when ``is_trial=False``).
    # Stamped by the conversion hook in the CoopShare acquisition
    # service, never by hand.
    trial_converted_at = models.DateTimeField(blank=True, null=True)
    # GenG §30 requires Eintritts- AND Austrittsdatum on the members
    # list. ``cancelled_at`` (timestamp the office recorded it) +
    # ``cancelled_effective_at`` (legal exit date — typically year-end
    # after a notice period) come from ``CancellableMixin``. Derive
    # "is this member cancelled?" via ``Member.cancelled_at is not None``
    # — no separate boolean flag.
    # ``cancellation_email_sent_at`` records when (and if) the
    # ``commissioning.member_cancelled`` confirmation email was
    # dispatched. Stamped by ``cancel_member_with_coop_shares`` after the
    # send returns ``ok=True``, NEVER inside the cancellation
    # transaction — see P2-3. NULL means either "no email sent yet"
    # OR "no email could be sent" (member.email empty, GDPR-
    # anonymised path, transport failure).
    cancellation_email_sent_at = models.DateTimeField(blank=True, null=True)
    # Collected for statutory reasons (cooperative member-registry
    # documentation) — intentionally unused by application logic.
    # Do not remove as "dead data"; it is classified PII and handled
    # by the GDPR export/anonymisation machinery like every other
    # Member field.
    birth_date = models.DateField(blank=True, null=True)

    user = models.OneToOneField(
        "accounts.JasminUser",
        on_delete=models.SET_NULL,
        related_name="member_profile",
        blank=True,
        null=True,
    )

    # Not every Member has a linked JasminUser (and vice versa), so first/last
    # name live on BOTH models independently. The Member row is authoritative
    # for member-facing displays/exports; the User row's name is only used for
    # auth/account UI. They are intentionally NOT kept in sync — a mismatch is
    # allowed (e.g. an account holder managing a household member's share).
    member_number = models.PositiveIntegerField(unique=True, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    pickup_name = models.CharField(max_length=255, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    zip_code = models.CharField(max_length=10, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    number_of_rates = models.PositiveSmallIntegerField(
        default=0
    )  # this means rate payment / monthly

    # Payment data — encrypted at rest. SEPA + bank-account info is
    # the highest-sensitivity PII on this model; column ciphertext
    # protects against partial DB-only breaches. Decryption is
    # transparent on Python-side access, so callers don't change.
    account_owner = EncryptedCharField(max_length=255, blank=True, null=True)
    iban = EncryptedCharField(
        max_length=34, blank=True, null=True, validators=[validate_iban]
    )
    sepa_consent = models.DateTimeField(blank=True, null=True)
    withdrawal_consent = models.DateTimeField(blank=True, null=True)
    privacy_consent = models.DateTimeField(blank=True, null=True)
    # Set when the member withdraws a privacy / withdrawal-terms consent (a
    # processing-legal-basis withdrawal that needs office review); cleared when
    # they re-consent. Surfaces "needs a consent review" to the office, which is
    # also emailed at withdrawal time (ConsentService.revoke).
    consent_withdrawn_at = models.DateTimeField(blank=True, null=True)
    # Office stamp: when the signed PAPER membership declaration was physically
    # received. Only relevant when the tenant requires a paper signature for
    # membership; the office ticks a checkbox that sets this to today.
    membership_paper_received_at = models.DateField(blank=True, null=True)
    # Optional free-text reason captured when the membership is cancelled
    # (office- or member-initiated). cancelled_at/effective_at/by come from
    # CancellableMixin; this is the "why".
    cancellation_reason = models.TextField(blank=True, null=True)
    is_student = models.BooleanField(default=False)
    email = models.EmailField(max_length=255, null=True, blank=True, unique=True)
    email_2 = models.CharField(max_length=255, null=True, blank=True)
    email_3 = models.CharField(max_length=255, null=True, blank=True)

    note = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            # Keep only indexes that aren't subsumed by larger composites.
            # ``last_name, first_name`` covers "last_name only" too;
            # ``is_trial, is_active`` covers "is_active only". The
            # ``member_number`` and ``email`` equality lookups (login/recovery)
            # are already served by their ``unique=True`` B-tree indexes — no
            # explicit Index needed (an extra one is pure write amplification).
            models.Index(fields=["is_trial", "is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["last_name", "first_name"]),
            # Drives the nightly ``anonymise_long_cancelled_members``
            # Huey sweep (apps/gdpr/tasks.py) — a daily full-table scan
            # over every tenant's Members would be wasteful once the
            # platform has a few thousand cancelled rows. ``WHERE
            # cancelled_effective_at <= cutoff`` is the only access
            # pattern that uses this column at scale.
            models.Index(fields=["cancelled_effective_at"]),
        ]
        constraints = [
            # Date-order backstops for the bulk paths that bypass ``clean()``.
            # All NULL-tolerant: only enforced when both members of a pair are
            # set. The ``cancelled_effective_at >= cancelled_at.date()`` rule
            # comes from CancellableMixin.clean() (datetime-vs-date, no DB
            # constraint).
            nullable_date_order_constraint(
                "cancelled_effective_at",
                "entry_date",
                name="member_cancelled_effective_after_entry",
            ),
            nullable_date_order_constraint(
                "entry_date",
                "birth_date",
                name="member_entry_after_birth",
            ),
            # ``trial_converted_at`` is a DateTimeField, ``entry_date`` a
            # DateField — cast the timestamp to date so the comparison matches
            # the Python ``trial_converted_at.date() >= entry_date`` check.
            # NOTE: the DB-level date-cast is pinned to the operator's LOCAL
            # timezone by migration 0034 (``entry_date`` is a local calendar
            # day, so Django's default UTC cast fired a day early near the
            # local/UTC midnight boundary). If this constraint is ever
            # regenerated, re-apply that local-tz cast.
            models.CheckConstraint(
                condition=Q(trial_converted_at__isnull=True)
                | Q(entry_date__isnull=True)
                | Q(trial_converted_at__date__gte=F("entry_date")),
                name="member_trial_converted_after_entry",
            ),
        ]

    def __str__(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        name = " ".join(parts)
        if self.member_number:
            return (
                f"{name} (#{self.member_number})" if name else f"#{self.member_number}"
            )
        return name or self.get_display_id()

    @property
    def display_name(self) -> str:
        """Canonical display name — the company name when set, otherwise the
        natural ``first last`` (mirrors ``ContactEntity.name``). Carries no
        member-number suffix; that's ``__str__``'s job. The member register
        export deliberately renders surname-first instead (a formal-list
        convention matching its ``last_name`` sort), so it keeps its own
        formatter rather than reusing this."""
        if self.company_name:
            return self.company_name
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    def clean(self) -> None:
        super().clean()
        # Cross-field date-order guards. NULL-tolerant: each pair is only
        # enforced when both members are set. ``cancelled_effective_at`` vs
        # ``cancelled_at`` is enforced by CancellableMixin.clean().
        validate_nullable_date_order(
            self,
            "cancelled_effective_at",
            "entry_date",
            message=("Effective cancellation date must be on or after the entry date."),
        )
        validate_nullable_date_order(
            self,
            "entry_date",
            "birth_date",
            message="Entry date must be on or after the birth date.",
        )
        # ``trial_converted_at`` is a UTC DateTimeField, ``entry_date`` a LOCAL
        # calendar day — compare on the trial_converted_at date IN THE OPERATOR'S
        # LOCAL timezone (``.date()`` would give the UTC date, a day early near
        # the local/UTC midnight boundary; mirrors the DB constraint pinned to
        # local tz in migration 0034).
        if (
            self.trial_converted_at is not None
            and self.entry_date is not None
            and timezone.localtime(self.trial_converted_at).date() < self.entry_date
        ):
            raise ValidationError(
                {
                    "trial_converted_at": (
                        "Trial conversion date must be on or after the entry date."
                    )
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Validate on every save so the cross-field date-order guards in clean()
        # actually fire on the normal write path — a DjangoValidationError maps
        # to a 400 with the offending field, instead of the DB CheckConstraint
        # tripping a generic 409. validate_unique=False: email / member_number
        # uniqueness is already DB-enforced, and a per-save uniqueness query on
        # this frequently-saved model (role syncs re-save on every change) isn't
        # worth it — a duplicate still surfaces as the DB IntegrityError.
        self.full_clean(validate_unique=False)
        # MEM-7: capture the previously-linked user BEFORE the write so an
        # unlink (user→None) or relink (A→B) retracts Role.MEMBER from the old
        # user — the linking invariant is bidirectional. Role grant alone (the
        # old behaviour) left an offboarded/relinked user still carrying MEMBER.
        prev_user_id = (
            Member.objects.filter(pk=self.pk).values_list("user_id", flat=True).first()
            if self.pk
            else None
        )
        super().save(*args, **kwargs)
        # A user linked to a Member row always carries Role.MEMBER.
        if self.user_id:
            from apps.commissioning.services.member_role_sync import (
                ensure_member_role,
            )

            ensure_member_role(self.user)
        # The previously-linked user, if no longer linked to ANY member, loses
        # the role (retract_member_role also deactivates a now-role-less user).
        if (
            prev_user_id
            and prev_user_id != self.user_id
            and not Member.objects.filter(user_id=prev_user_id).exists()
        ):
            from apps.accounts.models import JasminUser
            from apps.commissioning.services.member_role_sync import (
                retract_member_role,
            )

            prev_user = JasminUser.objects.filter(pk=prev_user_id).first()
            if prev_user is not None:
                retract_member_role(prev_user)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        user = self.user if self.user_id else None
        result = super().delete(*args, **kwargs)
        if user is not None:
            from apps.commissioning.services.member_role_sync import (
                retract_member_role,
            )

            retract_member_role(user)
        return result

    @property
    def active_subscriptions_count(self) -> int:
        """Number of currently-active, admin-confirmed subscriptions for this member.

        NOTE: ``MemberViewSet.get_queryset`` annotates this same name on
        the queryset so list endpoints don't pay an N+1 cost (locked by
        ``apps/payments/tests/test_query_count_locks.py``). Because
        ``@property`` is a data descriptor, the annotation cannot shadow
        a property of the same name on bound instances — Django sets the
        annotation on ``__dict__`` but Python's descriptor protocol
        prefers the property. We therefore detect a stashed annotation
        value and return it instead of running the count.
        """
        cached = self.__dict__.get("_active_subscriptions_count_annotation")
        if cached is not None:
            return cached
        today = timezone.now().date()
        # The badge counts subscriptions active RIGHT NOW (``active_at_date``
        # adds ``valid_from <= today``), which is deliberately NARROWER than the
        # cancellation restraint ``Subscription.active_for_member`` (that guards
        # any un-ended commitment, including a future-dated confirmed one).
        return (
            Subscription.current.active_at_date(today)
            .filter(
                member=self,
                admin_confirmed=True,
                cancelled_at__isnull=True,
            )
            .count()
        )

    @active_subscriptions_count.setter
    def active_subscriptions_count(self, value: int) -> None:
        # Django sets attributes from queryset annotations via setattr().
        # Stash under a private key so the getter can find it without
        # clashing with the property's own descriptor lookup.
        self.__dict__["_active_subscriptions_count_annotation"] = value

    def _generate_member_number(self) -> None:
        # Mirrors ``FinalizableDocumentMixin.save_with_number_retry``
        # (apps/commissioning/models/mixin.py): serialise concurrent
        # writers with ``pg_advisory_xact_lock`` so ``Max(member_number)+1``
        # is computed inside the lock.
        from django.db import transaction

        from core.db_locks import acquire_advisory_xact_lock

        with transaction.atomic():
            acquire_advisory_xact_lock("member_number:sequence")
            last_number = Member.objects.aggregate(
                max_number=models.Max("member_number")
            )["max_number"]
            self.member_number = (last_number or 0) + 1
            self.save(update_fields=["member_number"])

    def confirm(self, admin_user, *, save: bool = True) -> None:
        # GenG admission gate on EVERY confirm entry-point (confirm_and_notify,
        # the Subscription-confirm cascade, link_to_user, accept_invitation): a
        # non-trial member may only enter the Mitgliederliste with total equity
        # inside the configured min/max window. Checked BEFORE flipping
        # admin_confirmed so a violation never leaves a half-admitted row. The
        # service no-ops for trial members and when no min/max is configured.
        from apps.commissioning.services.coop_share_service import CoopShareService

        CoopShareService.assert_member_total_within_bounds(self)
        super().confirm(admin_user, save=save)

    def _post_confirm(self, *, admin_user) -> None:
        """Materialise side-effects of admin-confirming a Member.

        Full (GenG) members get the trio of "you're now a Genosse"
        artifacts stamped together:

        * ``member_number`` — Mitgliedsnummer per the Mitgliederliste.
        * ``entry_date``    — Eintrittsdatum (GenG §30): the date the
          Vorstand admitted the member into the Mitgliederliste,
          i.e. today. NOT the share-payment date (separate under §7a)
          and NOT a member-chosen value.

        Trial members get NEITHER. They are not Mitglieder under GenG
        (no Geschäftsanteil yet), so no Mitgliedsnummer and no
        Eintrittsdatum. The conversion hook in
        ``convert_trial_member_on_first_coop_share`` stamps both when
        ``is_trial`` flips to False.

        The linked JasminUser is also activated here if it was waiting on
        admin approval. That's unrelated to GenG and fires for trial
        members too.
        """
        from django.utils import timezone as _timezone

        if not self.is_trial:
            updated_fields: list[str] = []
            if not self.member_number:
                # ``_generate_member_number`` saves under an advisory
                # lock; once it returns the row is up to date.
                self._generate_member_number()
            if not self.entry_date:
                self.entry_date = _timezone.localdate()
                updated_fields.append("entry_date")
            if updated_fields:
                self.save(update_fields=updated_fields)
        # Self-registered users wait in pending_approval until a member is
        # confirmed. Invitation-flow users stay in pending_invitation until
        # they accept the invite.
        if self.user_id and self.user.account_status == "pending_approval":
            self.user.account_status = "active"
            self.user.save(update_fields=["account_status", "is_active"])


class CoopShare(JasminModel, PayableMixin, AdminConfirmableMixin, CancellableMixin):
    # PROTECT: Geschäftsanteile (cooperative equity) have statutory retention
    # under German GenG. A Member.delete() must not silently wipe equity
    # history — block at the ORM layer instead.
    member = models.ForeignKey("Member", on_delete=models.PROTECT, related_name="+")
    amount_of_coop_shares = models.DecimalField(max_digits=10, decimal_places=2)
    value_one_coop_share = models.PositiveIntegerField()

    is_increase = models.BooleanField(
        default=False
    )  # for increases of the originally mandatory amount of coop shares
    note = models.TextField(blank=True, null=True)
    # Cooperative-equity payback after the member exits. ``payback_due_date`` is
    # snapshotted when the member is cancelled (= cancelled_effective_at +
    # TenantSettings.retention_period_cancelled_members_coop_shares_in_months),
    # so it stays frozen even if the tenant later changes the retention. The
    # office stamps ``paid_back_date`` when the share value is actually returned.
    payback_due_date = models.DateField(blank=True, null=True)
    paid_back_date = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            # Date-order backstops for the bulk paths that bypass ``clean()``.
            # All NULL-tolerant: only enforced when both members of a pair are
            # set. ``paid_at >= due_date`` comes from PayableMixin.clean() and
            # ``cancelled_effective_at >= cancelled_at.date()`` from
            # CancellableMixin.clean() (both datetime-vs-date, no DB
            # constraint).
            nullable_date_order_constraint(
                "payback_due_date",
                "cancelled_effective_at",
                name="coopshare_payback_due_after_cancel_effective",
            ),
            nullable_date_order_constraint(
                "paid_back_date",
                "payback_due_date",
                name="coopshare_paid_back_after_payback_due",
            ),
        ]

    def __str__(self) -> str:
        return f"CoopShare {self.amount_of_coop_shares} for {self.member}"

    def clean(self) -> None:
        super().clean()
        # Date-order guards (the cancel/payback equity-return lifecycle).
        # NULL-tolerant: each pair is only enforced when both members are set.
        # ``paid_at >= due_date`` is enforced by PayableMixin.clean() and
        # ``cancelled_effective_at >= cancelled_at`` by CancellableMixin.clean().
        validate_nullable_date_order(
            self,
            "payback_due_date",
            "cancelled_effective_at",
            message=(
                "Payback due date must be on or after the effective "
                "cancellation date."
            ),
        )
        validate_nullable_date_order(
            self,
            "paid_back_date",
            "payback_due_date",
            message="Paid-back date must be on or after the payback due date.",
        )
        # Service holds the actual logic so bulk paths can reuse it.
        from apps.commissioning.services.coop_share_service import CoopShareService

        # A cancelled (divested) coop share is no longer live equity, so it
        # contributes 0 to the GenG window — the aggregate already excludes the
        # member's other cancelled shares.
        new_amount = 0 if self.cancelled_at else self.amount_of_coop_shares
        CoopShareService.assert_within_min_max(
            member=self.member,
            new_amount=new_amount,
            exclude_pk=self.pk,
        )

        # MEM-8: a reassignment (member changed on an existing share) must also
        # re-validate the LOSING member — the share leaving could drop their
        # live equity below the GenG minimum, which the new-member check above
        # never sees. exclude_pk so this departing share isn't counted for them.
        if self.pk:
            prev_member_id = (
                CoopShare.objects.filter(pk=self.pk)
                .values_list("member_id", flat=True)
                .first()
            )
            if prev_member_id and prev_member_id != self.member_id:
                prev_member = Member.objects.filter(pk=prev_member_id).first()
                if prev_member is not None:
                    CoopShareService.assert_within_min_max(
                        member=prev_member,
                        new_amount=0,
                        exclude_pk=self.pk,
                    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def confirm(self, admin_user, *, save: bool = True) -> None:
        """Confirm the share AND, if it admits a trial member into the
        Mitgliederliste, convert them trial→full.

        Trial conversion fires here — on CONFIRMATION — not at creation:
        acquiring *confirmed* equity is the GenG-level act that turns a trial
        member into a Mitglied. A member's self-subscribed share is created
        ``admin_confirmed=False`` (pending) and must NOT prematurely convert
        them; if such a pending share were later cancelled before the office
        confirmed it, a save-time conversion would leave the member wrongly
        locked into full status below the min-equity window. Office-created
        shares auto-confirm (CoopShareViewSet.perform_create), so they still
        convert in lock-step. Conversion enforces the GenG min/max window, so
        keep confirm + conversion in one atomic unit.
        """
        # Never confirm equity for a member who has initiated their exit
        # (cancelled_at set) — confirming a leftover pending share would
        # re-admit a departed member (stamp entry_date/member_number, fire the
        # admission email, run trial→full conversion). This is the chokepoint
        # for BOTH the office ``confirm`` action and ``perform_create``'s
        # auto-confirm.
        if self.member_id and self.member.cancelled_at is not None:
            from apps.commissioning.errors import MemberAlreadyCancelled

            raise MemberAlreadyCancelled(
                "Cannot confirm a coop share for a cancelled member."
            )
        with transaction.atomic():
            super().confirm(admin_user, save=save)
            if save and self.member_id:
                from apps.commissioning.services.trial_conversion import (
                    convert_trial_member_on_first_coop_share,
                )

                convert_trial_member_on_first_coop_share(self.member)


class UserInvitation(JasminModel, CreatedMixin):
    # Invitation may be linked to a Member (Scenario 1: staff creates a
    # Member without account, then invites them) OR may stand alone for
    # non-member users like staff/admin (configuration -> Users -> Invite).
    member = models.ForeignKey(
        "Member",
        on_delete=models.CASCADE,
        related_name="+",
        null=True,
        blank=True,
    )
    # The user account that has been provisioned in `pending_invitation`
    # state. Set as soon as the invitation is created. NULL only for legacy
    # rows.
    user = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.CASCADE,
        related_name="invitations",
        null=True,
        blank=True,
    )

    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True)

    status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.SENT,
    )

    expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self) -> str:
        return f"Invitation for {self.member} to {self.email} ({self.status})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at and self.status == InvitationStatus.SENT


class Subscription(
    JasminModel,
    AdminConfirmableMixin,
    TimeBoundMixin,
    CreatedMixin,
    CancellableMixin,
    WaitingListMixin,
):
    """
    Represents a specific subscription period (trial, annual term, etc.).

    A renewal is a new Subscription whose ``previous_subscription`` points at
    the prior term; that chain replaces the former SubscriptionGroup.
    """

    # NOTE: no ``overlap_unique_fields`` — subscriptions are intentionally
    # independent. Two subscriptions for the same member + variation may
    # coexist (e.g. a renewal term materialised before the prior term ends);
    # there is deliberately no succession-closing or overlap-uniqueness here.
    member = models.ForeignKey(
        "Member", on_delete=models.CASCADE, related_name="subscriptions"
    )
    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.PROTECT, null=False
    )

    # The cancellation rationale now lives directly on the subscription it
    # explains (formerly carried by SubscriptionGroup).
    cancellation_reason = models.TextField(blank=True, null=True)

    # Why this subscription is on the waiting list — ``WaitingListMixin`` only
    # records THAT it is. Set server-side at enqueue so the office can see which
    # capacity gate was full. ``None`` when the sub isn't waiting_listed.
    class WaitingListReason(models.TextChoices):
        DELIVERY_STATION_FULL = (
            "delivery_station_full",
            "Delivery station full",
        )
        VARIATION_FULL = "variation_full", "Share type sold out"
        MANUAL = "manual", "Manually queued"

    waiting_list_reason = models.CharField(
        max_length=32,
        choices=WaitingListReason.choices,
        blank=True,
        null=True,
    )

    is_trial = models.BooleanField(default=False)

    # The predecessor term in a renewal chain. ``related_name="renewals"`` lets
    # us ask "has this subscription been renewed yet?" — the daily renewal job
    # skips subscriptions that already have a renewal.
    previous_subscription = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="renewals",
    )

    # Human-facing chain identifier. ``subscription_number`` is shared across a
    # renewal chain (assigned once on the first term, inherited by every
    # renewal); ``renewal_generation`` is the position in the chain (0 = the
    # original, 1 = first renewal, …). Together they render as ``1042a`` /
    # ``1042b`` / … via ``renewal_display_id``. Both are assigned in ``save()``.
    subscription_number = models.PositiveIntegerField(
        null=True, blank=True, db_index=True
    )
    renewal_generation = models.PositiveSmallIntegerField(default=0)

    # Pricing and payment
    quantity = models.PositiveSmallIntegerField(default=1, null=False)
    price_per_delivery = models.DecimalField(
        decimal_places=2, max_digits=8, null=True, blank=True
    )
    payment_cycle = models.ForeignKey(
        "PaymentCycle", on_delete=models.PROTECT, null=False
    )

    notice_period_duration = models.IntegerField(null=True, blank=True)
    default_delivery_station_day = models.ForeignKey(
        "DeliveryStationDay",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(TimeBoundMixin.Meta):
        # Inherit base_manager_name + ordering from TimeBoundMixin; the
        # valid-range check is wired explicitly via the shared helper, same as
        # every other TimeBoundMixin subclass (it is no longer declared on the
        # abstract Meta). Declaring ``constraints`` here overrides the inherited
        # (now-empty) one.
        constraints = [
            time_bound_valid_range_constraint("subscription_valid_range"),
            # A cancellation can't take effect AFTER the subscription's term
            # ends. NULL-tolerant: an open-ended subscription (``valid_until``
            # NULL) or an uncancelled row (``cancelled_effective_at`` NULL) is
            # exempt. ``cancelled_effective_at >= cancelled_at.date()`` comes
            # from CancellableMixin.clean() (datetime-vs-date, no DB constraint).
            #
            # NOTE: there is intentionally NO cancelled_effective_at >=
            # valid_from constraint. The member-exit cascade force-ends a
            # not-yet-started subscription effective on the member's exit date,
            # which legitimately precedes valid_from (the member leaves before
            # the subscription's term begins). See
            # member_cancellation._force_end_subscription.
            models.CheckConstraint(
                condition=Q(cancelled_effective_at__isnull=True)
                | Q(valid_until__isnull=True)
                | Q(cancelled_effective_at__lte=F("valid_until")),
                name="subscription_cancel_before_valid_until",
            ),
            # At most one renewal per predecessor. The renewal flow's
            # "already renewed?" guard is a constraint-free read with no row
            # lock, so a daily-task-vs-bulk race or a double-submit could
            # otherwise insert two drafts pointing at the same predecessor
            # (a forked chain that double-bills on confirm). This partial
            # unique index makes the DB the source of truth: every racing
            # second insert is a caught IntegrityError (counted as failed,
            # never aborting the batch). Partial because most subscriptions
            # are roots with a NULL predecessor.
            models.UniqueConstraint(
                fields=["previous_subscription"],
                condition=Q(previous_subscription__isnull=False),
                name="subscription_one_renewal_per_predecessor",
            ),
        ]
        indexes = [
            models.Index(fields=["member", "valid_from"]),
            models.Index(fields=["share_type_variation", "valid_from"]),
            models.Index(fields=["valid_from", "valid_until"]),
        ]

    def __str__(self) -> str:
        trial_text = "Trial " if self.is_trial else ""
        return f"{trial_text}Subscription for {self.member} ({self.valid_from} - {self.valid_until or 'ongoing'})"

    def clean(self) -> None:
        super().clean()

        # Once a subscription is admin-confirmed its Shares / ShareDeliveries are
        # materialised and keyed by ``share_type_variation``; changing it would
        # orphan that data (deliveries still reference the OLD variation). Lock
        # it after confirmation — an unconfirmed draft (incl. an auto-renewal the
        # office is still reviewing) may still be re-pointed.
        if self.pk and not self._state.adding and self.admin_confirmed:
            old_variation_id = (
                Subscription.objects.filter(pk=self.pk)
                .values_list("share_type_variation_id", flat=True)
                .first()
            )
            if (
                old_variation_id is not None
                and old_variation_id != self.share_type_variation_id
            ):
                from apps.commissioning.errors import SubscriptionVariationLocked

                raise SubscriptionVariationLocked(
                    "Cannot change a confirmed subscription's "
                    "share_type_variation; create a new subscription instead.",
                    field="share_type_variation",
                )

        # A cancellation can't take effect after the term ends. NULL-tolerant:
        # only enforced when both ``cancelled_effective_at`` and ``valid_until``
        # are set. ``valid_from <= valid_until`` is guarded by TimeBoundMixin;
        # ``cancelled_effective_at >= cancelled_at`` by CancellableMixin.clean().
        #
        # There is intentionally no lower-bound (>= valid_from) check: the
        # member-exit cascade force-ends a not-yet-started subscription
        # effective on the member's exit date, which legitimately precedes
        # valid_from.
        if (
            self.cancelled_effective_at is not None
            and self.valid_until is not None
            and self.cancelled_effective_at > self.valid_until
        ):
            raise ValidationError(
                {
                    "cancelled_effective_at": (
                        "Effective cancellation date must be on or before the "
                        "subscription end date."
                    )
                }
            )

        # DSD validity-window check lives in the service so bulk paths can
        # reuse the same logic.
        from apps.commissioning.services.subscription_service import (
            SubscriptionService,
        )

        SubscriptionService.assert_delivery_station_day_covers_subscription(
            delivery_station_day=self.default_delivery_station_day,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
        )

    # NOTE: NO ``overlap_unique_fields`` — subscriptions are independent, so
    # ``TimeBoundMixin`` runs neither the overlap check nor succession-closing.
    # ``save()`` is overridden ONLY to assign the renewal-chain identifier; it
    # still calls ``super().save()`` (TimeBoundMixin → ``clean()``, incl. the
    # DSD validity-window check above).
    def save(self, *args, **kwargs) -> None:
        # A subscription must have a finite, billable term. Open-ended subs
        # materialise no ShareDeliveries and silently never bill (CHG-1). The
        # serializer blocks this on the API; this is the model-level backstop
        # for factories / imports / seed scripts / direct ORM writes — every
        # save path lands here, so an open-ended subscription is not possible.
        if self.valid_until is None:
            from apps.commissioning.errors import OpenEndedSubscriptionNotAllowed

            raise OpenEndedSubscriptionNotAllowed(
                "A subscription must have an end date (valid_until); "
                "open-ended subscriptions are not allowed.",
                field="valid_until",
            )
        if self.subscription_number is not None:
            super().save(*args, **kwargs)
            return
        # On a renewal, inherit the chain's number and bump the generation.
        if self.previous_subscription_id:
            predecessor = (
                Subscription.objects.filter(pk=self.previous_subscription_id)
                .values("subscription_number", "renewal_generation")
                .first()
            )
            if predecessor and predecessor["subscription_number"] is not None:
                self.subscription_number = predecessor["subscription_number"]
                self.renewal_generation = predecessor["renewal_generation"] + 1
                super().save(*args, **kwargs)
                return
            # A renewal must NEVER become a chain root: falling through to the
            # fresh-Max()+1 branch would assign a DIFFERENT number at
            # generation=0, silently splitting the shared-number-across-the-
            # chain invariant. A NULL predecessor number is only reachable when
            # the predecessor was created bypassing save() (bulk_create /
            # partial import) — refuse loudly instead of forking the chain.
            from apps.commissioning.errors import RenewalChainNumberMissing

            raise RenewalChainNumberMissing(
                "The predecessor subscription has no subscription_number to "
                "inherit — fix the predecessor's numbering before renewing."
            )
        # Otherwise take the next sequential number, serialising the ``Max()+1``
        # AND the insert under one advisory lock so two concurrent creates can't
        # claim the same number (mirrors ``Member._generate_member_number``).
        from django.db import transaction

        from core.db_locks import acquire_advisory_xact_lock

        with transaction.atomic():
            acquire_advisory_xact_lock("subscription_number:sequence")
            last = Subscription.objects.aggregate(
                max_number=models.Max("subscription_number")
            )["max_number"]
            self.subscription_number = (last or 0) + 1
            super().save(*args, **kwargs)

    def _post_confirm(self, *, admin_user) -> None:
        """Materialise Shares + ShareDeliveries + ChargeSchedule on confirm.

        Also cascades confirmation to the owning Member if it is not yet
        admin-confirmed (a confirmed subscription implies the member is
        accepted). Confirmation does NOT cascade the other way around.
        """
        from apps.commissioning.services.subscription_service import (
            SubscriptionService,
        )

        member = self.member
        # Don't back-cascade confirmation onto a member who has initiated their
        # exit (cancelled_at set) — they should not be re-admitted by confirming
        # a leftover subscription. The confirm endpoint already blocks this; the
        # guard here is defense-in-depth for any other confirm() caller.
        if member and not member.admin_confirmed and member.cancelled_at is None:
            member.confirm(admin_user)

        SubscriptionService().materialize_confirmed_subscription(self, actor=admin_user)

    @property
    def display_id(self) -> str:
        return self.get_display_id()

    @property
    def renewal_display_id(self) -> str:
        """Chain identifier as ``1`` / ``1a`` / ``1b`` / … — the shared
        ``subscription_number``, with a generation letter for renewals only
        (the original term has no letter, the first renewal is ``a``, the
        second ``b``, …). Falls back to the raw display id until a number is
        assigned. Sort the chain by ``(subscription_number, renewal_generation)``
        to get ``1, 1a, 1b, 2, 2a, …`` — NOT by this string."""
        if self.subscription_number is None:
            return self.get_display_id()
        if self.renewal_generation == 0:
            return str(self.subscription_number)
        if self.renewal_generation <= 26:
            suffix = chr(ord("a") + self.renewal_generation - 1)
        else:
            suffix = f".{self.renewal_generation}"
        return f"{self.subscription_number}{suffix}"

    @property
    def is_current(self) -> bool:
        """Check if this subscription period is currently active"""
        today = timezone.now().date()
        if not self.valid_from:
            return False
        if self.valid_until is None:
            return today >= self.valid_from
        return self.valid_from <= today <= self.valid_until

    @property
    def is_expired(self) -> bool:
        if self.valid_until is None:
            return False
        return timezone.now().date() > self.valid_until

    @property
    def days_until_expiry(self) -> int | None:
        if self.valid_until is None:
            return None
        return max(0, (self.valid_until - timezone.now().date()).days)

    @classmethod
    def active_for_member(
        cls, member: Member, on_date: date
    ) -> models.QuerySet[Subscription]:
        """Subscriptions that BLOCK a membership / subscription cancellation on
        ``on_date``: admin-confirmed, not cancelled, and not yet ended
        (``valid_until`` IS NULL OR ``>= on_date``).

        The single definition shared by the two cancellation restraints (they
        were byte-identical). A future-dated confirmed subscription IS included
        — it is a live commitment the member can't walk away from — so this is
        deliberately BROADER than ``active_subscriptions_count``'s "active
        today" badge (which additionally requires ``valid_from <= today``).
        Callers add ``.exists()``.
        """
        return cls.objects.filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=on_date),
            member=member,
            admin_confirmed=True,
            cancelled_at__isnull=True,
        )


class MemberLoan(JasminModel, AdminConfirmableMixin, CreatedMixin):
    member = models.ForeignKey("Member", on_delete=models.PROTECT)
    amount = models.IntegerField()
    interest_rate = models.DecimalField(max_digits=4, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    cancelled_reason = models.TextField(blank=True, null=True)
    paid_back_date = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            # Date-order backstops for the bulk paths that bypass ``clean()``.
            # All NULL-tolerant: only enforced when both members of a pair are
            # set.
            nullable_date_order_constraint(
                "end_date",
                "start_date",
                name="memberloan_end_after_start",
            ),
            nullable_date_order_constraint(
                "paid_back_date",
                "start_date",
                name="memberloan_paid_back_after_start",
            ),
            # Reversed direction (``paid_back_date <= end_date``) — kept bespoke
            # so the stored constraint keeps its exact field/operator ordering
            # (rewriting it as ``end_date >= paid_back_date`` via the helper
            # would churn a migration for no schema change).
            models.CheckConstraint(
                condition=Q(paid_back_date__isnull=True)
                | Q(end_date__isnull=True)
                | Q(paid_back_date__lte=F("end_date")),
                name="memberloan_paid_back_before_end",
            ),
        ]

    def __str__(self) -> str:
        return f"Loan {self.amount} for {self.member}"

    def clean(self) -> None:
        super().clean()

        validate_nullable_date_order(
            self,
            "end_date",
            "start_date",
            message="End date must be after start date",
        )
        validate_nullable_date_order(
            self,
            "paid_back_date",
            "start_date",
            message="Paid back date cannot be before start date",
        )

        # A loan must not be marked paid back after its own end date.
        if (
            self.paid_back_date
            and self.end_date
            and self.paid_back_date > self.end_date
        ):
            raise ValidationError(
                {"paid_back_date": "Paid back date cannot be after end date"}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
