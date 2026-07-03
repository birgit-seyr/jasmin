"""Retention pre-flight checks — Art. 17(3)(b) blockers for anonymization."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import JasminUser
from apps.commissioning.models import CoopShare, InvoiceReseller, Member, Subscription
from apps.payments.constants import OPEN_CHARGE_STATUSES
from apps.payments.models import ChargeSchedule

if TYPE_CHECKING:
    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there. Method bodies must resolve it at call
    # time through the ASSEMBLED class so monkeypatched attributes on
    # ``GDPRService`` are honoured.
    from . import GDPRService


class RetentionChecksMixin:
    """Retention-blocks checks, mixed into
    :class:`apps.gdpr.services.GDPRService`."""

    # ---------------------------------------------------------------
    # Retention pre-flight
    # ---------------------------------------------------------------

    @staticmethod
    def check_retention_blocks(user: JasminUser) -> list[str]:
        """Return human-readable reasons why anonymizing ``user`` is
        currently refused under Art. 17(3)(b) — empty list means OK.

        Refusal grounds (German law applied):

        - **GenG §5 / §15** — any ``CoopShare`` row attached to the
          subject's Member blocks anonymization (registry obligation
          while shares are held). Future: also block for 10 years
          after the last share is paid back (handled by Step 8's
          retention cron once it's wired).
        - **HGB §257 / UStG §14b** — any **open** finalized invoice
          (``has_been_paid=False``) on a reseller linked to the user
          blocks anonymization. After payment + 10 years, retention
          is satisfied and the cleanup cron (Step 8) handles the
          historical rows.
        - **Active subscription** — a current ``Subscription`` row
          (``valid_until IS NULL`` or in the future) on the subject's
          Member means an ongoing service relationship; anonymizing
          mid-contract would orphan an active billing slot.
        - **Open charge schedule** — any ``ChargeSchedule`` in
          ``PLANNED`` / ``ISSUED`` / ``PARTIAL`` on the subject's
          Member is owed-but-not-paid; same treatment as an open
          invoice.

        Each reason is a short string the frontend can render in a
        list (no PII; safe to log).
        """
        today = timezone.localdate()

        # Soft retention: only OPEN shares / active subs / open charges block
        # anonymisation. GenG §31 keeps the equity-history rows; anonymisation
        # scrubs the member's PII columns while leaving CoopShare.amount /
        # cancelled_at intact. Member-based obligations only apply when the
        # user has a Member row.
        member = Member.objects.filter(user=user).first()
        coop_count = active_sub_count = open_charge_count = 0
        if member is not None:
            # Block while equity is live (open) OR cancelled-but-not-yet-paid-
            # back: the co-op still owes the ex-member their Geschäftsanteile
            # (GenG §73 Auseinandersetzung, Art. 17(3)(b)) and must keep their
            # identity + payout details until ``paid_back_date`` is stamped.
            coop_count = CoopShare.objects.filter(
                Q(cancelled_at__isnull=True) | Q(paid_back_date__isnull=True),
                member=member,
            ).count()
            active_sub_count = (
                Subscription.objects.filter(member=member)
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
                .count()
            )
            open_charge_count = ChargeSchedule.objects.filter(
                member=member,
                status__in=OPEN_CHARGE_STATUSES,
            ).count()

        # Reseller side — for Members who are ALSO B2B customers, plus
        # pure-Reseller users with no Member row.
        open_invoice_count = InvoiceReseller.objects.filter(
            reseller__linked_user=user,
            has_been_paid=False,
            is_finalized=True,
        ).count()

        return GDPRService._retention_reasons(
            coop_count=coop_count,
            active_sub_count=active_sub_count,
            open_charge_count=open_charge_count,
            open_invoice_count=open_invoice_count,
        )

    @staticmethod
    def _retention_reasons(
        *,
        coop_count: int,
        active_sub_count: int,
        open_charge_count: int,
        open_invoice_count: int,
    ) -> list[str]:
        """Build the human-readable blocker list from pre-counted obligations.

        Shared by :meth:`check_retention_blocks` (single user) and
        :meth:`check_retention_blocks_bulk` so the wording can't drift.
        """
        reasons: list[str] = []
        if coop_count > 0:
            reasons.append(
                f"{coop_count} open CoopShare(s) "
                "(GenG §5: cancel before anonymisation)"
            )
        if active_sub_count > 0:
            reasons.append(
                f"{active_sub_count} active subscription(s) "
                "— deletion would orphan an ongoing service contract"
            )
        if open_charge_count > 0:
            reasons.append(
                f"{open_charge_count} open charge(s) "
                "(PLANNED / ISSUED / PARTIAL) — HGB §257"
            )
        if open_invoice_count > 0:
            reasons.append(
                f"{open_invoice_count} unpaid finalized invoice(s) "
                "(UStG §14b: 10-year retention from issue date)"
            )
        return reasons

    @staticmethod
    def check_retention_blocks_bulk(
        users: Iterable[JasminUser],
    ) -> dict[Any, list[str]]:
        """Batched :meth:`check_retention_blocks`: ``{user_id: [reasons]}`` for
        many users in a CONSTANT number of queries (one grouped COUNT per
        obligation) instead of ~5 queries per user. Used by the office GDPR
        pending-deletions inbox, which must reflect current state per row.
        """
        user_ids = [u.id for u in users if u is not None]
        if not user_ids:
            return {}
        today = timezone.localdate()

        # user_id -> member_id (Member.user is OneToOne) — one query.
        member_id_by_user: dict[Any, Any] = {
            user_id: member_id
            for member_id, user_id in Member.objects.filter(
                user_id__in=user_ids
            ).values_list("id", "user_id")
        }
        member_ids = list(member_id_by_user.values())

        def _grouped(qs, group_field: str) -> dict[Any, int]:
            return {
                row[group_field]: row["c"]
                for row in qs.values(group_field).annotate(c=Count("id"))
            }

        coop_by_member: dict[Any, int] = {}
        sub_by_member: dict[Any, int] = {}
        charge_by_member: dict[Any, int] = {}
        if member_ids:
            coop_by_member = _grouped(
                CoopShare.objects.filter(
                    Q(cancelled_at__isnull=True) | Q(paid_back_date__isnull=True),
                    member_id__in=member_ids,
                ),
                "member_id",
            )
            sub_by_member = _grouped(
                Subscription.objects.filter(member_id__in=member_ids).filter(
                    Q(valid_until__isnull=True) | Q(valid_until__gte=today)
                ),
                "member_id",
            )
            charge_by_member = _grouped(
                ChargeSchedule.objects.filter(
                    member_id__in=member_ids, status__in=OPEN_CHARGE_STATUSES
                ),
                "member_id",
            )

        invoice_by_user = _grouped(
            InvoiceReseller.objects.filter(
                reseller__linked_user_id__in=user_ids,
                has_been_paid=False,
                is_finalized=True,
            ),
            "reseller__linked_user_id",
        )

        result: dict[Any, list[str]] = {}
        for user_id in user_ids:
            member_id = member_id_by_user.get(user_id)
            result[user_id] = GDPRService._retention_reasons(
                coop_count=(
                    coop_by_member.get(member_id, 0) if member_id is not None else 0
                ),
                active_sub_count=(
                    sub_by_member.get(member_id, 0) if member_id is not None else 0
                ),
                open_charge_count=(
                    charge_by_member.get(member_id, 0) if member_id is not None else 0
                ),
                open_invoice_count=invoice_by_user.get(user_id, 0),
            )
        return result
