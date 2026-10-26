"""Retention pre-flight checks — Art. 17(3)(b) blockers for anonymization."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.commissioning.models import CoopShare, InvoiceReseller, Member, Subscription
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule

from .subjects import ErasureSubject

if TYPE_CHECKING:
    # Type-only: the runtime path uses ``get_user_model()``, so this module
    # also works under a host project with a different ``AUTH_USER_MODEL``.
    from apps.accounts.models import JasminUser

    # ``GDPRService`` is assembled in the package ``__init__`` and bound into
    # this module's namespace there. Method bodies must resolve it at call
    # time through the ASSEMBLED class so monkeypatched attributes on
    # ``GDPRService`` are honoured.
    from . import GDPRService


def _ongoing_subscriptions(today) -> Q:
    """Subscriptions that are still an ongoing contract: confirmed and running
    until a day still to come. A reject unconfirms, so a confirmed row is no
    rejected application, even when it keeps an earlier ``admin_rejected_at``.
    A cancellation ends the term at ``cancelled_effective_at`` (a member exit
    force-ends it there too) while ``valid_until`` keeps the original end, so
    that date wins when set."""
    still_running = Q(cancelled_effective_at__gte=today) | (
        Q(cancelled_effective_at__isnull=True)
        & (Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    )
    return Q(admin_confirmed=True) & still_running


def _owed_charges() -> Q:
    """Charges that still owe something. The planner writes a PLANNED row for
    every unlocked period, at 0.00 where nothing is owed (a period without
    deliveries, every period after a force-ended term), and nothing ever
    settles those; a planned period that starts after the subscription's
    effective end owes nothing either. Positive conditions only: a negated one
    on the mostly-NULL ``cancelled_effective_at`` would drop rows in SQL."""
    planned_and_owed = (
        Q(status=ChargeStatus.PLANNED)
        & Q(expected_amount__gt=0)
        & (
            Q(subscription__cancelled_effective_at__isnull=True)
            | Q(period_start__lte=F("subscription__cancelled_effective_at"))
        )
    )
    return Q(status__in=[ChargeStatus.ISSUED, ChargeStatus.PARTIAL]) | planned_and_owed


class RetentionChecksMixin:
    """Retention-blocks checks, mixed into
    :class:`apps.gdpr.services.GDPRService`."""

    # ---------------------------------------------------------------
    # Retention pre-flight
    # ---------------------------------------------------------------

    @staticmethod
    def check_retention_blocks(user: JasminUser) -> list[str]:
        """:meth:`check_retention_blocks_for_subject` for a login user and the
        member and reseller records tied to it."""
        return GDPRService.check_retention_blocks_for_subject(
            ErasureSubject.of_user(user)
        )

    @staticmethod
    def check_retention_blocks_for_subject(subject: ErasureSubject) -> list[str]:
        """Return human-readable reasons why anonymizing ``subject`` is
        currently refused under Art. 17(3)(b) — empty list means OK.

        Refusal grounds (German law applied):

        - **GenG §5 / §15** — any ``CoopShare`` row attached to the
          subject's Member blocks anonymization (registry obligation
          while shares are held). Future: also block for 10 years
          after the last share is paid back (handled by a
          retention cron once it's wired).
        - **HGB §257 / UStG §14b** — any **open** finalized invoice
          (``has_been_paid=False``) on the subject's reseller
          blocks anonymization. After payment + 10 years, retention
          is satisfied and a future cleanup cron will handle the
          historical rows.
        - **Active subscription** — a confirmed ``Subscription`` still
          running (its effective end — the cancellation date, else
          ``valid_until`` — open or to come) means
          an ongoing service relationship; anonymizing mid-contract would
          orphan an active billing slot.
        - **Open charge schedule** — a ``ChargeSchedule`` that still owes
          something: ``ISSUED`` / ``PARTIAL``, or ``PLANNED`` above 0.00 for
          a period within the subscription's term; same treatment as an
          open invoice.

        Each reason is a short string the frontend can render in a
        list (no PII; safe to log).
        """
        today = timezone.localdate()

        # Soft retention: only OPEN shares / active subs / open charges block
        # anonymisation. GenG §31 keeps the equity-history rows; anonymisation
        # scrubs the member's PII columns while leaving CoopShare.amount /
        # cancelled_at intact. Member-based obligations only apply when the
        # subject has a Member row.
        member = subject.member
        coop_count = active_sub_count = open_charge_count = 0
        if member is not None:
            # Block while equity is live (open) OR cancelled-but-not-yet-paid-
            # back: the co-op still owes the ex-member their Geschäftsanteile
            # (GenG §73 Auseinandersetzung, Art. 17(3)(b)) and must keep their
            # identity + payout details until ``paid_back_date`` is stamped. Rows a
            # coop share transfer settled owe nothing: the equity moved to another
            # member.
            coop_count = GDPRService._open_coop_share_counts([member.pk]).get(
                member.pk, 0
            )
            active_sub_count = Subscription.objects.filter(
                _ongoing_subscriptions(today), member=member
            ).count()
            open_charge_count = ChargeSchedule.objects.filter(
                _owed_charges(), member=member
            ).count()

        # Reseller side — for Members who are ALSO B2B customers, plus
        # pure Resellers with no Member row.
        open_invoice_count = 0
        if subject.reseller is not None:
            open_invoice_count = InvoiceReseller.objects.filter(
                reseller=subject.reseller,
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
    def _open_coop_share_counts(member_ids: list[Any]) -> dict[Any, int]:
        """Coop share rows that still block anonymisation, per member.

        Live (uncancelled) equity blocks. Cancelled rows block while their equity
        isn't paid back: rows without ``paid_back_date`` that no transfer settled
        count as long as their amounts sum above zero, because a negative
        transfer row nets against the rows its shares came from.
        """
        if not member_ids:
            return {}
        counts: dict[Any, int] = defaultdict(int)
        live = (
            CoopShare.objects.filter(
                member_id__in=member_ids, cancelled_at__isnull=True
            )
            .values("member_id")
            .annotate(rows=Count("id"))
        )
        for row in live:
            counts[row["member_id"]] += row["rows"]
        not_paid_back = (
            CoopShare.objects.filter(
                member_id__in=member_ids,
                cancelled_at__isnull=False,
                paid_back_date__isnull=True,
                settled_by_transfer__isnull=True,
            )
            .values("member_id")
            .annotate(
                total=Sum("amount_of_coop_shares"),
                rows=Count("id", filter=Q(amount_of_coop_shares__gt=0)),
            )
        )
        for row in not_paid_back:
            if row["total"] > 0:
                counts[row["member_id"]] += row["rows"]
        return dict(counts)

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
        user_ids = [u.id for u in users]
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
            coop_by_member = GDPRService._open_coop_share_counts(member_ids)
            sub_by_member = _grouped(
                Subscription.objects.filter(
                    _ongoing_subscriptions(today), member_id__in=member_ids
                ),
                "member_id",
            )
            charge_by_member = _grouped(
                ChargeSchedule.objects.filter(
                    _owed_charges(), member_id__in=member_ids
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
