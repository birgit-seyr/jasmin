"""Two-step deletion-request workflow (request → confirm → approve/reject)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import JasminUser

from ..errors import (
    DeletionRequestNotPending,
    DeletionTokenExpired,
    DeletionTokenInvalid,
    RetentionPeriodActive,
)
from ..models import DeletionRequest, DeletionRequestState
from .deletion_emails import send_deletion_pending_admin_office_email

if TYPE_CHECKING:
    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there. Method bodies must resolve it at call
    # time through the ASSEMBLED class so monkeypatched attributes on
    # ``GDPRService`` are honoured.
    from . import GDPRService

logger = logging.getLogger("gdpr")


class DeletionWorkflowMixin:
    """Deletion-request state machine, mixed into
    :class:`apps.gdpr.services.GDPRService`."""

    # ---------------------------------------------------------------
    # Two-step deletion flow
    # ---------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def request_deletion(
        user: JasminUser, *, requested_ip: str | None = None
    ) -> DeletionRequest:
        """Step 1 of the two-step flow: create a ``PENDING_EMAIL``
        request. The request ALWAYS lodges — open retention
        obligations never block this step (see Note below).

        Supersedes any earlier still-open request for the same user
        (state flipped to ``CANCELLED``) so a fresh token always wins.
        The caller is responsible for dispatching the confirmation
        email — kept as a separate step so test code can call
        ``request_deletion`` without a working SMTP config.

        Returns the newly-created request. The token lives on
        ``request.token`` and is what goes into the email link.

        Note: retention obligations are NOT checked here — the request
        always lodges. The check runs at admin-approve time
        (``_execute_deletion``), which is the actual execution gate.
        Letting the request through means the admin sees it in their
        inbox alongside its blockers and can resolve them (cancel
        CoopShares, settle invoices, …) at which point Approve becomes
        actionable. Matches GDPR Art. 17(3): the right isn't suspended
        by retention, only its execution is deferred.
        """
        # Cancel any previously-open request for this user so the
        # database has exactly one "live" request per subject. The
        # superseded rows stay (audit trail of "user asked twice").
        DeletionRequest.objects.filter(
            user=user,
            state__in=(
                DeletionRequestState.PENDING_EMAIL,
                DeletionRequestState.PENDING_ADMIN,
                DeletionRequestState.APPROVED,
            ),
        ).update(
            state=DeletionRequestState.CANCELLED,
            superseded_at=timezone.now(),
        )

        # Admin approval is mandatory for every deletion request —
        # no per-tenant / per-persona opt-out. The field stays True
        # for new rows; historical rows preserve whatever they were
        # created with.
        deletion_request = DeletionRequest.objects.create(
            user=user,
            requested_email=user.email,
            requires_admin_approval=True,
            state=DeletionRequestState.PENDING_EMAIL,
            requested_ip=requested_ip,
        )

        logger.info(
            "gdpr.deletion_requested user=%s request_id=%s",
            user.email,
            deletion_request.pk,
        )
        return deletion_request

    @staticmethod
    def confirm_deletion_token(token: str, *, ip: str | None = None) -> DeletionRequest:
        """Step 2: the user clicks the link in the confirmation email.

        Transitions the request from ``PENDING_EMAIL`` → ``PENDING_ADMIN``.
        Admin approval is mandatory for every deletion; nothing
        executes here.

        Raises:
            DeletionTokenInvalid: unknown token, OR the matching
                request isn't in ``PENDING_EMAIL`` any more
                (already confirmed / cancelled / superseded).
            DeletionTokenExpired: token matched but the 24h window
                lapsed — user must request again.

        The expiry-mark write happens OUTSIDE the consume-atomic so
        the ``state=EXPIRED`` save commits even though we immediately
        raise. Same trick for the "wrong state" path — those are
        single-write transitions, no atomicity needed.
        """
        # Step 0 — lookup. ``ValidationError`` covers Django 5.x's
        # "not a valid UUID" path; ``ValueError`` covers older Django
        # / non-Postgres backends; ``DoesNotExist`` is the normal
        # unknown-token miss. All three become the same 404 so an
        # attacker can't probe for valid token shapes.
        from django.core.exceptions import ValidationError

        try:
            deletion_request = DeletionRequest.objects.get(token=token)
        except (
            DeletionRequest.DoesNotExist,
            ValueError,
            ValidationError,
        ):
            raise DeletionTokenInvalid(
                "Unknown or already-used deletion token."
            ) from None

        if deletion_request.state != DeletionRequestState.PENDING_EMAIL:
            # Token is real but the request moved on (cancelled,
            # superseded, already executed). Same 404 — see
            # ``DeletionTokenInvalid`` docstring.
            raise DeletionTokenInvalid(
                f"This deletion link is no longer valid "
                f"(state: {deletion_request.state})."
            )

        if deletion_request.is_token_expired:
            # Single-row mark so the audit trail records WHY this
            # request never went through. Use ``QuerySet.update`` —
            # runs in its own auto-commit transaction so the state
            # change survives the ``raise`` that follows. A naive
            # ``instance.save() + raise`` inside an atomic block
            # would roll back; ``.update()`` doesn't enroll in the
            # outer transaction (it issues SQL directly).
            DeletionRequest.objects.filter(pk=deletion_request.pk).update(
                state=DeletionRequestState.EXPIRED
            )
            raise DeletionTokenExpired(
                "The confirmation link has expired. " "Please request deletion again."
            )

        # Step 1 — consume the token + (optionally) execute. This is
        # the only path that needs the row-lock + transaction wrapper.
        return GDPRService._consume_pending_email_request(deletion_request.pk, ip=ip)

    @staticmethod
    @transaction.atomic
    def _consume_pending_email_request(
        deletion_request_pk: str, *, ip: str | None
    ) -> DeletionRequest:
        """Inside-the-lock branch of :meth:`confirm_deletion_token`.

        Re-fetches the row with ``select_for_update`` so two
        simultaneous confirms (user double-clicks the email link)
        serialise. The race-guard re-check is necessary: another
        worker may have flipped the state or expired the token
        between our outside-atomic checks and this lock acquisition.
        """
        deletion_request = DeletionRequest.objects.select_for_update().get(
            pk=deletion_request_pk
        )

        if deletion_request.state != DeletionRequestState.PENDING_EMAIL:
            raise DeletionTokenInvalid(
                f"This deletion link is no longer valid "
                f"(state: {deletion_request.state})."
            )

        now = timezone.now()
        deletion_request.email_confirmed_at = now
        deletion_request.email_confirmed_ip = ip
        # Admin approval is mandatory — every confirmed request lands
        # in PENDING_ADMIN and waits for an office decision.
        deletion_request.state = DeletionRequestState.PENDING_ADMIN
        deletion_request.save(
            update_fields=["email_confirmed_at", "email_confirmed_ip", "state"]
        )
        logger.info(
            "gdpr.deletion_email_confirmed request_id=%s " "next=pending_admin user=%s",
            deletion_request.pk,
            deletion_request.requested_email,
        )

        # Push notification to the office mailbox so a pending request
        # doesn't sit unnoticed for days. Deferred via ``on_commit`` so
        # the email never goes out for a transition that gets rolled
        # back. Best-effort: the helper logs but doesn't raise; admin
        # workflow falls back to the ConfigurationGDPR inbox card.
        # See ``send_deletion_pending_admin_office_email`` for the
        # "deliberately minimal payload" rationale (no PII).
        transaction.on_commit(
            lambda: send_deletion_pending_admin_office_email(deletion_request)
        )
        return deletion_request

    @staticmethod
    @transaction.atomic
    def admin_approve_deletion(
        deletion_request: DeletionRequest,
        *,
        admin_user: JasminUser,
    ) -> DeletionRequest:
        """Step 3 (only when the admin gate is on): an office/admin
        approves the request, which then immediately executes.

        Uses :meth:`AdminConfirmableMixin.confirm` to stamp the
        ``admin_confirmed`` / ``admin_confirmed_by`` /
        ``admin_confirmed_at`` audit fields, then transitions the
        state machine and runs anonymization.

        Raises :class:`DeletionRequestNotPending` if the request
        isn't currently in ``PENDING_ADMIN`` (already executed,
        rejected, or still awaiting email confirmation).

        Re-fetches the row under ``select_for_update()`` so two
        admins clicking Approve at the same time serialise — the
        second one's state check sees ``APPROVED`` / ``EXECUTED``
        and raises ``DeletionRequestNotPending`` instead of running
        anonymisation twice.
        """
        deletion_request = DeletionRequest.objects.select_for_update().get(
            pk=deletion_request.pk
        )
        if deletion_request.state != DeletionRequestState.PENDING_ADMIN:
            raise DeletionRequestNotPending(str(deletion_request.state))

        # Mixin's confirm() sets admin_confirmed=True, stamps _by/_at,
        # clears any prior rejection reason, and saves. The mixin's
        # ``_post_confirm`` hook would also fire here — we don't
        # override it because the state transition + execute logic
        # depends on ``GDPRService._execute_deletion``, which would
        # create a model→service import cycle if invoked from the
        # mixin hook. Keeping the orchestration in the service.
        deletion_request.confirm(admin_user=admin_user)
        deletion_request.state = DeletionRequestState.APPROVED
        deletion_request.save(update_fields=["state"])
        return GDPRService._execute_deletion(deletion_request)

    @staticmethod
    @transaction.atomic
    def admin_reject_deletion(
        deletion_request: DeletionRequest,
        *,
        admin_user: JasminUser,
        reason: str,
    ) -> DeletionRequest:
        """Admin denies the request (e.g. they spotted a retention
        obligation the automated check missed, or the user phoned to
        cancel). Transitions to a terminal ``REJECTED`` state;
        ``anonymize_user`` is NOT called.

        Uses :meth:`AdminConfirmableMixin.reject` to stamp
        ``admin_confirmed_by`` + ``admin_rejection_reason``, then
        moves the state machine to ``REJECTED``.

        Raises :class:`DeletionRequestNotPending` if the request
        isn't in ``PENDING_ADMIN``. Re-fetches under
        ``select_for_update()`` to serialise concurrent
        Reject-clicks against the same row."""
        deletion_request = DeletionRequest.objects.select_for_update().get(
            pk=deletion_request.pk
        )
        if deletion_request.state != DeletionRequestState.PENDING_ADMIN:
            raise DeletionRequestNotPending(str(deletion_request.state))

        deletion_request.reject(admin_user=admin_user, reason=reason)

        deletion_request.admin_confirmed_at = timezone.now()
        deletion_request.state = DeletionRequestState.REJECTED
        deletion_request.save(update_fields=["admin_confirmed_at", "state"])
        logger.warning(
            "gdpr.deletion_rejected request_id=%s by=%s reason=%s",
            deletion_request.pk,
            admin_user.email,
            reason,
        )
        return deletion_request

    @staticmethod
    def _execute_deletion(deletion_request: DeletionRequest) -> DeletionRequest:
        """Run the anonymization and stamp the request as executed.
        Called from both ``confirm_deletion_token`` (no-admin path)
        and ``admin_approve_deletion`` — keeps the bookkeeping in
        one place.

        Re-checks retention obligations: the original
        ``request_deletion`` checked, but the request may have sat
        in ``PENDING_ADMIN`` for hours / days during which the
        member could have re-opened a subscription, etc. Better to
        refuse late than to violate Art. 17(3)(b).
        """
        # DeletionRequest.user is SET_NULL (NOT cascade) — this row IS the
        # Art. 17 erasure audit trail and must outlive its subject. Guard the
        # NULL-user case (defensive; anonymisation is in-place today so no path
        # produces it) so we fail loudly instead of crashing in anonymize_user
        # or silently mis-answering retention against a NULL FK.
        user = deletion_request.user
        if user is None:
            raise DeletionRequestNotPending(
                "This deletion request has no linked user and cannot be executed."
            )

        # Late retention re-check — see docstring above.
        reasons = GDPRService.check_retention_blocks(user)
        if reasons:
            raise RetentionPeriodActive(reasons)

        deletion_log = GDPRService.anonymize_user(user)
        deletion_request.executed_at = timezone.now()
        deletion_request.deletion_log = deletion_log
        deletion_request.state = DeletionRequestState.EXECUTED
        deletion_request.save(update_fields=["executed_at", "deletion_log", "state"])
        logger.warning(
            "gdpr.deletion_executed request_id=%s user_email=%s",
            deletion_request.pk,
            deletion_request.requested_email,
        )
        return deletion_request
