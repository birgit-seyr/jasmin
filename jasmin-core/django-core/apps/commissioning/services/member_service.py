"""Service layer for the Member resource.

Orchestration logic for `MemberViewSet`: JasminUser lookup/linking on
create, status conflict
detection, admin confirm/reject with notification side-effects, and
invitation send/resend.

Email side-effects are best-effort and never block the primary action;
failures are logged and swallowed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.authz.roles import STAFF_ROLES, Role

from ..errors import (
    MemberAlreadyCancelled,
    MemberAlreadyConfirmed,
    MemberAlreadyRejected,
    MemberCoopSharesOutOfRange,
    MemberEmailAlreadyHasUser,
    MemberEmailHeldByNonMemberLogin,
    MemberHasNoEmail,
    MemberUserAlreadyActive,
    UserAlreadyLinked,
    UserInBlockedStatus,
)
from ..models import Member, Subscription, UserInvitation
from ..models.choices import InvitationStatus
from .member_email import schedule_member_email
from .waiting_list_offer_service import (
    release_rejected_subscription,
    withdraw_from_waiting_list,
)

if TYPE_CHECKING:
    # Type-only: the concrete user model keeps mypy precise, while the runtime
    # path goes through ``get_user_model()`` so this module works under a host
    # project whose ``AUTH_USER_MODEL`` is something else.
    from apps.accounts.models import JasminUser

logger = logging.getLogger(__name__)


# Account statuses that block linking a new Member to an existing user.
BLOCKED_LINK_STATUSES: frozenset[str] = frozenset({"pending_approval", "inactive"})


class MemberService:
    # --- JasminUser linking on create ------------------------------------

    @staticmethod
    def find_existing_user_for_email(email: str | None) -> JasminUser | None:
        if not email:
            return None
        return get_user_model().objects.filter(email__iexact=email).first()

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
        confirm_active_user: bool = True,
    ) -> Member:
        """Link `member` to an existing `user` and apply status side-effects.

        For an `active` user: confirms the Member and (when `notify_user` is
        true) sends a welcome email — when the Member can be admitted already.
        A non-trial member whose coop shares don't fit the tenant's window yet
        (a new one holds none) stays linked and pending; the office confirms
        it once its shares are in. For other statuses the link is set but no
        further action is taken.

        ``confirm_active_user=False`` (onboarding mode) only links: the office
        confirms the member later with its historical date.
        """
        member.user = user
        member.save(update_fields=["user"])

        if confirm_active_user and user.account_status == "active":
            try:
                with transaction.atomic():
                    member.confirm(admin_user=admin_user, save=True)
            except MemberCoopSharesOutOfRange:
                return member
            if notify_user and member.email:
                # ``accounts.welcome_user`` is a USER-account event — the
                # template expects ``user.first_name`` + ``portal_url``,
                # NOT member.*. Pass the linked JasminUser explicitly so
                # this matches the ``accept_invitation`` call site, and
                # include the portal URL the body's "log in at …" line
                # depends on.
                from apps.shared.tenant_urls import frontend_base_url

                self._send_email(
                    member,
                    slug="accounts.welcome_user",
                    request=request,
                    extra_context={
                        "user": {"first_name": user.first_name},
                        "portal_url": frontend_base_url(),
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
        confirmed_at: datetime | None = None,
        notify: bool = True,
        allow_cancelled: bool = False,
    ) -> Member:
        """Confirm `member` and best-effort notify the applicant by email.

        The email send is deferred to ``transaction.on_commit`` inside
        ``_send_email`` so a rollback elsewhere in the request cycle
        cannot leave the applicant with a confirmation email for a
        non-confirmed Member.

        Onboarding mode passes the other three arguments:

        * ``confirmed_at`` dates the confirmation, the entry date and the
          confirmation of the member's pending coop shares.
        * ``notify=False`` sends neither ``accounts.application_approved`` nor
          ``commissioning.trial_converted``.
        * ``allow_cancelled=True`` admits a member who has already left (admit
          and exit): the member is confirmed on a day no later than the exit
          date, then every open coop share is cancelled with the member's
          existing exit stamps and the normal payback due date. The member row
          keeps its cancellation and no cancellation email is sent.
        """
        # Decide on the member row as it is now, locked: a reject committed
        # since the caller read it (a stale tab, a confirm waiting on the
        # reject's lock) would otherwise be undone. Refreshed in place, so the
        # caller's instance is current too.
        member.refresh_from_db(from_queryset=Member.objects.select_for_update())
        if member.admin_confirmed:
            raise MemberAlreadyConfirmed("Member is already confirmed")
        if member.admin_rejected_at is not None:
            raise MemberAlreadyRejected(
                "The member was rejected; a new invitation re-admits them."
            )

        # Never admit a member who has initiated their exit (cancelled_at set).
        # Defense-in-depth for every confirm caller (the coop-share and
        # subscription confirm endpoints already block this upstream).
        if member.cancelled_at is not None:
            if not allow_cancelled:
                raise MemberAlreadyCancelled("Cannot confirm a cancelled member.")
            from .onboarding_policy import assert_confirmation_not_after_exit

            assert_confirmation_not_after_exit(member, confirmed_at=confirmed_at)

        # GenG: a full member admitted into the Mitgliederliste must
        # hold an equity position inside the tenant's
        # ``min_number_coop_shares`` / ``max_number_coop_shares``
        # window. Block here BEFORE flipping ``admin_confirmed`` so the
        # office can't promote a non-trial member with zero (or
        # otherwise out-of-range) coop shares — the CoopShare validator
        # only fires on CoopShare.save(), so it doesn't cover this.
        # Trial members are exempt by design (re-checked at trial-
        # conversion time when they acquire their first share).
        from apps.commissioning.services.coop_share_service import (
            CoopShareService,
        )

        CoopShareService.assert_member_total_within_bounds(member)

        member.confirm(admin_user=admin_user, save=True, confirmed_at=confirmed_at)

        # Admitting the member admits their pending (self-subscribed) coop
        # shares in lock-step — the office reviews person + equity together.
        # Shares subscribed AFTER admission stay pending until confirmed
        # separately (CoopShareViewSet.confirm).
        CoopShareService.confirm_pending_for_member(
            member, admin_user=admin_user, confirmed_at=confirmed_at, notify=notify
        )

        if member.cancelled_at is not None:
            # Admit and exit: the membership ended before it was recorded, so
            # the equity confirmed just now is already on its way back.
            from .member_cancellation import cancel_coop_shares_of_departed_member

            cancel_coop_shares_of_departed_member(member)

        if notify and member.email:
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
          1. ``_reject_open_subscriptions`` rejects the member's open
             subscriptions along with the member and frees what they hold:
             station-day reservations, waiting-list places and open offers,
             and the variation slot an accepted offer holds. It runs before
             the member row is locked and written: a subscription confirm
             locks its subscription and then writes the member, so both take
             the locks in the same order.
          2. ``Member.reject()`` stamps ``admin_rejected_at`` +
             ``admin_rejection_reason`` and clears any stale
             ``admin_confirmed_at``, on the member row re-read under its lock;
             a member confirmed in the meantime is refused instead.
          3. ``accounts.application_rejected`` email scheduled via
             on_commit. It renders in the language of the login linked to
             the member, so it is scheduled before step 4 can unlink it.
          4. ``_deactivate_linked_user`` ends the linked login's (if any)
             access as this member: a member's portal login is flipped to
             ``account_status='inactive'`` so a rejected applicant can no
             longer log into the portal AND any pending invitation link
             stops working; a login with a staff or customer role keeps
             that access and is unlinked from the member instead. Same
             transaction as the reject stamp — a rolled-back rejection
             leaves the user account untouched.
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

        self._reject_open_subscriptions(member, admin_user=admin_user, reason=reason)
        # Decide on the member row under the lock ``confirm`` takes, after the
        # subscriptions' locks above. A member confirm committed since the
        # caller read the row would otherwise be undone: its member number and
        # entry date reset, the login it activated deactivated again, and a
        # rejection mail sent after the approval mail. The refusal rolls the
        # subscriptions' rejection back with it.
        member = Member.objects.select_for_update().get(pk=member.pk)
        if member.admin_confirmed:
            raise MemberAlreadyConfirmed(
                "Confirmed members cannot be rejected — they must be "
                "offboarded instead."
            )
        member.reject(admin_user=admin_user, reason=reason, save=True)

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
        self._deactivate_linked_user(member, admin_user=admin_user)
        return member

    @staticmethod
    def _reject_open_subscriptions(
        member: Member, *, admin_user: JasminUser, reason: str | None
    ) -> None:
        """Reject the open subscriptions of `member`, whom the office is
        rejecting, and free what they hold.

        A subscription that is neither confirmed, rejected nor cancelled is
        part of the rejected application: it gets the member's rejection stamp
        and reason, so the office finds it decided rather than pending, and
        ``release_rejected_subscription`` frees its station-day reservation,
        its waiting-list place and any open offer. The stamp ends the variation
        slot an accepted offer holds. A subscription already cancelled or
        rejected keeps its stamps; one still on the waiting list leaves it.

        The stamps are written with ``update()``, like the waiting-list
        withdrawal's: a rejection must not fail on a term that the
        subscription's own validation has come to refuse.
        """
        open_subscriptions = list(
            Subscription.objects.filter(
                member_id=member.pk,
                admin_confirmed=False,
                admin_rejected_at__isnull=True,
                cancelled_at__isnull=True,
            )
            .select_for_update()
            .order_by("pk")
        )
        if open_subscriptions:
            # The stamps ``AdminConfirmableMixin.reject`` writes;
            # ``admin_confirmed`` is False already.
            Subscription.objects.filter(
                pk__in=[subscription.pk for subscription in open_subscriptions]
            ).update(
                admin_confirmed_by=admin_user,
                admin_confirmed_at=None,
                admin_rejected_at=timezone.now(),
                admin_rejection_reason=reason,
            )
        for subscription in open_subscriptions:
            release_rejected_subscription(subscription)
        withdraw_from_waiting_list(Subscription.objects.filter(member_id=member.pk))

    @staticmethod
    def _deactivate_linked_user(member: Member, *, admin_user: JasminUser) -> None:
        """Flip the linked JasminUser (if any) to ``inactive`` and
        cancel any open invitations — when the login is there for the
        membership alone.

        A login with a staff or customer role keeps those roles and its
        account status: it is unlinked from the rejected member instead and
        loses only the member role (``_unlink_login_with_other_roles``). The
        member create and the CSV import link any login whose email matches,
        an admin's included, and rejecting is an office action; deactivating
        such a login is an admin's decision, made with step-up on the
        admin-users endpoints, where the last active admin can't be
        deactivated.

        Re-activation is intentionally NOT automatic if the office
        later un-rejects the Member — that would silently re-open
        portal access for a user who in the meantime might have lost
        their device, changed email, etc. Re-activation stays an
        explicit operator decision (re-send invitation or flip
        ``account_status`` manually).

        No-op when:
          * ``member.user`` is not set (member was never linked);
          * a login without a staff or customer role is already
            ``inactive`` (idempotent on repeat calls).
        """
        user = member.user
        if user is None:
            return
        if user.has_any_role(STAFF_ROLES | {Role.CUSTOMER}):
            MemberService._unlink_login_with_other_roles(
                member, user, admin_user=admin_user
            )
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
        # accept-link can't be used after rejection.
        UserInvitation.objects.filter(user=user, status=InvitationStatus.SENT).update(
            status=InvitationStatus.CANCELLED
        )

        logger.info(
            "member.reject_deactivated_user member=%s user=%s "
            "previous_status=%s by=%s",
            member.id,
            user.id,
            previous_status,
            admin_user.id,
        )

    @staticmethod
    def _unlink_login_with_other_roles(
        member: Member, user: JasminUser, *, admin_user: JasminUser
    ) -> None:
        """Detach a login with a staff or customer role from the rejected
        `member`, leaving its account status and its other roles as they are.

        Saving the member without the login makes ``Member.save`` retract the
        member role (``retract_member_role``), since no member links the
        login any more. An invitation sent for this membership is cancelled:
        accepting it would confirm the rejected member. The login's other
        open invitations stay usable.
        """
        kept_roles = sorted(set(user.roles or []) - {Role.MEMBER})
        member.user = None
        member.save(update_fields=["user"])

        UserInvitation.objects.filter(
            user=user, member=member, status=InvitationStatus.SENT
        ).update(status=InvitationStatus.CANCELLED)

        logger.info(
            "member.reject_unlinked_user member=%s user=%s kept_roles=%s by=%s",
            member.id,
            user.id,
            kept_roles,
            admin_user.id,
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
        # Local imports avoid the costly invitations import at module load
        # time.
        from apps.shared.invitations import (
            create_user_with_invitation,
            resend_invitation,
        )
        from apps.shared.tenants.onboarding_emails import EmailCategory

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
                resend_invitation(
                    user=member.user,
                    created_by=admin_user,
                    email_category=EmailCategory.MEMBER_LIFECYCLE,
                    member=member,
                )
                return member
            raise MemberUserAlreadyActive("Member already has an active user account.")

        # ``Member.email`` is not unique (shared inboxes are legitimate) but
        # ``JasminUser.email`` IS — it is the USERNAME_FIELD. So a second member
        # on the same address cannot get their own login. Detect that here and
        # name the holder, instead of letting the shared invitation helper reuse
        # the other member's account: for a ``pending_invitation`` / ``inactive``
        # user it would roll THIS member's name onto THAT user, reset its status
        # and cancel its open invite before finally tripping the
        # ``Member.user`` OneToOne constraint.
        conflicting_user = self.find_existing_user_for_email(member.email)
        if conflicting_user is not None:
            holder = getattr(conflicting_user, "member_profile", None)
            if holder is not None and holder.pk != member.pk:
                raise MemberEmailAlreadyHasUser(email=member.email, holder=holder)
            # ``member.user_id`` is None on this branch, so no member profile
            # at all means the address belongs to a NON-member login — a staff
            # account, or one still mid-invitation. That is not an account to
            # invite into: ``create_user_with_invitation`` reuses ``inactive``
            # and ``pending_invitation`` rows, so it would roll this member's
            # name onto that row, replace its roles with [member], and link it
            # here — handing the primary key, and every ``created_by``
            # reference pointing at it, to whoever accepts the invite. The
            # account would also come back to life without the explicit
            # operator decision ``_deactivate_linked_user`` requires.
            # Attaching an existing login to a member is a separate operation
            # (``link_to_user`` → ``assert_user_can_be_linked``).
            if holder is None:
                raise MemberEmailHeldByNonMemberLogin(
                    "This email address already has a login without a member "
                    "profile."
                )

        user, _invitation = create_user_with_invitation(
            email=member.email,
            first_name=member.first_name or "",
            last_name=member.last_name or "",
            roles=[Role.MEMBER],
            member=member,
            created_by=admin_user,
            email_category=EmailCategory.MEMBER_LIFECYCLE,
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
        about a state change that did not in fact persist.

        When called *outside* an atomic block, Django runs the callback
        immediately, so non-transactional callers (e.g. plain shell
        scripts) get fire-and-forget semantics.
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

        schedule_member_email(
            member,
            slug=slug,
            context=context,
            logger=logger,
            log_error_event=f"member.{log_label}_email_crashed",
            log_not_sent_event=f"member.{log_label}_email_not_sent",
        )
