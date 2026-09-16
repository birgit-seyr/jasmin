from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING, Any

from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from core.db_locks import acquire_advisory_xact_lock
from core.tenant_db import connection

from ..errors import (
    CoopShareConfirmedFieldsLocked,
    CoopShareInvalidAmount,
    CoopShareTransferCancellationNotConfirmed,
    CoopShareTransferDateBeforeEntry,
    CoopShareTransferDateInFuture,
    CoopShareTransferExceedsHeld,
    CoopShareTransferGiverNotAdmitted,
    CoopShareTransferReceiverCancelled,
    CoopShareTransferReceiverNotAdmitted,
    CoopShareTransferSameMember,
    MemberAlreadyCancelled,
    MemberCoopSharesOutOfRange,
)

if TYPE_CHECKING:
    from apps.commissioning.models import CoopShare, CoopShareTransfer, Member


@dataclass(frozen=True)
class CoopShareTransferResult:
    transfer: CoopShareTransfer
    from_member_cancelled: bool


class CoopShareService:
    """Business logic for ``CoopShare``: the rules ``CoopShare.clean()`` shares
    with the paths it can't guard, and transfers of shares between members.
    """

    # What the office still maintains on an admin-confirmed share: the payment
    # and payback bookkeeping, the cancellation reason and the note. Every other
    # writable field is the committed Geschäftsanteil and is locked.
    CONFIRMED_EDITABLE_FIELDS = frozenset(
        {"note", "paid_at", "paid_back_date", "cancellation_reason"}
    )
    # The per-share value snapshot (GenG §31). The office grid re-sends the
    # tenant's CURRENT value on every save, so on a confirmed share a differing
    # value is dropped and the snapshot kept, instead of refusing the save —
    # refusing would block every note / paid-back edit on that share once the
    # tenant changes its share value.
    CONFIRMED_SNAPSHOT_FIELDS = frozenset({"value_one_coop_share"})

    @staticmethod
    def assert_valid_amount(amount: Decimal | int | None) -> None:
        """Raise ``CoopShareInvalidAmount`` unless ``amount`` is a whole number
        greater than zero — a cooperative share is a whole Geschäftsanteil.

        The single rule for every write path (office grid, CSV import, member
        self-service). Deliberately not a model validator: ``CoopShare.save()``
        runs ``full_clean()`` on every save (cancellation cascade, confirm), and
        rows written before this rule existed must keep saving.
        """
        if amount is None or amount <= 0:
            raise CoopShareInvalidAmount("amount_of_coop_shares must be greater than 0")
        if amount % 1 != 0:
            raise CoopShareInvalidAmount("amount_of_coop_shares must be a whole number")

    @staticmethod
    def apply_confirmed_share_edit_lock(
        coop_share: CoopShare, attrs: dict[str, Any]
    ) -> None:
        """Refuse an update that changes the committed terms of an
        admin-confirmed coop share; no-op for an unconfirmed one.

        Compares VALUES, not keys: the office grid sends the whole row, so an
        unchanged amount / member / due date riding along with a note edit is
        fine. A differing ``value_one_coop_share`` is removed from ``attrs``
        (mutated in place) so the stored snapshot survives. Raises
        ``CoopShareConfirmedFieldsLocked`` naming every other changed field.
        """
        if not coop_share.admin_confirmed:
            return
        offending: list[str] = []
        for field_name in list(attrs):
            if field_name in CoopShareService.CONFIRMED_EDITABLE_FIELDS:
                continue
            new_value = attrs[field_name]
            if isinstance(new_value, models.Model):
                new_value = new_value.pk
            # Serializer attrs are concrete columns (``member`` compares by its
            # ``member_id`` attname); a reverse relation never reaches here.
            field = coop_share._meta.get_field(field_name)
            attname = field.attname if isinstance(field, models.Field) else field_name
            if new_value == getattr(coop_share, attname):
                continue
            if field_name in CoopShareService.CONFIRMED_SNAPSHOT_FIELDS:
                del attrs[field_name]
                continue
            offending.append(field_name)
        if offending:
            raise CoopShareConfirmedFieldsLocked(sorted(offending))

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
        # shares that are later rejected/deleted.
        if only_confirmed:
            qs = qs.filter(admin_confirmed=True)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        return qs.aggregate(total=Sum("amount_of_coop_shares"))["total"] or Decimal(0)

    @staticmethod
    def confirm_pending_for_member(
        member: Member,
        *,
        admin_user,
        confirmed_at: datetime | None = None,
        notify: bool = True,
    ) -> int:
        """Confirm all of ``member``'s pending (unconfirmed, non-cancelled) coop
        shares and return how many were confirmed.

        Used when a member is admitted: confirming the member admits their
        self-subscribed shares in lock-step (the office reviews equity + person
        together). New shares a member subscribes AFTER admission stay pending
        until confirmed separately. The shares are already part of the member's
        live total (which was bounds-checked at member confirmation), so no
        re-validation is needed here.

        ``confirmed_at`` (onboarding mode) dates the shares' confirmation and a
        trial member's entry date; ``notify=False`` suppresses the trial
        conversion email.
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
                admin_confirmed_at=(
                    confirmed_at if confirmed_at is not None else timezone.now()
                ),
                admin_rejection_reason=None,
            )
            convert_trial_member_on_first_coop_share(
                member,
                entry_date=(
                    timezone.localdate(confirmed_at)
                    if confirmed_at is not None
                    else None
                ),
                notify=notify,
            )
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
    def assert_not_below_minimum(
        member: Member, *, only_confirmed: bool = False
    ) -> None:
        """Raise ``MemberCoopSharesOutOfRange`` if ``member``'s live total is below
        the tenant minimum.

        The lower bound only: used after shares leave a member, which can't make
        a total above the maximum worse. Same scope as
        :meth:`assert_within_min_max` (trial members and not-yet-confirmed
        applicants are exempt).
        """
        if not CoopShareService._bounds_apply_to(member):
            return

        from apps.shared.tenants.models import TenantSettings

        current_settings = TenantSettings.get_current_settings(connection.tenant)
        if not current_settings or current_settings.min_number_coop_shares is None:
            return

        total = CoopShareService.member_total_shares(
            member, only_confirmed=only_confirmed
        )
        if total < current_settings.min_number_coop_shares:
            raise MemberCoopSharesOutOfRange(
                total=total,
                minimum=current_settings.min_number_coop_shares,
                maximum=current_settings.max_number_coop_shares,
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
        rejected/deleted. The member-confirm path leaves it False because
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

    @staticmethod
    @transaction.atomic
    def transfer(
        *,
        from_member: Member,
        to_member: Member,
        amount: int,
        transfer_date: date,
        actor,
        note: str | None = None,
        from_member_note: str | None = None,
        to_member_note: str | None = None,
        confirm_member_cancellation: bool = False,
    ) -> CoopShareTransferResult:
        """Move ``amount`` coop shares (Geschäftsanteile, GenG §76) from
        ``from_member`` to ``to_member`` as ledger rows: existing rows stay
        unchanged, the giving member gets a negative row and the receiving member a
        positive row per share value.

        - The giver must be an admitted, non-trial member; the receiver an admitted
          (full or trial) member; neither may be cancelled, and the transfer date
          may not be before either entry date.
        - Only confirmed, uncancelled shares paid by the transfer date can be
          given, in whole shares, share value with the most recent payment first.
        - New rows are confirmed, paid on the transfer date and linked to the
          transfer; ``from_member_note`` / ``to_member_note`` become their notes.
        - The min/max window is checked once on the final state of both members:
          the receiver against the whole window, the giver's confirmed shares
          against the minimum (``member.coop_shares_out_of_range``).
        - A giver whose confirmed shares sum to zero is cancelled, which
          ``confirm_member_cancellation`` has to confirm: those rows are closed
          (cancelled without a payback date, linked through
          ``settled_by_transfer``) and ``cancel_member_with_coop_shares`` cancels
          the member effective on the transfer date. It refuses a member with
          active subscriptions and sends the cancellation email, which then says
          no settlement follows.
        - A trial receiver is converted to a full member, with the transfer date as
          entry date.
        """
        from apps.commissioning.models import CoopShare, CoopShareTransfer, Member
        from apps.commissioning.services.member_cancellation import (
            cancel_member_with_coop_shares,
        )
        from apps.commissioning.services.trial_conversion import (
            convert_trial_member_on_first_coop_share,
        )

        CoopShareService.assert_valid_amount(amount)
        if from_member.pk == to_member.pk:
            raise CoopShareTransferSameMember()
        if transfer_date > timezone.localdate():
            raise CoopShareTransferDateInFuture()

        # Same per-member lock as CoopShareViewSet create/update (the bounds check
        # is check-then-act), taken in sorted order so opposite transfers can't
        # deadlock.
        for member_id in sorted({str(from_member.pk), str(to_member.pk)}):
            acquire_advisory_xact_lock(f"coop_share_bounds:{member_id}")
        locked = {
            member.pk: member
            for member in Member.objects.select_for_update()
            .filter(pk__in=[from_member.pk, to_member.pk])
            .order_by("pk")
        }
        from_member = locked[from_member.pk]
        to_member = locked[to_member.pk]

        if from_member.cancelled_at is not None:
            raise MemberAlreadyCancelled("The giving member is already cancelled.")
        if not from_member.admin_confirmed or from_member.is_trial:
            raise CoopShareTransferGiverNotAdmitted()
        if to_member.cancelled_at is not None:
            raise CoopShareTransferReceiverCancelled()
        if not to_member.admin_confirmed or to_member.admin_rejected_at is not None:
            raise CoopShareTransferReceiverNotAdmitted()
        for side, member in (("from_member", from_member), ("to_member", to_member)):
            if member.entry_date is not None and transfer_date < member.entry_date:
                raise CoopShareTransferDateBeforeEntry(
                    entry_date=member.entry_date.isoformat(), member=side
                )

        given_by_value = CoopShareService._allocate_paid_shares(
            from_member, amount, transfer_date
        )

        receiver_had_shares = CoopShareService.member_total_shares(to_member) > 0
        now = timezone.now()
        coop_share_transfer = CoopShareTransfer.objects.create(
            from_member=from_member,
            to_member=to_member,
            amount_of_coop_shares=amount,
            transfer_date=transfer_date,
            note=note,
            created_by=actor,
        )
        paid_at = timezone.make_aware(datetime.combine(transfer_date, time.min))
        for value_one_coop_share, taken in given_by_value.items():
            for member, signed_amount, row_note, is_increase in (
                (from_member, -taken, from_member_note, False),
                (to_member, taken, to_member_note, receiver_had_shares),
            ):
                CoopShareService._save_without_bounds_check(
                    CoopShare(
                        member=member,
                        amount_of_coop_shares=signed_amount,
                        value_one_coop_share=value_one_coop_share,
                        paid_at=paid_at,
                        is_increase=is_increase,
                        note=row_note,
                        admin_confirmed=True,
                        admin_confirmed_by=actor,
                        admin_confirmed_at=now,
                        transfer=coop_share_transfer,
                    )
                )

        CoopShareService.assert_within_min_max(member=to_member, new_amount=Decimal(0))
        from_member_cancelled = (
            CoopShareService.member_total_shares(from_member, only_confirmed=True) == 0
        )
        if from_member_cancelled:
            if not confirm_member_cancellation:
                raise CoopShareTransferCancellationNotConfirmed()
            for row in CoopShare.objects.filter(
                member=from_member, admin_confirmed=True, cancelled_at__isnull=True
            ):
                row.cancelled_at = now
                row.cancelled_effective_at = transfer_date
                row.cancelled_by = actor
                row.payback_due_date = None
                row.settled_by_transfer = coop_share_transfer
                CoopShareService._save_without_bounds_check(
                    row,
                    update_fields=[
                        "cancelled_at",
                        "cancelled_effective_at",
                        "cancelled_by",
                        "payback_due_date",
                        "settled_by_transfer",
                    ],
                )
            cancel_member_with_coop_shares(
                from_member,
                cancelled_effective_at=transfer_date,
                cancelled_by=actor,
                shares_transferred=True,
            )
        else:
            CoopShareService.assert_not_below_minimum(from_member, only_confirmed=True)

        if to_member.is_trial:
            convert_trial_member_on_first_coop_share(
                to_member, entry_date=transfer_date
            )

        return CoopShareTransferResult(
            transfer=coop_share_transfer, from_member_cancelled=from_member_cancelled
        )

    @staticmethod
    def _allocate_paid_shares(
        member: Member, amount: int, transfer_date: date
    ) -> dict[int, Decimal]:
        """Split ``amount`` over the member's share values, in whole shares.

        Per share value, counts confirmed, uncancelled rows paid by the transfer
        date (negative rows of earlier transfers included), capped by what the
        member holds of that value today, so a backdated transfer can't give shares
        a transfer dated later already gave away. Share values with the most
        recent payment are used first. Raises ``CoopShareTransferExceedsHeld`` when
        the whole shares don't cover ``amount``.
        """
        from apps.commissioning.models import CoopShare

        rows = list(
            CoopShare.objects.select_for_update().filter(
                member=member,
                admin_confirmed=True,
                paid_at__isnull=False,
                cancelled_at__isnull=True,
            )
        )
        held_today: defaultdict[int, Decimal] = defaultdict(Decimal)
        held_on_transfer_date: defaultdict[int, Decimal] = defaultdict(Decimal)
        latest_payment: dict[int, datetime] = {}
        for row in rows:
            value = row.value_one_coop_share
            held_today[value] += row.amount_of_coop_shares
            if (
                row.paid_at is None
                or timezone.localtime(row.paid_at).date() > transfer_date
            ):
                continue
            held_on_transfer_date[value] += row.amount_of_coop_shares
            latest_payment[value] = max(
                latest_payment.get(value, row.paid_at), row.paid_at
            )

        whole_by_value: dict[int, Decimal] = {}
        for value, held in held_on_transfer_date.items():
            whole = min(held, held_today[value]).to_integral_value(rounding=ROUND_FLOOR)
            if whole >= 1:
                whole_by_value[value] = whole
        available = sum(whole_by_value.values(), Decimal(0))
        if amount > available:
            raise CoopShareTransferExceedsHeld(available=int(available))

        still_needed = Decimal(amount)
        given_by_value: dict[int, Decimal] = {}
        for value in sorted(
            whole_by_value, key=latest_payment.__getitem__, reverse=True
        ):
            if still_needed <= 0:
                break
            taken = min(whole_by_value[value], still_needed)
            given_by_value[value] = taken
            still_needed -= taken
        return given_by_value

    @staticmethod
    def _save_without_bounds_check(share: CoopShare, **kwargs: Any) -> None:
        """Save through ``JasminModel.save`` (the audit log still records the
        change) but skip ``CoopShare.save``'s ``full_clean()``: its min/max check
        would see a half-applied transfer. ``transfer`` checks the window on the
        final state instead."""
        from apps.commissioning.models import CoopShare

        super(CoopShare, share).save(**kwargs)

    # NOTE: there is no bulk validator. If a real bulk coop-share path appears,
    # add one that delegates to assert_within_min_max per (member,
    # would-be-amount) pair so the bounds comparison + trial exemption stay
    # single-sourced.
