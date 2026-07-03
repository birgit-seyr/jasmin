from __future__ import annotations

import datetime
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from isoweek import Week

from ..models import (
    CapacityReservation,
    DeliveryStationDay,
    Share,
    ShareDelivery,
    SharesDeliveryDay,
)
from ..models.mixin import TimeBoundMixin

logger = logging.getLogger(__name__)


def _is_future_and_within_validity(
    record_date: datetime.date,
    today: datetime.date,
    timebound: TimeBoundMixin,
) -> bool:
    """Return True when *record_date* is in the future AND falls inside
    *timebound*'s [valid_from, valid_until] window."""
    if record_date <= today:
        return False
    if timebound.valid_from and record_date < timebound.valid_from:
        return False
    if timebound.valid_until and record_date > timebound.valid_until:
        return False
    return True


class SharesDeliveryDayService:
    @staticmethod
    @transaction.atomic
    def update_delivery_station_days(
        instance: SharesDeliveryDay,
        existing_delivery_day: SharesDeliveryDay,
        validated_data: dict,
    ) -> list[DeliveryStationDay]:
        """Migrate the predecessor day's station-days onto *instance*.

        A station-day that STARTS before the new boundary is closed on the old
        day at ``valid_from - 1`` and copied onto the new day (preserving its
        own end date). A station-day that already starts ON/AFTER the new
        boundary (a same-boundary or future-dated row) is REPOINTED onto the
        new day instead — closing it would give ``valid_until < valid_from`` (a
        negative range), and it already belongs in the successor day's window.
        Repointing carries its ShareDeliveries along automatically, so no
        future child is stranded on the now-closed predecessor day.
        """
        valid_from: datetime.date = validated_data["valid_from"]
        one_day_before = valid_from - timedelta(days=1)

        # ``active_at_date_or_future`` also pulls in future-dated rows
        # (valid_from > boundary) that ``active_at_date`` would miss — otherwise
        # a future-only station-day is orphaned on the now-closed predecessor.
        delivery_station_days = list(
            DeliveryStationDay.current.active_at_date_or_future(valid_from).filter(
                delivery_day=existing_delivery_day
            )
        )

        # Fields copied verbatim onto a new-day copy (the rest are set below).
        exclude_fields = {"id", "pk", "delivery_day", "valid_from", "valid_until"}

        rows_to_close: list[DeliveryStationDay] = []
        rows_to_repoint: list[DeliveryStationDay] = []
        copies: list[DeliveryStationDay] = []
        for delivery_station_day in delivery_station_days:
            if delivery_station_day.valid_from >= valid_from:
                # Already starts on/after the boundary: repoint onto the new day
                # (don't close → no negative range; don't copy → it already
                # lives in the new day's window).
                delivery_station_day.delivery_day = instance
                rows_to_repoint.append(delivery_station_day)
                continue

            # Starts before the boundary: copy onto the new day preserving its
            # OWN end date (an open row stays open; a row that already extended
            # past the boundary keeps that end so it isn't silently turned open
            # — which would also collide with a repointed sibling), then close
            # the original on the old day at boundary - 1.
            fields_to_copy = {
                field.name: getattr(delivery_station_day, field.name)
                for field in delivery_station_day._meta.fields
                if field.name not in exclude_fields
            }
            copies.append(
                DeliveryStationDay(
                    delivery_day=instance,
                    valid_from=valid_from,
                    valid_until=delivery_station_day.valid_until,
                    **fields_to_copy,
                )
            )
            delivery_station_day.valid_until = one_day_before
            rows_to_close.append(delivery_station_day)

        if rows_to_close:
            DeliveryStationDay.objects.bulk_update(
                rows_to_close, fields=["valid_until"]
            )
        if rows_to_repoint:
            DeliveryStationDay.objects.bulk_update(
                rows_to_repoint, fields=["delivery_day"]
            )
        if copies:
            DeliveryStationDay.objects.bulk_create(copies)
            # SUC-3: a draft subscription with an OPEN default DSD holds a
            # CapacityReservation for EVERY week on that single id. After the
            # copy, post-boundary weeks materialize against the new copy's id —
            # but occupancy is strictly id-keyed, so a stale reservation left on
            # the closed original stops counting, freeing the slot for a
            # concurrent over-book. Repoint each closed DSD's post-boundary
            # reservations onto its copy. (copies carry their nanoid PK from the
            # JasminModel default, set at __init__, so the FK assign is valid.)
            copy_by_old_id = {
                old.id: copy for old, copy in zip(rows_to_close, copies, strict=True)
            }
            vf_week = Week.withdate(valid_from)
            reservations = list(
                CapacityReservation.objects.filter(
                    delivery_station_day_id__in=copy_by_old_id
                ).filter(
                    Q(year__gt=vf_week.year)
                    | Q(year=vf_week.year, week__gte=vf_week.week)
                )
            )
            for reservation in reservations:
                reservation.delivery_station_day = copy_by_old_id[
                    reservation.delivery_station_day_id
                ]
            if reservations:
                CapacityReservation.objects.bulk_update(
                    reservations, fields=["delivery_station_day"]
                )

        return copies

    @staticmethod
    @transaction.atomic
    def update_shares_for_delivery_day(
        new_delivery_day: SharesDeliveryDay,
        old_delivery_day: SharesDeliveryDay | None = None,
    ) -> int:
        """Update future Share objects to use the new delivery day if it has
        the same day_number as the old delivery day they were using."""
        today = timezone.now().date()

        if old_delivery_day is None:
            old_delivery_day = (
                SharesDeliveryDay.objects.filter(
                    day_number=new_delivery_day.day_number,
                    valid_until__isnull=False,
                )
                .order_by("-valid_until")
                .first()
            )

        if old_delivery_day is None:
            return 0

        if old_delivery_day.day_number != new_delivery_day.day_number:
            return 0

        shares = Share.objects.filter(delivery_day=old_delivery_day)

        future_shares: list[Share] = [
            share
            for share in shares
            if _is_future_and_within_validity(
                Week(share.year, share.delivery_week).monday(),
                today,
                new_delivery_day,
            )
        ]

        day_fields_mapping: dict[str, str] = {
            "harvesting_day": "default_harvesting_day",
            "packing_day": "default_packing_day",
            "washing_day": "default_washing_day",
            "cleaning_day": "default_cleaning_day",
            "get_current_stock_day": "default_get_current_stock_day",
        }

        for share in future_shares:
            share.delivery_day = new_delivery_day
            for share_field, delivery_day_field in day_fields_mapping.items():
                old_default = getattr(old_delivery_day, delivery_day_field)
                current = getattr(share, share_field)
                # Inherited (or unset) → follow the successor's default, INCLUDING
                # when the successor clears it (None): that matches what a freshly
                # created Share on the successor day would have, and the day is a
                # recompute input. A value differing from the old default is a
                # deliberate per-week override (set via SharesDayChangeService)
                # and must survive this catalogue-level succession untouched.
                if current is None or current == old_default:
                    setattr(
                        share,
                        share_field,
                        getattr(new_delivery_day, delivery_day_field),
                    )

        if future_shares:
            update_fields = ["delivery_day"] + list(day_fields_mapping.keys())
            Share.objects.bulk_update(future_shares, fields=update_fields)

            # The reassigned harvesting/packing/washing/cleaning/stock days are
            # recompute-relevant inputs. Shares carrying only forecast/default
            # ShareContent have no ShareDelivery, so the sibling
            # update_share_deliveries_for_delivery_day never rebuilds them —
            # rebuild theoreticals/SHARECONTENT movements here so they don't
            # keep amounts computed off the old days. (recompute_shares is
            # idempotent, so the overlap with the sibling is harmless.)
            from .recompute import recompute_shares

            recompute_shares({share.id for share in future_shares if share.id})

        return len(future_shares)

    @staticmethod
    @transaction.atomic
    def update_share_deliveries_for_delivery_day(
        new_delivery_day: SharesDeliveryDay,
        old_delivery_day: SharesDeliveryDay | None = None,
    ) -> int:
        """Update future ShareDelivery objects to use the new delivery station
        days when a delivery day is replaced."""
        today = timezone.now().date()

        if old_delivery_day is None:
            return 0

        if old_delivery_day.day_number != new_delivery_day.day_number:
            return 0

        # Future deliveries still attached to the OLD day's station-days. Rows
        # whose station-day was REPOINTED already carry delivery_day=new and are
        # excluded here — they need no remap (the row itself moved).
        share_deliveries = ShareDelivery.objects.filter(
            delivery_station_day__delivery_day=old_delivery_day
        ).select_related("share", "delivery_station_day")

        future_deliveries: list[ShareDelivery] = [
            share_delivery
            for share_delivery in share_deliveries
            if _is_future_and_within_validity(
                Week(
                    share_delivery.share.year, share_delivery.share.delivery_week
                ).monday(),
                today,
                new_delivery_day,
            )
        ]
        if not future_deliveries:
            return 0

        # New-day station-days grouped by station, so each future delivery
        # resolves to the one active at its OWN week — the new day may now hold a
        # chain per station (a copy of the closed row + repointed future rows).
        new_day_dsds_by_station: dict[str, list[DeliveryStationDay]] = {}
        for delivery_station_day in DeliveryStationDay.objects.filter(
            delivery_day=new_delivery_day
        ):
            new_day_dsds_by_station.setdefault(
                delivery_station_day.delivery_station_id, []
            ).append(delivery_station_day)

        def _resolve_new_dsd(
            station_id: str, active_at: datetime.date
        ) -> DeliveryStationDay | None:
            for candidate in new_day_dsds_by_station.get(station_id, ()):
                if candidate.valid_from <= active_at and (
                    candidate.valid_until is None or candidate.valid_until >= active_at
                ):
                    return candidate
            return None

        updated_deliveries: list[ShareDelivery] = []
        for share_delivery in future_deliveries:
            monday = Week(
                share_delivery.share.year, share_delivery.share.delivery_week
            ).monday()
            station_id = share_delivery.delivery_station_day.delivery_station_id
            resolved = _resolve_new_dsd(station_id, monday)
            if resolved is None:
                # SUC-4: the station has no station-day covering this week on the
                # new day, so the delivery can't be remapped. Leaving it on the
                # closed old-day row would violate the Share/ShareDelivery
                # day-match invariant — refuse the whole succession (the viewset
                # wraps this in one transaction) so the office configures the
                # missing station-day and retries, rather than silently stranding
                # the delivery.
                from ..errors import SharesDeliveryDaySuccessionCoverageGap

                raise SharesDeliveryDaySuccessionCoverageGap(
                    station_id=station_id,
                    day_number=new_delivery_day.day_number,
                    week_monday=monday,
                )
            if resolved.id != share_delivery.delivery_station_day_id:
                share_delivery.delivery_station_day = resolved
                updated_deliveries.append(share_delivery)

        if updated_deliveries:
            ShareDelivery.objects.bulk_update(
                updated_deliveries, fields=["delivery_station_day"]
            )
            from .recompute import recompute_shares

            recompute_shares(
                {
                    share_delivery.share_id
                    for share_delivery in updated_deliveries
                    if share_delivery.share_id
                }
            )

        return len(updated_deliveries)
