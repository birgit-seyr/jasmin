"""Errors of time-bound validity windows and of successions between time-bound rows."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
)

# --------------------------------------------------------------------------- #
# Time-bound validity and succession                                          #
# --------------------------------------------------------------------------- #


class ShareTypeSuccessionHasActiveVariations(ConflictError):
    """A new share type can't take over a ``share_option`` while the current
    one still has variations active on or after the new start date. Closing
    the predecessor would strand those variations (and any subscriptions on
    them) outliving their parent. End the variations first (set their
    ``valid_until``), or choose a later start date."""

    code = "share_type.succession_has_active_variations"

    def __init__(self, *, share_option, new_valid_from, active_variation_count) -> None:
        super().__init__(
            f"Cannot start a new '{share_option}' share type on "
            f"{new_valid_from}: the current one still has "
            f"{active_variation_count} variation(s) active on or after that "
            f"date. End those variations first, or choose a later start date.",
            details={
                "share_option": share_option,
                "new_valid_from": str(new_valid_from),
                "active_variation_count": active_variation_count,
            },
        )


class TimeBoundValidFromNotMonday(BadRequestError):
    """A time-bound record starts on a Monday — validity windows are whole ISO
    weeks. ``field`` is ``valid_from``."""

    code = "time_bound.valid_from_not_monday"


class TimeBoundValidUntilNotSunday(BadRequestError):
    """A time-bound record ends on a Sunday — validity windows are whole ISO
    weeks. ``field`` is ``valid_until``."""

    code = "time_bound.valid_until_not_sunday"


class TimeBoundInvalidRange(BadRequestError):
    """A time-bound record's ``valid_until`` lies before its ``valid_from``."""

    code = "time_bound.invalid_range"


class TimeBoundOverlap(BadRequestError):
    """A time-bound record's validity shares a day with another record of its
    overlap group (``overlap_unique_fields``). ``details.context`` is ``open``
    when that record has no end date, so the message can say so."""

    code = "time_bound.overlap"

    def __init__(self, existing) -> None:
        until = existing.valid_until
        details = {
            "existing_valid_from": str(existing.valid_from),
            "existing_valid_until": str(until) if until else None,
        }
        if until is None:
            details["context"] = "open"
        super().__init__(
            "Overlapping period detected with existing record "
            f"({existing.valid_from} to {until})",
            details=details,
        )


class SuccessionStartBeforePredecessor(ConflictError):
    """A new time-bound record can't start *before* the open record it would
    succeed. ``TimeBoundMixin.handle_succession`` closes the predecessor at
    ``new_valid_from - 1 day``; when ``new_valid_from`` is earlier than the
    predecessor's own ``valid_from`` that would hand the predecessor an end
    date before its own start. Choose a start date on or after the existing
    record's, or close the existing record first."""

    code = "time_bound.succession_start_before_predecessor"

    def __init__(self, *, new_valid_from, existing_valid_from) -> None:
        super().__init__(
            f"Cannot start a new record on {new_valid_from}: an existing open "
            f"record already starts later, on {existing_valid_from}. Choose a "
            f"start date on or after that, or close the existing record first.",
            details={
                "new_valid_from": str(new_valid_from),
                "existing_valid_from": str(existing_valid_from),
            },
        )


class ShareTypeVariationOutsideShareTypeRange(BadRequestError):
    """A share type variation's validity must lie WITHIN its share type's
    validity: it can't start before the share type starts, nor stay open / end
    after the share type ends (that would outlive its parent)."""

    code = "share_type_variation.outside_share_type_range"

    def __init__(
        self, *, variation_from, variation_until, share_type_from, share_type_until
    ) -> None:
        super().__init__(
            f"The variation's validity ({variation_from} – "
            f"{variation_until or 'open'}) must lie within its share type's "
            f"validity ({share_type_from} – {share_type_until or 'open'}).",
            details={
                "variation_valid_from": str(variation_from),
                "variation_valid_until": (
                    str(variation_until) if variation_until else None
                ),
                "share_type_valid_from": str(share_type_from),
                "share_type_valid_until": (
                    str(share_type_until) if share_type_until else None
                ),
            },
        )


class ShareTypeShorteningStrandsVariation(ConflictError):
    """Shortening (or closing) a share type's validity would strand a child
    variation that is open or ends after the new end date — the variation
    (and any subscriptions on it) would outlive its parent. End or shorten
    those variations first, or pick a later end date."""

    code = "share_type.shortening_strands_variation"

    def __init__(self, *, share_type, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end share type '{share_type}' on {new_valid_until}: "
            f"{stranded_count} variation(s) are open or end after that date and "
            "would outlive their parent. End or shorten those variations first.",
            details={
                "share_type": share_type,
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class ShareTypeVariationSuccessionHasActiveSubscriptions(ConflictError):
    """A new share type variation can't take over a ``(share_type, size)``
    slot while the current one still has subscription groups active on or
    after the new start date. The subscription→variation link is locked once
    subscriptions exist, so closing the predecessor would strand those
    subscriptions (and their materialized shares) on a closed variation,
    dropping them out of harvest/packing/demand planning. End those
    subscriptions first, or choose a later start date."""

    code = "share_type_variation.succession_has_active_subscriptions"

    def __init__(
        self, *, share_type, size, new_valid_from, active_subscription_count
    ) -> None:
        super().__init__(
            f"Cannot start a new '{size}' variation of '{share_type}' on "
            f"{new_valid_from}: the current one still has "
            f"{active_subscription_count} subscription(s) running on or after "
            "that date. The successor can only start once the last subscription "
            "has ended — end them first, or choose a later start date.",
            details={
                "share_type": str(share_type),
                "size": size,
                "new_valid_from": str(new_valid_from),
                "active_subscription_count": active_subscription_count,
            },
        )


class ShareTypeVariationShorteningStrandsSubscriptions(ConflictError):
    """Shortening (or closing) a share type variation's validity would strand
    subscription groups that are open or end after the new end date — the
    subscriptions (and their materialized shares) would outlive their
    variation. End those subscriptions first, or pick a later end date."""

    code = "share_type_variation.shortening_strands_subscriptions"

    def __init__(self, *, variation, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end variation '{variation}' on {new_valid_until}: "
            f"{stranded_count} subscription(s) are open or end after that date "
            "and would outlive their variation. End those subscriptions first.",
            details={
                "variation": str(variation),
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class SharesDeliveryDayToursReducedWhileInUse(ConflictError):
    """The number of tours on a delivery day that is already in use (it has
    deliveries / subscriptions, i.e. it is not deletable) may only be raised,
    not lowered — reducing it would strand deliveries on the removed tours."""

    code = "shares_delivery_day.tours_reduced_while_in_use"

    def __init__(self, *, current_tours, new_tours) -> None:
        super().__init__(
            f"This delivery day is in use, so the number of tours can't be "
            f"reduced from {current_tours} to {new_tours} — only increased. "
            f"Lowering it would strand deliveries on the removed tours.",
            details={"current_tours": current_tours, "new_tours": new_tours},
        )


class SharesDeliveryDayShorteningStrandsChildren(ConflictError):
    """Shortening (or closing) a delivery day's validity would strand future
    children past the new end date — DeliveryStationDays that are open or end
    later, or Shares whose delivery week falls after it. Migrate via the
    close-then-create succession flow, or pick a later end date."""

    code = "shares_delivery_day.shortening_strands_children"

    def __init__(self, *, delivery_day, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end delivery day '{delivery_day}' on {new_valid_until}: "
            f"{stranded_count} future child object(s) (station-days or shares) "
            "would outlive it. Use a succession (close-then-create) or pick a "
            "later end date.",
            details={
                "delivery_day": delivery_day,
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class SharesDeliveryDayStartMoveStrandsChildren(ConflictError):
    """Moving a delivery day's ``valid_from`` LATER would leave children before
    the new start with no day covering them — DeliveryStationDays that begin
    earlier, or Shares whose delivery week falls before it. The children stay
    pointed at this day, so nothing re-homes them; pick an earlier start or
    migrate them first."""

    code = "shares_delivery_day.start_move_strands_children"

    def __init__(self, *, delivery_day, new_valid_from, stranded_count) -> None:
        super().__init__(
            f"Cannot start delivery day '{delivery_day}' on {new_valid_from}: "
            f"{stranded_count} existing child object(s) (station-days or shares) "
            "fall before that date and would be left uncovered. Pick an earlier "
            "start date, or move those children first.",
            details={
                "delivery_day": delivery_day,
                "new_valid_from": str(new_valid_from),
                "stranded_count": stranded_count,
            },
        )


class SharesDeliveryDaySuccessionCoverageGap(ConflictError):
    """A delivery-day succession can't remap a future ShareDelivery because the
    station has no DeliveryStationDay covering that week on the new day. Leaving
    the delivery on the closed old day would violate the Share/ShareDelivery
    day-match invariant — configure the station-day for the new day first, then
    retry the succession."""

    code = "shares_delivery_day.succession_coverage_gap"

    def __init__(self, *, station_id, day_number, week_monday) -> None:
        super().__init__(
            f"Cannot complete the delivery-day succession: station {station_id} "
            f"has no station-day for day {day_number} covering the week of "
            f"{week_monday}. Configure that station-day first, then retry.",
            details={
                "station_id": str(station_id),
                "day_number": day_number,
                "week_monday": str(week_monday),
            },
        )


class DeliveryStationDayShorteningStrandsChildren(ConflictError):
    """Shortening (or closing) a station-day's validity via a direct edit would
    strand its future children past the new end — ShareDeliveries or
    CapacityReservations whose delivery week falls after it. Create a successor
    station-day instead (which migrates them), or pick a later end date."""

    code = "delivery_station_day.shortening_strands_children"

    def __init__(self, *, station_day, new_valid_until, stranded_count) -> None:
        super().__init__(
            f"Cannot end station-day '{station_day}' on {new_valid_until}: "
            f"{stranded_count} future delivery/reservation(s) would outlive it. "
            "Create a successor station-day (which migrates them) or pick a later "
            "end date.",
            details={
                "station_day": station_day,
                "new_valid_until": str(new_valid_until),
                "stranded_count": stranded_count,
            },
        )


class DeliveryStationDayStartMoveStrandsChildren(ConflictError):
    """Moving a station-day's ``valid_from`` LATER would leave children before
    the new start with no station-day covering them — ShareDeliveries or
    CapacityReservations whose delivery week falls before it. They keep pointing
    at this row, so nothing re-homes them; pick an earlier start date."""

    code = "delivery_station_day.start_move_strands_children"

    def __init__(self, *, station_day, new_valid_from, stranded_count) -> None:
        super().__init__(
            f"Cannot start station-day '{station_day}' on {new_valid_from}: "
            f"{stranded_count} existing delivery/reservation(s) fall before that "
            "date and would be left uncovered. Pick an earlier start date, or "
            "move them first.",
            details={
                "station_day": station_day,
                "new_valid_from": str(new_valid_from),
                "stranded_count": stranded_count,
            },
        )


class DeliveryStationDayStartsBeforeDeliveryDay(ConflictError):
    """A station-day's ``valid_from`` would fall before the ``valid_from`` of the
    SharesDeliveryDay row it hangs off. The station-day would then be active on
    weeks its delivery day does not cover, and the no-overlap check is scoped to
    (station, delivery_day) — so a row reaching back past its own day can shadow
    a sibling sitting on an OLDER delivery-day row without tripping it."""

    code = "delivery_station_day.starts_before_delivery_day"

    def __init__(
        self, *, station_day, new_valid_from, delivery_day, delivery_day_valid_from
    ) -> None:
        super().__init__(
            f"Cannot start station-day '{station_day}' on {new_valid_from}: its "
            f"delivery day '{delivery_day}' only starts on "
            f"{delivery_day_valid_from}. Move the delivery day's start first, or "
            "pick a start on or after it.",
            details={
                "station_day": station_day,
                "new_valid_from": str(new_valid_from),
                "delivery_day": delivery_day,
                "delivery_day_valid_from": str(delivery_day_valid_from),
            },
        )
