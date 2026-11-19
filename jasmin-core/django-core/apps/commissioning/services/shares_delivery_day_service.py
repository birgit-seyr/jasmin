from __future__ import annotations

import datetime
import logging
from datetime import timedelta
from typing import TypeVar

from django.db import transaction
from django.utils import timezone
from isoweek import Week

from apps.shared.iso_week_filters import iso_week_bound

from ..models import (
    CapacityReservation,
    DeliveryStationDay,
    ExternalShareDemand,
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
    if record_date < timebound.valid_from:
        return False
    if timebound.valid_until and record_date > timebound.valid_until:
        return False
    return True


_StationDayRow = TypeVar("_StationDayRow", CapacityReservation, ExternalShareDemand)


def _move_onto_copies(
    model: type[_StationDayRow],
    week_field: str,
    from_week: tuple[int, int],
    copy_by_old_id: dict[str, DeliveryStationDay],
) -> None:
    """Move ``model``'s rows of ``from_week`` on from each closed station day
    onto its copy."""
    rows = list(
        model.objects.filter(delivery_station_day_id__in=copy_by_old_id).filter(
            iso_week_bound(from_week, "gte", week_field=week_field)
        )
    )
    for row in rows:
        row.delivery_station_day = copy_by_old_id[row.delivery_station_day_id]
    if rows:
        model.objects.bulk_update(rows, fields=["delivery_station_day"])


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
            # Post-boundary weeks belong to the copy, so each closed DSD's
            # rows for those weeks move onto it. A draft subscription with an
            # OPEN default DSD holds a CapacityReservation for EVERY week on
            # that single id, and occupancy is strictly id-keyed: a stale
            # reservation on the closed original stops counting, freeing the
            # slot for a concurrent over-book. Imported demand is found through
            # its DSD's delivery day: left on the original, the moved Shares
            # find none, and a host's unchanged re-import is skipped as already
            # applied. It moves only for the weeks whose Shares move, those not
            # begun (``update_shares_for_delivery_day``). (copies carry their
            # nanoid PK from the JasminModel default, set at __init__, so the FK
            # assign is valid.)
            copy_by_old_id = {
                old.id: copy for old, copy in zip(rows_to_close, copies, strict=True)
            }
            vf_week = Week.withdate(valid_from)
            _move_onto_copies(
                CapacityReservation,
                "week",
                (vf_week.year, vf_week.week),
                copy_by_old_id,
            )
            demand_week = max(vf_week, Week.withdate(timezone.localdate()) + 1)
            _move_onto_copies(
                ExternalShareDemand,
                "delivery_week",
                (demand_week.year, demand_week.week),
                copy_by_old_id,
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
        today = timezone.localdate()

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

        for share in future_shares:
            share.delivery_day = new_delivery_day
            for share_field, delivery_day_field in Share.DAY_FIELD_DEFAULTS.items():
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
            update_fields = ["delivery_day", *Share.DAY_FIELD_DEFAULTS]
            Share.objects.bulk_update(future_shares, fields=update_fields)

            # The reassigned harvesting/packing/washing/cleaning/stock days are
            # recompute-relevant inputs. Shares carrying only forecast/default
            # ShareContent have no ShareDelivery, so the sibling
            # update_share_deliveries_for_delivery_day never rebuilds them —
            # rebuild theoreticals/SHARECONTENT movements here so they don't
            # keep amounts computed off the old days. (recompute_shares is
            # idempotent, so the overlap with the sibling is harmless.)
            from .recompute import recompute_shares

            recompute_shares({share.id for share in future_shares})

        return len(future_shares)

    @staticmethod
    @transaction.atomic
    def follow_changed_work_days(
        delivery_day: SharesDeliveryDay, old_defaults: dict[str, int | None]
    ) -> int:
        """Hand a delivery day's changed default work days to its shares of
        this week and later, the way a successor day hands its own on: a share
        takes the new day where it has none or the old default, and keeps a
        day set for its week. A delivery day synced in without work days is
        in use at once, so its shares wait for these. The shares are then
        recomputed, which leaves whatever lies before today as it was.
        ``old_defaults`` holds the defaults before the change, by field name.
        Returns how many shares changed."""
        changed = {
            share_field: default_field
            for share_field, default_field in Share.DAY_FIELD_DEFAULTS.items()
            if getattr(delivery_day, default_field) != old_defaults[default_field]
        }
        if not changed:
            return 0

        this_week = Week.withdate(timezone.localdate())
        shares = Share.objects.filter(
            iso_week_bound((this_week.year, this_week.week), "gte"),
            delivery_day=delivery_day,
        )
        updated: list[Share] = []
        for share in shares:
            follows = [
                share_field
                for share_field, default_field in changed.items()
                if getattr(share, share_field) in (None, old_defaults[default_field])
            ]
            for share_field in follows:
                setattr(share, share_field, getattr(delivery_day, changed[share_field]))
            if follows:
                updated.append(share)

        if updated:
            Share.objects.bulk_update(updated, fields=list(changed))
            from .recompute import recompute_shares

            recompute_shares({share.id for share in updated})
        return len(updated)

    @staticmethod
    @transaction.atomic
    def update_share_deliveries_for_delivery_day(
        new_delivery_day: SharesDeliveryDay,
        old_delivery_day: SharesDeliveryDay | None = None,
    ) -> int:
        """Update future ShareDelivery objects to use the new delivery station
        days when a delivery day is replaced."""
        today = timezone.localdate()

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
        new_day_station_days_by_station: dict[str, list[DeliveryStationDay]] = {}
        for delivery_station_day in DeliveryStationDay.objects.filter(
            delivery_day=new_delivery_day
        ):
            new_day_station_days_by_station.setdefault(
                delivery_station_day.delivery_station_id, []
            ).append(delivery_station_day)

        def _resolve_new_station_day(
            station_id: str, active_at: datetime.date
        ) -> DeliveryStationDay | None:
            for candidate in new_day_station_days_by_station.get(station_id, ()):
                if candidate.is_active_at(active_at):
                    return candidate
            return None

        updated_deliveries: list[ShareDelivery] = []
        for share_delivery in future_deliveries:
            monday = Week(
                share_delivery.share.year, share_delivery.share.delivery_week
            ).monday()
            station_id = share_delivery.delivery_station_day.delivery_station_id
            resolved = _resolve_new_station_day(station_id, monday)
            if resolved is None:
                # The station has no station-day covering this week on the
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
                {share_delivery.share_id for share_delivery in updated_deliveries}
            )

        return len(updated_deliveries)
