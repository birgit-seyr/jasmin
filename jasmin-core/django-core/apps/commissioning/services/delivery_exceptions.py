"""Delivery-exception ("Lieferpause") wiring.

A ``DeliveryExceptionPeriod`` marks a whole-week range during which a
``ShareTypeVariation`` is NOT delivered. The single lever is ShareDelivery
materialisation: with no ShareDelivery in a paused week there is no production
demand and — because billing is driven off ShareDeliveries — no billing for
that week either.

Two entry points:

* :func:`paused_weeks_for_variation` — used by the subscription generation path
  to skip paused weeks when materialising a NEW / renewed subscription.
* :func:`resync_delivery_exception` — used by the CRUD endpoints to bring
  ALREADY-confirmed subscriptions in line after a pause is created / edited /
  deleted: suppress deliveries in newly-paused weeks, restore them in
  newly-freed weeks, recompute the affected shares' stock/theoreticals, and
  re-plan charges via the subscription-changed hook. FUTURE weeks only —
  mirrors :func:`..services.subscription_deliveries.truncate_future_deliveries`
  so an already issued/paid week is never retro-edited.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from isoweek import Week

from ..models import DeliveryExceptionPeriod, Share, ShareDelivery, Subscription
from .recompute import recompute_shares

# An ISO ``(year, week)`` tuple.
YearWeek = tuple[int, int]


def weeks_in_range(
    valid_from: datetime.date | None, valid_until: datetime.date | None
) -> set[YearWeek]:
    """The ISO ``(year, week)`` tuples covered by a whole-week
    ``[valid_from (Monday) … valid_until (Sunday)]`` range."""
    if not valid_from or not valid_until:
        return set()
    weeks: set[YearWeek] = set()
    day = valid_from
    while day <= valid_until:
        iso_year, iso_week, _ = day.isocalendar()
        weeks.add((iso_year, iso_week))
        day += datetime.timedelta(days=7)
    return weeks


def paused_weeks_for_variation(
    share_type_variation_id, candidate_weeks: Iterable[YearWeek]
) -> set[YearWeek]:
    """Of ``candidate_weeks``, the subset paused by ANY DeliveryExceptionPeriod
    of the given variation. One query; used by the generation path."""
    candidate = set(candidate_weeks)
    if not candidate:
        return set()
    periods = list(
        DeliveryExceptionPeriod.objects.filter(
            share_type_variation_id=share_type_variation_id
        ).values_list("valid_from", "valid_until")
    )
    if not periods:
        return set()
    paused: set[YearWeek] = set()
    for year, week in candidate:
        monday = Week(year, week).monday()
        for valid_from, valid_until in periods:
            # An open-ended (valid_until is None) pause is rejected at the API
            # boundary; guard here so a stray legacy row can't raise a TypeError
            # ("<=" against None) on the subscription-generation hot path.
            if valid_from and valid_until and valid_from <= monday <= valid_until:
                paused.add((year, week))
                break
    return paused


def paused_weeks_by_variation(
    variation_ids: Iterable[str], candidate_weeks: Iterable[YearWeek]
) -> dict[str, set[YearWeek]]:
    """Batched :func:`paused_weeks_for_variation` over many variations in ONE
    query. Returns ``{variation_id: {paused (year, week), …}}`` (only variations
    with at least one paused candidate week appear). Used by the capacity
    display so a variation isn't shown as "full" on a week nothing delivers."""
    ids = list(variation_ids)
    candidate = set(candidate_weeks)
    if not ids or not candidate:
        return {}
    periods_by_var: dict[str, list] = {}
    for var_id, valid_from, valid_until in DeliveryExceptionPeriod.objects.filter(
        share_type_variation_id__in=ids
    ).values_list("share_type_variation_id", "valid_from", "valid_until"):
        # Open-ended pauses are rejected at the API boundary; guard a stray
        # legacy row so ``<=`` against None can't raise (same as the per-variation
        # helper above).
        if valid_from and valid_until:
            periods_by_var.setdefault(var_id, []).append((valid_from, valid_until))
    out: dict[str, set[YearWeek]] = {}
    for var_id, periods in periods_by_var.items():
        paused: set[YearWeek] = set()
        for year, week in candidate:
            monday = Week(year, week).monday()
            if any(vf <= monday <= vu for vf, vu in periods):
                paused.add((year, week))
        if paused:
            out[var_id] = paused
    return out


def _is_future_week(year_week: YearWeek, today: datetime.date) -> bool:
    """A week is still editable when its Monday is on/after today — i.e. it
    hasn't started. Conservative: a week already in progress is left untouched
    so its (possibly billed) deliveries aren't retro-edited."""
    return Week(year_week[0], year_week[1]).monday() >= today


@transaction.atomic
def resync_delivery_exception(
    *,
    share_type_variation_id,
    newly_paused_weeks: Iterable[YearWeek],
    freed_weeks: Iterable[YearWeek],
) -> None:
    """Reconcile already-confirmed subscriptions of a variation after its pause
    set changed. FUTURE weeks only. Deletes deliveries in newly-paused weeks,
    (re)creates them in newly-freed weeks, then recomputes affected shares and
    re-plans charges per touched subscription."""
    from apps.shared.subscription_hooks import notify_subscription_changed

    today = timezone.localdate()
    paused = {w for w in newly_paused_weeks if _is_future_week(w, today)}
    freed = {w for w in freed_weeks if _is_future_week(w, today)}
    if not paused and not freed:
        return

    # Only subscriptions whose term overlaps the affected weeks can have (or
    # need) deliveries in them — a subscription that ended before the earliest
    # affected week, or starts after the latest, is a guaranteed no-op. Narrow
    # to that window in SQL: without it this loop is O(all confirmed
    # subscriptions of the variation, EVER), so on a variation that has run for
    # several seasons every long-expired subscription is dragged through the
    # per-row suppress/restore + charge re-plan below. The affected-week set is
    # small and always in the future, so the window is tight.
    affected_mondays = [Week(year, week).monday() for (year, week) in paused | freed]
    earliest_monday = min(affected_mondays)
    latest_sunday = max(affected_mondays) + datetime.timedelta(days=6)

    subscriptions = (
        Subscription.objects.filter(
            share_type_variation_id=share_type_variation_id,
            admin_confirmed=True,
        )
        .filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=earliest_monday),
            Q(valid_from__isnull=True) | Q(valid_from__lte=latest_sunday),
        )
        .select_related(
            "share_type_variation", "default_delivery_station_day__delivery_day"
        )
    )

    # Do all the ShareDelivery mutations first, accumulating the affected shares
    # and which subscriptions were touched.
    all_affected_share_ids: set = set()
    touched_subscriptions: list[Subscription] = []
    for subscription in subscriptions:
        affected_share_ids: set = set()
        affected_share_ids |= _suppress_weeks(subscription, paused)
        affected_share_ids |= _restore_weeks(subscription, freed)
        if affected_share_ids:
            all_affected_share_ids |= affected_share_ids
            touched_subscriptions.append(subscription)

    # Recompute stock/theoreticals ONCE over the union. Subscriptions of the same
    # variation in the same week share the SAME Share, so a per-subscription
    # recompute redundantly rebuilds the same shares — recompute_shares is the
    # expensive part, so collapsing it to a single call is the big win for a
    # popular variation. (recompute reads the final ShareDelivery state, so it
    # must run after all the suppress/restore mutations above.)
    if all_affected_share_ids:
        recompute_shares(all_affected_share_ids)

    # Charges ARE per-subscription — re-plan each touched one. Payments reacts via
    # the subscription-changed hook and re-plans the PLANNED charges against the
    # now-changed delivery set (locked ISSUED/PAID/FAILED/WAIVED rows preserved).
    for subscription in touched_subscriptions:
        notify_subscription_changed(subscription)


def _suppress_weeks(subscription: Subscription, weeks: set[YearWeek]) -> set:
    """Delete this subscription's ShareDeliveries whose share falls in ``weeks``.
    Returns the affected share ids (for recompute)."""
    if not weeks:
        return set()
    years = {year for (year, _) in weeks}
    week_numbers = {week for (_, week) in weeks}
    # The ``__in`` cross-product can over-match (e.g. (2026, 3) vs (2027, 3)),
    # so narrow to the exact (year, week) tuples in Python.
    to_delete = [
        share_delivery
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription,
            share__year__in=years,
            share__delivery_week__in=week_numbers,
        ).select_related("share")
        if (share_delivery.share.year, share_delivery.share.delivery_week) in weeks
    ]
    if not to_delete:
        return set()
    affected = {
        share_delivery.share_id
        for share_delivery in to_delete
        if share_delivery.share_id
    }
    ShareDelivery.objects.filter(
        pk__in=[share_delivery.pk for share_delivery in to_delete]
    ).delete()
    return affected


def _restore_weeks(subscription: Subscription, weeks: set[YearWeek]) -> set:
    """Re-materialise this subscription's ShareDeliveries for the freed ``weeks``
    it doesn't already have. Returns the affected share ids."""
    if not weeks:
        return set()
    from .subscription_service import SubscriptionService

    # Resolve each of the subscription's delivery weeks to the DSD that should
    # hold it (handles the static default DSD and time-bounded station-day
    # chains), then keep only the freed weeks within the subscription's term.
    targets = {
        year_week: delivery_station_day
        for year_week, delivery_station_day in (
            SubscriptionService.resolve_station_days_by_week(subscription).items()
        )
        if year_week in weeks
    }
    if not targets:
        return set()

    variation = subscription.share_type_variation
    # bulk_create bypasses ShareDelivery.save(), which stamps is_opted_in from
    # the variation default — mirror _create_share_deliveries so an on-by-default
    # opt-in variation isn't born opted-OUT.
    is_opted_in = bool(
        variation and variation.requires_optin and variation.default_optin_state
    )

    # BIZ-6: while the pause was active the freed station-day slots may have been
    # taken by new confirmed subscriptions, so restoring a paused delivery can
    # push the week over capacity. Capacity-check each restore (raises
    # DeliveryStationOverCapacity → the un-pause aborts) instead of silently
    # overbooking. Harvest-share options only; no-op for unlimited station-days.
    from .capacity_reservation_service import CapacityReservationService

    share_option = getattr(getattr(variation, "share_type", None), "share_option", None)
    quantity = subscription.quantity or 1

    existing_weeks = {
        (share_delivery.share.year, share_delivery.share.delivery_week)
        for share_delivery in ShareDelivery.objects.filter(
            subscription=subscription,
            share__year__in={year for (year, _) in targets},
            share__delivery_week__in={week for (_, week) in targets},
        ).select_related("share")
    }

    affected: set = set()
    new_deliveries: list[ShareDelivery] = []
    for (year, week), delivery_station_day in targets.items():
        if (year, week) in existing_weeks:
            continue
        CapacityReservationService.assert_restore_fits(
            delivery_station_day_id=delivery_station_day.id,
            year=year,
            week=week,
            share_option=share_option,
            quantity=quantity,
        )
        share, _ = Share.get_or_create_for_delivery(
            year=year,
            delivery_week=week,
            delivery_day=delivery_station_day.delivery_day,
            share_type_variation=variation,
        )
        new_deliveries.append(
            ShareDelivery(
                subscription=subscription,
                share=share,
                delivery_station_day=delivery_station_day,
                joker_taken=False,
                is_opted_in=is_opted_in,
            )
        )
        affected.add(share.id)
    if new_deliveries:
        ShareDelivery.objects.bulk_create(new_deliveries)
    return affected
