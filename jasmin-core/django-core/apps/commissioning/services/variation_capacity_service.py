"""Enforce ``ShareTypeVariation.capacity`` — the farm-wide production cap.

The production-axis twin of :class:`CapacityReservationService` (which guards
the per-week delivery-station-day *logistics* cap). A subscription must fit
BOTH gates: its station-day's weekly slot AND its variation's farm-wide total.
Either being full sends the order to the waiting list.

Occupancy is measured **per ISO week**, exactly like the station-day cap: a
subscription occupies its variation in EVERY week its term
``[valid_from, valid_until]`` intersects (quantity-weighted), and a term is
full when the *busiest* week in it — the "peak week" — has no room. This is
the one source of truth that the serializer's ``capacity_by_week`` exposes and
the office capacity overview / abos select / new-subscription modal all read,
so what the office SEES (peak/total for a term) is exactly what BLOCKS a save.

Unlike the DSD service there is NO reservation table: occupancy is a live count
of confirmed subscriptions, checked under a row lock at subscribe + confirm.
Abandoned drafts therefore never squat a variation slot; the trade-off is that
the create-time check is best-effort (two drafts can both be created for the
last share) with the confirm-time check as the authoritative gate — the office
confirms one, the other trips the backstop.
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections import defaultdict
from collections.abc import Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..errors import ShareTypeVariationOverCapacity
from ..models import ShareTypeVariation, Subscription
from ..utils.iso_week_utils import previous_monday, week_day_to_date

logger = logging.getLogger(__name__)


def _occupying_q() -> Q:
    """A subscription occupies a production slot when it is:

    * **ACTIVE** — admin-confirmed and off the waiting list; OR
    * **OFFERED** — a spot-available waiting-list offer whose response window is
      still open. Counting it HOLDS the freed slot for the whole offer window so
      a concurrent subscribe can't snipe it out from under the notified member;
      OR
    * **ACCEPTED** — the member accepted the offer (already left the waiting
      list) but the office hasn't admin-confirmed yet. Counting it holds the
      slot across the accept→confirm gap.

    An offer whose window has elapsed drops out automatically via the
    ``notification_expires_at`` time check — even before the sweep job flips its
    status to EXPIRED — so a lapsed offer frees its slot on its own.
    """
    now = timezone.now()
    active = Q(admin_confirmed=True, on_waiting_list=False)
    offered = Q(
        waiting_list_status=Subscription.WaitingListStatus.SPOT_AVAILABLE,
        notification_expires_at__gt=now,
    )
    accepted_pending = Q(
        waiting_list_status=Subscription.WaitingListStatus.CONFIRMED,
        on_waiting_list=False,
        admin_confirmed=False,
    )
    return active | offered | accepted_pending


def _occupying_qs(variation_ids: Iterable[str]):
    """Subs of these variations that consume a production slot (see
    :func:`_occupying_q`): non-cancelled, dated, and active / offered /
    accepted-pending."""
    return Subscription.objects.filter(
        share_type_variation_id__in=list(variation_ids),
        cancelled_at__isnull=True,
        valid_from__isnull=False,
    ).filter(_occupying_q())


class VariationCapacityService:
    # ---- per-week occupancy engine -------------------------------------

    @staticmethod
    def capacity_counts_by_week(
        *,
        variation_ids: Iterable[str],
        year_weeks: Iterable[tuple[int, int]],
    ) -> dict[tuple[str, int, int], int]:
        """Batched concurrent occupancy: ``{(variation_id, year, week): used}``.

        A subscription occupies its variation in EVERY ISO week its term
        intersects (quantity-weighted). The production-cap twin of
        ``ShareDemandService.capacity_counts_by_week`` (which counts physical
        deliveries per week for the logistics cap). One query over the whole
        window, then expand each sub's term across the requested weeks in
        Python — subs carry date ranges, not per-week rows, so there is no
        grouped-by-week SQL to lean on.
        """
        ids = list(variation_ids)
        wanted = list(year_weeks)
        if not ids or not wanted:
            return {}

        # Monday/Sunday calendar bounds for each requested ISO week.
        bounds: list[tuple[int, int, _dt.date, _dt.date]] = []
        for year, week in wanted:
            try:
                monday = week_day_to_date(year, week, 0)
                sunday = week_day_to_date(year, week, 6)
            except (ValueError, TypeError):
                continue
            bounds.append((year, week, monday, sunday))
        if not bounds:
            return {}
        window_start = min(b[2] for b in bounds)
        window_end = max(b[3] for b in bounds)

        subs = (
            _occupying_qs(ids)
            .filter(valid_from__lte=window_end)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=window_start))
            .values_list(
                "share_type_variation_id", "valid_from", "valid_until", "quantity"
            )
        )
        out: dict[tuple[str, int, int], int] = defaultdict(int)
        for var_id, vfrom, vuntil, qty in subs:
            qty = qty or 1
            for year, week, monday, sunday in bounds:
                # Sub active in this week iff its term intersects [Mon, Sun].
                if vfrom > sunday:
                    continue
                if vuntil is not None and vuntil < monday:
                    continue
                out[(var_id, year, week)] += qty
        return dict(out)

    @classmethod
    def _overlapping_qs(cls, variation_id, valid_from, valid_until, exclude_pk):
        qs = _occupying_qs([variation_id])
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if valid_until is not None:
            qs = qs.filter(valid_from__lte=valid_until)
        return qs.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=valid_from))

    @classmethod
    def _peak_occupied_in_term(
        cls, *, variation_id, valid_from, valid_until, exclude_pk
    ) -> int:
        """Busiest single ISO week's occupancy across ``[valid_from,
        valid_until]`` for one variation, excluding ``exclude_pk``
        (quantity-weighted, other subs only).

        The peak of a set of intervals is always reached at some interval's
        START, so we evaluate only the term's own start week plus each
        overlapping sub's start week (clamped into the term) — no need to walk,
        or even bound, an open-ended term week-by-week.
        """
        others = list(
            cls._overlapping_qs(
                variation_id, valid_from, valid_until, exclude_pk
            ).values_list("valid_from", "valid_until", "quantity")
        )
        if not others:
            return 0

        candidate_mondays = {previous_monday(valid_from)}
        for ofrom, _ountil, _oqty in others:
            monday = previous_monday(ofrom if ofrom > valid_from else valid_from)
            if valid_until is not None and monday > valid_until:
                continue
            candidate_mondays.add(monday)

        peak = 0
        for monday in candidate_mondays:
            sunday = monday + _dt.timedelta(days=6)
            occupied = sum(
                (oqty or 1)
                for ofrom, ountil, oqty in others
                if ofrom <= sunday and (ountil is None or ountil >= monday)
            )
            peak = max(peak, occupied)
        return peak

    # ---- enforcement ---------------------------------------------------

    @classmethod
    @transaction.atomic
    def assert_capacity_available(cls, subscription) -> None:
        """Verify the subscription's variation has room in EVERY week of its
        term. Row-locks the ``ShareTypeVariation`` so concurrent orders
        serialise. No-op when the variation has no cap (``capacity is None``)
        or the subscription has no start date. Callers decide WHEN to call: not
        for a waiting_listed DRAFT (it holds no slot), but always at confirm —
        promoting a waiting_listed subscription must still fit. Raises
        :class:`ShareTypeVariationOverCapacity` (409) when the peak week is
        full.
        """
        variation_id = subscription.share_type_variation_id
        if not variation_id or not subscription.valid_from:
            return

        variation = (
            ShareTypeVariation.objects.select_for_update()
            .filter(pk=variation_id)
            .first()
        )
        if variation is None or variation.capacity is None:
            return  # unlimited — nothing to enforce

        quantity = subscription.quantity or 1
        peak = cls._peak_occupied_in_term(
            variation_id=variation_id,
            valid_from=subscription.valid_from,
            valid_until=subscription.valid_until,
            exclude_pk=subscription.pk,
        )
        if peak + quantity > variation.capacity:
            raise ShareTypeVariationOverCapacity(
                share_type_variation_id=str(variation_id),
                capacity=variation.capacity,
                occupied=peak + quantity,
            )
        logger.debug(
            "variation.capacity ok variation=%s peak=%s+%s cap=%s",
            variation_id,
            peak,
            quantity,
            variation.capacity,
        )

    @classmethod
    def is_over_capacity(cls, subscription) -> bool:
        """Non-locking, non-raising twin of :meth:`assert_capacity_available` —
        used to infer WHY a subscription is being waiting_listed. ``False`` for
        unlimited / termless / variation-less subs."""
        variation_id = subscription.share_type_variation_id
        if not variation_id or not subscription.valid_from:
            return False
        variation = ShareTypeVariation.objects.filter(pk=variation_id).first()
        if variation is None or variation.capacity is None:
            return False
        peak = cls._peak_occupied_in_term(
            variation_id=variation_id,
            valid_from=subscription.valid_from,
            valid_until=subscription.valid_until,
            exclude_pk=subscription.pk,
        )
        return peak + (subscription.quantity or 1) > variation.capacity
