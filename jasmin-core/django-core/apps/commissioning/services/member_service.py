"""Service layer for the Member resource.

Centralises orchestration logic that was previously inlined in
`MemberViewSet`: JasminUser lookup/linking on create, status conflict
detection, admin confirm/reject with notification side-effects, and
invitation send/resend.

Email side-effects are best-effort and never block the primary action;
failures are logged and swallowed.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.accounts.models import JasminUser
from apps.shared.deferred_email import schedule_deferred_email

from ..errors import (
    MemberAlreadyCancelled,
    MemberAlreadyConfirmed,
    MemberHasNoEmail,
    MemberUserAlreadyActive,
    UserAlreadyLinked,
    UserInBlockedStatus,
)
from ..models import Member

logger = logging.getLogger(__name__)


# Account statuses that block linking a new Member to an existing user.
BLOCKED_LINK_STATUSES: frozenset[str] = frozenset({"pending_approval", "inactive"})


class MemberService:
    # --- JasminUser linking on create ------------------------------------

    @staticmethod
    def find_existing_user_for_email(email: str | None) -> JasminUser | None:
        if not email:
            return None
        return JasminUser.objects.filter(email__iexact=email).first()

    @staticmethod
    def assert_user_can_be_linked(user: JasminUser) -> None:
        """Validate that `user` may be linked to a new Member.

        Raises a ``MemberLinkConflict`` subclass for users who are
        mid-flow with another application or already linked to a
        member.
        """
        if user.account_status in BLOCKED_LINK_STATUSES:
            raise UserInBlockedStatus(
                f"A user with email {user.email} already exists in "
                f"status '{user.account_status}'."
            )
        if getattr(user, "member_profile", None):
            raise UserAlreadyLinked("This user is already linked to a member.")

    @transaction.atomic
    def link_to_user(
        self,
        member: Member,
        user: JasminUser,
        *,
        admin_user: JasminUser | None,
        notify_user: bool,
        request: Any | None = None,
    ) -> Member:
        """Link `member` to an existing `user` and apply status side-effects.

        For an `active` user: auto-confirms the Member and (when
        `notify_user` is true) sends a welcome email. For other statuses
        the link is set but no further action is taken.
        """
        member.user = user
        member.save(update_fields=["user"])

        if user.account_status == "active":
            member.confirm(admin_user=admin_user, save=True)
            if notify_user and member.email:
                # ``accounts.welcome_user`` is a USER-account event — the
                # template expects ``user.first_name`` + ``portal_url``,
                # NOT member.*. Pass the linked JasminUser explicitly so
                # this matches the ``accept_invitation`` call site, and
                # include the portal URL the body's "log in at …" line
                # depends on.
                from apps.shared.invitations import _frontend_base_url

                self._send_email(
                    member,
                    slug="accounts.welcome_user",
                    request=request,
                    extra_context={
                        "user": {"first_name": user.first_name},
                        "portal_url": _frontend_base_url(),
                    },
                    log_label="welcome",
                )
        return member

    # --- Confirm / reject ------------------------------------------------

    @transaction.atomic
    def confirm_and_notify(
        self,
        member: Member,
        *,
        admin_user: JasminUser,
        request: Any | None = None,
    ) -> Member:
        """Confirm `member` and best-effort notify the applicant by email.

        The email send is deferred to ``transaction.on_commit`` inside
        ``_send_email`` so a rollback elsewhere in the request cycle
        cannot leave the applicant with a confirmation email for a
        non-confirmed Member.
        """
        if member.admin_confirmed:
            raise MemberAlreadyConfirmed("Member is already confirmed")

        # Never admit a member who has initiated their exit (cancelled_at set).
        # Defense-in-depth for every confirm caller (the coop-share and
        # subscription confirm endpoints already block this upstream).
        if member.cancelled_at is not None:
            raise MemberAlreadyCancelled("Cannot confirm a cancelled member.")

        # GenG: a full member admitted into the Mitgliederliste must
        # hold an equity position inside the tenant's
        # ``min_number_coop_shares`` / ``max_number_coop_shares``
        # window. Block here BEFORE flipping ``admin_confirmed`` so the
        # office can't promote a non-trial member with zero (or
        # otherwise out-of-range) coop shares — the previous flow
        # silently allowed that because the existing CoopShare
        # validator only fires on CoopShare.save().
        # Trial members are exempt by design (re-checked at trial-
        # conversion time when they acquire their first share).
        from apps.commissioning.services.coop_share_service import (
            CoopShareService,
        )

        CoopShareService.assert_member_total_within_bounds(member)

        member.confirm(admin_user=admin_user, save=True)

        # Admitting the member admits their pending (self-subscribed) coop
        # shares in lock-step — the office reviews person + equity together.
        # Shares subscribed AFTER admission stay pending until confirmed
        # separately (CoopShareViewSet.confirm).
        CoopShareService.confirm_pending_for_member(member, admin_user=admin_user)

        if member.email:
            self._send_email(
                member,
                slug="accounts.application_approved",
                request=request,
                extra_context={
                    "applicant": {
                        "first_name": member.first_name,
                        "member_number": member.member_number,
                    }
                },
                log_label="confirm",
            )
        return member

    @transaction.atomic
    def reject_and_notify(
        self,
        member: Member,
        *,
        admin_user: JasminUser,
        reason: str | None,
        request: Any | None = None,
    ) -> Member:
        """Reject `member` (with optional reason) and best-effort notify.

        Side-effects executed in the same atomic block:
          1. ``Member.reject()`` stamps ``admin_rejected_at`` +
             ``admin_rejection_reason`` and clears any stale
             ``admin_confirmed_at``.
          2. ``_deactivate_linked_user`` flips the linked JasminUser
             (if any) to ``account_status='inactive'`` so a rejected
             applicant can no longer log into the portal AND any
             pending invitation link stops working. Same transaction
             as the reject stamp — a rolled-back rejection leaves the
             user account untouched.
          3. ``accounts.application_rejected`` email scheduled via
             on_commit (P1-3 policy).
        """
        # ``reject`` is for PENDING applications only. Un-flipping the confirm
        # flag on an ALREADY-CONFIRMED member would leave member_number,
        # entry_date, active CoopShares and the trial-conversion stamps in
        # place — a GenG registry row that reads as rejected but is still
        # materialised. Genuine offboarding of a confirmed member is a
        # separate flow; refuse the bare reject here.
        if member.admin_confirmed:
            raise MemberAlreadyConfirmed(
                "Confirmed members cannot be rejected — they must be "
                "offboarded instead."
            )

        member.reject(admin_user=admin_user, reason=reason, save=True)
        self._deactivate_linked_user(member, admin_user=admin_user)

        if member.email:
            self._send_email(
                member,
                slug="accounts.application_rejected",
                request=request,
                extra_context={
                    "applicant": {"first_name": member.first_name},
                    "reason": reason or "",
                },
                log_label="reject",
            )
        return member

    @staticmethod
    def _deactivate_linked_user(
        member: Member, *, admin_user: JasminUser | None
    ) -> None:
        """Flip the linked JasminUser (if any) to ``inactive`` and
        cancel any open invitations.

        Re-activation is intentionally NOT automatic if the office
        later un-rejects the Member — that would silently re-open
        portal access for a user who in the meantime might have lost
        their device, changed email, etc. Re-activation stays an
        explicit operator decision (re-send invitation or flip
        ``account_status`` manually).

        No-op when:
          * ``member.user`` is not set (member was never linked);
          * the user is already ``inactive`` (idempotent on repeat
            calls).
        """
        user = getattr(member, "user", None)
        if user is None:
            return
        if user.account_status == "inactive":
            return

        previous_status = user.account_status
        user.account_status = "inactive"
        # ``JasminUser.save()`` derives ``is_active`` from
        # ``account_status`` — explicitly setting it here keeps the
        # update_fields list honest and survives a later refactor
        # that changes the derivation.
        user.is_active = False
        user.save(update_fields=["account_status", "is_active"])

        # Cancel any still-open UserInvitation rows so a stolen
        # accept-link can't be used after rejection. Lazy import:
        # UserInvitation lives in the commissioning app, but the
        # cleanup is a small, focused query that doesn't justify
        # a cross-service call.
        from apps.commissioning.models import UserInvitation

        UserInvitation.objects.filter(user=user, status="sent").update(
            status="cancelled"
        )

        logger.info(
            "member.reject_deactivated_user member=%s user=%s "
            "previous_status=%s by=%s",
            member.id,
            user.id,
            previous_status,
            getattr(admin_user, "id", None),
        )

    # --- Invitations -----------------------------------------------------

    def send_invitation(
        self,
        member: Member,
        *,
        admin_user: JasminUser,
    ) -> Member:
        """Send (or resend) a JasminUser invitation for `member`.

        Raises:
            MemberHasNoEmail: member has no email address on file.
            MemberUserAlreadyActive: member already has a non-pending user.
        """
        # Local imports avoid the costly authz/invitations import at
        # module load time.
        from apps.authz.roles import Role
        from apps.shared.invitations import (
            create_user_with_invitation,
            resend_invitation,
        )

        if not member.email:
            raise MemberHasNoEmail("Member has no email address.")

        if member.user_id:
            # ``pending_invitation`` → resend. ``inactive`` → re-provision: a
            # member rejected via reject_and_notify has their linked user
            # deactivated, and that helper's docstring names "re-send
            # invitation" as the sanctioned operator re-activation path.
            # ``resend_invitation`` cancels any open invite, mints a fresh one,
            # flips the user back to ``pending_invitation``, and emails it — so
            # the office can re-invite a previously-rejected member without a
            # manual DB edit. Only a genuinely active (or pending-approval)
            # account is a real conflict.
            if member.user.account_status in {"pending_invitation", "inactive"}:
                resend_invitation(user=member.user, created_by=admin_user)
                return member
            raise MemberUserAlreadyActive("Member already has an active user account.")

        user, _invitation = create_user_with_invitation(
            email=member.email,
            first_name=member.first_name or "",
            last_name=member.last_name or "",
            roles=[Role.MEMBER],
            user_language=getattr(member, "preferred_language", None),
            member=member,
            created_by=admin_user,
        )
        member.user = user
        member.save(update_fields=["user"])
        return member

    # --- Internal helpers -----------------------------------------------

    @staticmethod
    def _send_email(
        member: Member,
        *,
        slug: str,
        request: Any | None,
        extra_context: dict[str, Any] | None = None,
        log_label: str,
    ) -> None:
        """Best-effort email send, deferred until the surrounding
        transaction commits.

        The actual ``EmailService.send_email`` call is scheduled via
        ``transaction.on_commit``. If the caller's atomic block rolls
        back, the email never fires — so we never email an applicant
        about a state change that did not in fact persist (P1-3).

        When called *outside* an atomic block, Django runs the callback
        immediately, so non-transactional callers (e.g. plain shell
        scripts) keep the previous fire-and-forget semantics.
        """
        tenant = getattr(request, "tenant", None) if request is not None else None
        # Flatten to plain scalars — never hand a live ORM instance to the
        # tenant-editable email renderer (see template_renderer._resolve).
        # These are the only ``member.*`` fields the member-lifecycle
        # templates (welcome / approved / rejected) reference.
        context: dict[str, Any] = {
            "tenant_name": getattr(tenant, "name", "") or "",
            "member": {
                "first_name": member.first_name,
                "member_number": member.member_number,
                "admin_rejection_reason": member.admin_rejection_reason or "",
            },
        }
        if extra_context:
            context.update(extra_context)

        member_id = member.id
        # EML-9: render in the recipient's stored language when known. Captured
        # as a plain scalar BEFORE the on_commit closure; None falls back to the
        # tenant language (existing behaviour) inside send_email.
        member_lang = (
            getattr(getattr(member, "user", None), "user_language", None) or None
        )

        schedule_deferred_email(
            slug=slug,
            to_emails=[member.email],
            context=context,
            related_object_type="member",
            related_object_id=str(member_id),
            language=member_lang,
            logger=logger,
            log_error_event=f"member.{log_label}_email_crashed",
            log_not_sent_event=f"member.{log_label}_email_not_sent",
            log_ref=f"member={member_id}",
        )
