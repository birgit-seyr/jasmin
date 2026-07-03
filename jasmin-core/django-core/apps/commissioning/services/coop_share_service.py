from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import connection
from django.db.models import Sum

from ..errors import MemberCoopSharesOutOfRange

if TYPE_CHECKING:
    from apps.commissioning.models import Member


class CoopShareService:
    """Business logic for ``CoopShare`` that needs to be reusable by both
    ``CoopShare.clean()`` and any path that ``clean()`` cannot guard.
    """

    @staticmethod
    def member_total_shares(
        member: Member, *, exclude_pk=None, only_confirmed: bool = False
    ) -> Decimal:
        from apps.commissioning.models import CoopShare

        # Cancelled (divested) shares are no longer live equity — exclude them
        # so they don't count toward the GenG min/max coop-share window.
        qs = CoopShare.objects.filter(member=member, cancelled_at__isnull=True)
        # ``only_confirmed``: a self-subscribed PENDING share is not live equity
        # until the office confirms it (mirrors the my_data self-subscribe
        # docstring + the GenG §30 register export). The min/max admission bounds
        # count confirmed equity ONLY, so a member can't be admitted on pending
        # shares that are later rejected/deleted (BIZ-3).
        if only_confirmed:
            qs = qs.filter(admin_confirmed=True)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        return qs.aggregate(total=Sum("amount_of_coop_shares"))["total"] or Decimal(0)

    @staticmethod
    def confirm_pending_for_member(member: Member, *, admin_user) -> int:
        """Confirm all of ``member``'s pending (unconfirmed, non-cancelled) coop
        shares and return how many were confirmed.

        Used when a member is admitted: confirming the member admits their
        self-subscribed shares in lock-step (the office reviews equity + person
        together). New shares a member subscribes AFTER admission stay pending
        until confirmed separately. The shares are already part of the member's
        live total (which was bounds-checked at member confirmation), so no
        re-validation is needed here.
        """
        from django.db import transaction
        from django.utils import timezone

        from apps.commissioning.models import CoopShare
        from apps.commissioning.services.trial_conversion import (
            convert_trial_member_on_first_coop_share,
        )

        pending = list(
            CoopShare.objects.filter(
                member=member, admin_confirmed=False, cancelled_at__isnull=True
            )
        )
        if not pending:
            return 0

        # One bulk write for the whole set instead of a per-share save() (these
        # are one member's pending shares — confirmed together at admission), plus
        # the trial→full conversion run EXACTLY ONCE (it is member-scoped and
        # idempotent, so per-share calls were redundant). Mirrors the fields
        # AdminConfirmableMixin.confirm stamps; CoopShare is NOT a
        # FinalizedProtected model, so the bulk .update() is safe (no trigger).
        # No re-validation needed — equity was bounds-checked at member confirm.
        with transaction.atomic():
            CoopShare.objects.filter(pk__in=[share.pk for share in pending]).update(
                admin_confirmed=True,
                admin_confirmed_by=admin_user,
                admin_confirmed_at=timezone.now(),
                admin_rejection_reason=None,
            )
            convert_trial_member_on_first_coop_share(member)
        return len(pending)

    @staticmethod
    def _bounds_apply_to(member: Member) -> bool:
        """The min/max-coop-shares rule is GenG-scoped: it constrains
        members who have been admitted into the Mitgliederliste as full
        members. Trial members (still on probation) and pending /
        rejected applicants (not yet in the Mitgliederliste) are
        exempt — the office must be able to build up their coop-share
        position incrementally without each interim save tripping a
        bound.

        Mirror this check on every entry-point that calls
        ``assert_within_min_max``.
        """
        return bool(getattr(member, "admin_confirmed", False)) and not bool(
            getattr(member, "is_trial", False)
        )

    @staticmethod
    def assert_within_min_max(
        *,
        member: Member | None,
        new_amount: Decimal | None,
        exclude_pk=None,
    ) -> None:
        """Raise ``MemberCoopSharesOutOfRange`` if the resulting total would be
        outside the tenant-configured min/max coop-share window.

        Safe to call from bulk paths: caller must pass the would-be values.

        Skips the check entirely for trial members and not-yet-confirmed
        applicants — see :meth:`_bounds_apply_to`.
        """
        if new_amount is None or member is None:
            return
        if not CoopShareService._bounds_apply_to(member):
            return

        from apps.shared.tenants.models import TenantSettings

        tenant = connection.tenant
        current_settings = TenantSettings.get_current_settings(tenant)
        if not current_settings:
            return

        min_coop_shares = current_settings.min_number_coop_shares
        max_coop_shares = current_settings.max_number_coop_shares

        current_total = CoopShareService.member_total_shares(
            member, exclude_pk=exclude_pk
        )
        new_total = current_total + (new_amount or 0)

        if min_coop_shares is not None and new_total < min_coop_shares:
            raise MemberCoopSharesOutOfRange(
                total=new_total,
                minimum=min_coop_shares,
                maximum=max_coop_shares,
                member_id=str(member.pk),
            )
        if max_coop_shares is not None and new_total > max_coop_shares:
            raise MemberCoopSharesOutOfRange(
                total=new_total,
                minimum=min_coop_shares,
                maximum=max_coop_shares,
                member_id=str(member.pk),
            )

    @staticmethod
    def assert_member_total_within_bounds(
        member: Member, *, only_confirmed: bool = False
    ) -> None:
        """Confirm-time variant: assert ``member``'s CURRENT total coop
        shares satisfies the tenant min/max window.

        Used by :meth:`apps.commissioning.services.MemberService
        .confirm_and_notify` immediately before flipping
        ``admin_confirmed=True`` on a non-trial member, so the office
        cannot promote someone with the wrong equity. Trial members
        are exempt — they'll be re-checked when ``is_trial`` flips.

        ``only_confirmed=True`` (the trial→full conversion path) counts only
        admin-confirmed equity: on that path the triggering share is already
        confirmed but sibling PENDING shares are NOT swept into confirmation, so
        counting them would admit a member on equity that can later be
        rejected/deleted (BIZ-3). The member-confirm path leaves it False because
        it confirms the member's pending shares in the same action.

        Raises :class:`apps.commissioning.errors.MemberCoopSharesOutOfRange`
        on violation (HTTP 400 ``member.coop_shares_out_of_range``).
        """
        from apps.shared.tenants.models import TenantSettings

        if member is None or member.is_trial:
            return

        tenant = connection.tenant
        current_settings = TenantSettings.get_current_settings(tenant)
        if not current_settings:
            return

        min_coop_shares = current_settings.min_number_coop_shares
        max_coop_shares = current_settings.max_number_coop_shares
        if min_coop_shares is None and max_coop_shares is None:
            return

        total = CoopShareService.member_total_shares(
            member, only_confirmed=only_confirmed
        )
        if min_coop_shares is not None and total < min_coop_shares:
            raise MemberCoopSharesOutOfRange(
                total=total,
                minimum=min_coop_shares,
                maximum=max_coop_shares,
                member_id=str(member.pk),
            )
        if max_coop_shares is not None and total > max_coop_shares:
            raise MemberCoopSharesOutOfRange(
                total=total,
                minimum=min_coop_shares,
                maximum=max_coop_shares,
                member_id=str(member.pk),
            )

    # NOTE: a bulk validator (assert_many_within_min_max) was removed as dead
    # code. If a real bulk coop-share path appears, reintroduce one that
    # delegates to assert_within_min_max per (member, would-be-amount) pair so
    # the bounds comparison + trial exemption stay single-sourced.
