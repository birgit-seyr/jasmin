"""Reserve / release a draft subscription's delivery-station-day capacity.

A reservation is created at order/draft save — BEFORE the subscription's
``ShareDelivery`` rows materialise at admin-confirm — so two members can't
both grab the last slot and then both fail at confirm. Occupancy is therefore
``confirmed ShareDeliveries + active reservations`` (see
``SubscriptionDemandBackend`` in ``share_demand_service``).

See :class:`apps.commissioning.models.CapacityReservation` for the lifecycle
(create on draft, delete on confirm, CASCADE on reject/delete, expire via
``expires_at``).
"""

from __future__ import annotations

import datetime
import logging

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..errors import DeliveryStationOverCapacity
from ..models import CapacityReservation, DeliveryStationDay, ShareDelivery

logger = logging.getLogger(__name__)

# How long an unconfirmed draft holds its slot before the reservation lapses.
# "Active" is purely ``expires_at > now``, so this is also the auto-release
# window — long enough for the office to confirm, short enough that an
# abandoned order frees the slot.
RESERVATION_TTL_DAYS = 14

# A share occupies station-day capacity iff it is a STANDALONE (non-additional)
# share — i.e. ``share_type.is_additional_share_type is False``. Additional
# shares are "packed into another share's box" (e.g. honey dropped into the
# veg box), so they take no separate pickup slot and never consume or reserve
# capacity. Mirrors ``DeliveryStationDay.get_occupied_capacity`` +
# ``ShareDemandService`` occupancy so reservations stay in lock-step.


class CapacityReservationService:
    @classmethod
    @transaction.atomic
    def reserve_for_subscription(cls, subscription) -> None:
        """(Re)create this draft subscription's reservations across its period.

        Race-safe: locks the ``DeliveryStationDay`` row for the duration, so
        concurrent reservations for the same station-day serialise. Raises
        :class:`DeliveryStationOverCapacity` for the first full week and
        creates NO reservations in that case (the whole order is refused).

        No-op when the subscription doesn't consume harvest capacity: no
        default station-day, missing dates, a non-harvest share option, or a
        station-day with no capacity limit.

        Reserves against the ACTUAL per-week station-day (via
        ``SubscriptionService.resolve_station_days_by_week``): the default DSD
        when it is open-ended, else the per-week successor for a time-bounded
        default — matching what ``_create_share_deliveries`` materializes, so a
        mid-term handoff can't slip a delivery onto an over-full successor DSD.
        """
        delivery_station_day_id = subscription.default_delivery_station_day_id
        if (
            not delivery_station_day_id
            or not subscription.valid_from
            or not subscription.valid_until
        ):
            return
        if not cls._counts_toward_capacity(subscription):
            return

        # Drop any prior holds for this subscription first (re-reserve on edit)
        # so the occupancy counts below exclude our own old rows.
        CapacityReservation.objects.filter(subscription=subscription).delete()

        # Resolve the ACTUAL per-week station-day (the default DSD when it is
        # open-ended, else the per-week successor for a time-bounded default) so
        # capacity is reserved against the DSD materialization will write to —
        # not just the default. A handoff week otherwise lands on a successor
        # DSD whose own capacity was never reserved.
        from .subscription_service import SubscriptionService

        delivery_station_day_by_week = SubscriptionService.resolve_station_days_by_week(
            subscription
        )
        if not delivery_station_day_by_week:
            return

        # Lock every distinct resolved DSD in a deterministic (id) order so
        # concurrent reservations serialise without deadlocking.
        distinct_ids = sorted(
            {
                delivery_station_day.id
                for delivery_station_day in delivery_station_day_by_week.values()
            }
        )
        locked = {
            delivery_station_day.id: delivery_station_day
            for delivery_station_day in DeliveryStationDay.objects.select_for_update()
            .filter(id__in=distinct_ids)
            .order_by("id")
        }

        from .share_demand_service import ShareDemandService

        year_weeks = list(delivery_station_day_by_week.keys())
        # Counts confirmed deliveries + OTHER active reservations (our own holds
        # were just deleted above), per (resolved DSD, year, week).
        occupied_by_week = ShareDemandService.capacity_counts_by_week(
            station_day_ids=distinct_ids,
            year_weeks=year_weeks,
        )

        quantity = subscription.quantity or 1
        expires_at = timezone.now() + datetime.timedelta(days=RESERVATION_TTL_DAYS)
        to_create: list[CapacityReservation] = []
        for (year, week), resolved in delivery_station_day_by_week.items():
            delivery_station_day = locked[resolved.id]
            occupied = occupied_by_week.get((delivery_station_day.id, year, week), 0)
            # ``occupied`` is everyone else (own holds deleted above) and is
            # quantity-weighted; add this subscription's ``quantity`` before
            # comparing — otherwise a quantity=N order slips into one free slot.
            if occupied + quantity > delivery_station_day.capacity:
                raise DeliveryStationOverCapacity(
                    station_day_id=delivery_station_day.id,
                    year=year,
                    week=week,
                    capacity=delivery_station_day.capacity,
                    occupied=occupied + quantity,
                )
            to_create.append(
                CapacityReservation(
                    subscription=subscription,
                    delivery_station_day=delivery_station_day,
                    year=year,
                    week=week,
                    expires_at=expires_at,
                )
            )
        CapacityReservation.objects.bulk_create(to_create)
        logger.info(
            "capacity.reserved subscription=%s weeks=%s delivery_station_days=%s",
            subscription.pk,
            len(to_create),
            len(distinct_ids),
        )

    @classmethod
    @transaction.atomic
    def assert_capacity_available_for_confirm(cls, subscription) -> None:
        """Confirm-time backstop: verify each period week still has room,
        counting everyone EXCEPT this subscription's own (still-active) holds.

        Locks the station-day so concurrent confirms serialise. If our hold is
        still active it reserved the slot and the check passes; if it lapsed
        and someone else took the slot, raises
        :class:`DeliveryStationOverCapacity`.
        """
        delivery_station_day_id = subscription.default_delivery_station_day_id
        if (
            not delivery_station_day_id
            or not subscription.valid_from
            or not subscription.valid_until
        ):
            return
        if not cls._counts_toward_capacity(subscription):
            return

        # Resolve the ACTUAL per-week station-day so the backstop verifies each
        # week against the DSD materialization will write to (a time-bounded
        # default hands off to successor DSDs mid-term).
        from .subscription_service import SubscriptionService

        delivery_station_day_by_week = SubscriptionService.resolve_station_days_by_week(
            subscription
        )
        if not delivery_station_day_by_week:
            return

        distinct_ids = sorted(
            {
                delivery_station_day.id
                for delivery_station_day in delivery_station_day_by_week.values()
            }
        )
        locked = {
            delivery_station_day.id: delivery_station_day
            for delivery_station_day in DeliveryStationDay.objects.select_for_update()
            .filter(id__in=distinct_ids)
            .order_by("id")
        }

        from .share_demand_service import ShareDemandService

        now = timezone.now()
        year_weeks = list(delivery_station_day_by_week.keys())
        total_by_week = ShareDemandService.capacity_counts_by_week(
            station_day_ids=distinct_ids,
            year_weeks=year_weeks,
        )
        # Our own still-active holds, quantity-weighted (Coalesce(quantity, 1))
        # to match ``total``, per (resolved DSD, year, week). A plain row count
        # under-subtracts for a multi-quantity subscription.
        own_by_week = {
            (row["delivery_station_day_id"], row["year"], row["week"]): row["c"]
            for row in CapacityReservation.objects.filter(
                subscription=subscription,
                delivery_station_day_id__in=distinct_ids,
                expires_at__gt=now,
            )
            .values("delivery_station_day_id", "year", "week")
            .annotate(c=Sum(Coalesce("subscription__quantity", 1)))
        }
        quantity = subscription.quantity or 1
        for (year, week), resolved in delivery_station_day_by_week.items():
            delivery_station_day = locked[resolved.id]
            total = total_by_week.get((delivery_station_day.id, year, week), 0)
            # Subtract our own active hold(s) for this slot so we measure
            # everyone else against the cap, then the slots we need must fit.
            own = own_by_week.get((delivery_station_day.id, year, week), 0)
            if (total - own) + quantity > delivery_station_day.capacity:
                raise DeliveryStationOverCapacity(
                    station_day_id=delivery_station_day.id,
                    year=year,
                    week=week,
                    capacity=delivery_station_day.capacity,
                    occupied=(total - own) + quantity,
                )

    @classmethod
    def assert_restore_fits(
        cls,
        *,
        delivery_station_day_id: str,
        year: int,
        week: int,
        is_additional_share_type: bool,
        quantity: int,
    ) -> None:
        """Un-pause restore: materialising ``quantity`` slots for a station-day
        must not push it over capacity. While a delivery pause was active the
        freed slots may have been filled by NEW confirmed subscriptions, so
        blindly restoring the paused deliveries can overbook the week — raise
        :class:`DeliveryStationOverCapacity` instead of silently overfilling
        (BIZ-6). Locks the station-day for race-safety, mirroring the confirm /
        move checks. No-op for additional (packed-along) shares — they take no
        pickup slot.
        """
        if is_additional_share_type:
            return
        delivery_station_day = DeliveryStationDay.objects.select_for_update().get(
            pk=delivery_station_day_id
        )
        occupied = delivery_station_day.get_occupied_capacity(year, week)
        if occupied + quantity > delivery_station_day.capacity:
            raise DeliveryStationOverCapacity(
                station_day_id=delivery_station_day.id,
                year=year,
                week=week,
                capacity=delivery_station_day.capacity,
                occupied=occupied + quantity,
            )

    @classmethod
    @transaction.atomic
    def assert_share_delivery_fits(
        cls,
        *,
        delivery_station_day_id: str,
        year: int,
        week: int,
        is_additional_share_type: bool,
        moving_delivery_id: str | None = None,
    ) -> None:
        """Assert a standalone ShareDelivery may occupy ``delivery_station_day_id``
        for ``(year, week)`` — used when the office moves a delivery to another
        station-day. Locks the station-day for race-safety.

        No-op for additional (packed-along) deliveries — they take no slot.
        ``moving_delivery_id`` is the delivery being moved IN: if it already sits
        at this station-day for this week (a non-move re-save), it is discounted
        so we don't block on a delivery against itself.
        """
        if is_additional_share_type:
            return
        delivery_station_day = DeliveryStationDay.objects.select_for_update().get(
            pk=delivery_station_day_id
        )

        occupied = delivery_station_day.get_occupied_capacity(year, week)

        # The delivery being moved in occupies ``incoming_quantity`` slots
        # (quantity-weighted, matching ``occupied``; a subscription-less delivery
        # counts as 1). If it already sits here this week it's already inside
        # ``occupied``, so subtract its weight to measure everyone else, then add
        # it back below — a re-save onto the same station-day nets to zero.
        incoming_quantity = 1
        already_here = False
        if moving_delivery_id is not None:
            moving = (
                ShareDelivery.objects.filter(pk=moving_delivery_id)
                .values(
                    "subscription__quantity",
                    "delivery_station_day_id",
                    "share__year",
                    "share__delivery_week",
                )
                .first()
            )
            if moving is not None:
                incoming_quantity = moving["subscription__quantity"] or 1
                already_here = (
                    moving["delivery_station_day_id"] == delivery_station_day_id
                    and moving["share__year"] == year
                    and moving["share__delivery_week"] == week
                )
        others = (occupied - incoming_quantity) if already_here else occupied

        if others + incoming_quantity > delivery_station_day.capacity:
            raise DeliveryStationOverCapacity(
                station_day_id=delivery_station_day.id,
                year=year,
                week=week,
                capacity=delivery_station_day.capacity,
                occupied=others + incoming_quantity,
            )

    @staticmethod
    def release_for_subscription(subscription) -> None:
        """Drop this subscription's reservations.

        Called at confirm (once the real ``ShareDelivery`` rows hold the slots,
        else occupancy double-counts), on waiting_list flips, on member-cancel of a
        draft, and on reject. Deleting the Subscription ROW also frees them via
        the ``on_delete=CASCADE`` FK — but reject only STAMPS flags (no row
        delete), so the reject path must call this explicitly.
        """
        CapacityReservation.objects.filter(subscription=subscription).delete()

    @staticmethod
    def _counts_toward_capacity(subscription) -> bool:
        """A subscription occupies station-day capacity iff its share_type is a
        standalone (non-additional) share. Add-ons (``is_additional_share_type``)
        ride along in another share's box and take no slot. Unknown share_type
        (defensive) → False, i.e. reserve nothing — matches the old ``None``
        share_option skip."""
        variation = getattr(subscription, "share_type_variation", None)
        share_type = getattr(variation, "share_type", None)
        if share_type is None:
            return False
        return not share_type.is_additional_share_type
