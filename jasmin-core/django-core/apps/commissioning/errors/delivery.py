"""Errors of delivery stations, delivery days, tours and the packing list."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

# --------------------------------------------------------------------------- #
# Delivery stations / days / tours                                            #
# --------------------------------------------------------------------------- #


class DeliveryDayNotFound(NotFoundError):
    code = "delivery_day.not_found"


class SharesDeliveryDayNotFound(NotFoundError):
    """No active SharesDeliveryDay exists for the requested day."""

    code = "shares_delivery_day.not_found"


class PictureInvalid(BadRequestError):
    """An uploaded ``picture`` (share-type variation or delivery station) is not
    a PNG/JPEG/WEBP/GIF image within the byte and pixel caps. Raised by
    ``apps.shared.image_upload.normalize_uploaded_picture`` so a non-image
    (HTML, SVG, …) can never be stored and served from the tenant origin."""

    code = "commissioning.picture_invalid"


class DeliveryStationNotFound(BadRequestError):
    """A referenced ``delivery_station_id`` does not exist — raised by the
    tour-update input serializer so a bogus id is a field-level 400 instead of
    a generic IntegrityError-derived 409 from ``update_or_create``."""

    code = "delivery_station.not_found"


class SharedStationIdentityLocked(ForbiddenError):
    """A customer self-edit tried to rewrite identity columns on a
    ``ContactEntity`` that a ``DeliveryStation`` also owns.

    One row can back both a Reseller and a pickup station
    (``ResellerAndDeliveryStationService`` does ``get_or_create(contact=…)``),
    and the station's name and address are shown to members as a physical
    collection point. Station writes are office-only, so the customer surface
    must not reach those columns through the shared row. Contact and bank
    fields on the same row stay editable."""

    code = "my_data.shared_station_identity_locked"


class DeliveryDayValidFromInPast(BadRequestError):
    """A delivery day or station-day was CREATED with a ``valid_from`` date
    before today.

    Creation only, and the boundary is today rather than the current week's
    Monday — a move on an existing row raises
    ``DeliveryDayValidFromMoveIntoPast`` instead, which is the laxer of the two.
    400 (not the 409 ``PastWeekError``): the request is malformed input — a new
    row must take effect today or later. ``field="valid_from"``.
    """

    code = "delivery_day.valid_from_in_past"


class DeliveryDayValidFromMoveIntoPast(BadRequestError):
    """An EXISTING delivery day's or station-day's ``valid_from`` was moved back
    into a week that has already been delivered and billed.

    The Monday of the current week is the earliest start such a move may land
    on. Onboarding mode lifts the rule: there the office is dating back a
    schedule that has been running on paper. Distinct from
    ``DeliveryDayValidFromInPast`` (creation, and stricter — no onboarding
    exemption, and the boundary is today), so each message can name the
    boundary its own path actually enforces. ``field="valid_from"``.
    """

    code = "delivery_day.valid_from_move_into_past"


class DeliveryExceptionInvalidRange(BadRequestError):
    """A delivery-exception ("Lieferpause") range is malformed: ``valid_from``
    is not a Monday, ``valid_until`` is not a Sunday, or the range is inverted.
    The pause covers whole delivery weeks, so its bounds must align to them.
    """

    code = "delivery_exception.invalid_range"


class DeliveryExceptionOverlap(ConflictError):
    """A delivery-exception period would overlap an existing one for the same
    ShareTypeVariation. A variation may have several pauses, but they must not
    overlap in time (409: the request is well-formed, the state forbids it).
    """

    code = "delivery_exception.overlap"


class DeliveryExceptionPeriodLocked(ConflictError):
    """A delivery-exception period that has already started (active or past) may
    not be edited or deleted — its deliveries/billing for the started portion
    already stand. Only future, not-yet-started pauses are mutable (409).
    """

    code = "delivery_exception.locked"


class DeliveryStationOverCapacity(ConflictError):
    """A delivery-station-day has no free slots for one of the weeks being
    assigned (a subscription's period week, or a single ShareDelivery's week).

    ``Conflict`` (409) rather than 400: the request is well-formed, but the
    resource state (the station-day is full for that week) prevents it. The
    frontend greys out full station-days, so this is the race-time backstop
    when two saves target the last slot — the second gets this.
    """

    code = "delivery_station.over_capacity"

    def __init__(
        self,
        *,
        station_day_id: str,
        year: int,
        week: int,
        capacity: int | None = None,
        occupied: int | None = None,
    ) -> None:
        super().__init__(
            f"Delivery station day {station_day_id} is full for week "
            f"{year}-{week} ({occupied}/{capacity}).",
            details={
                "station_day_id": str(station_day_id),
                "year": year,
                "week": week,
                "capacity": capacity,
                "occupied": occupied,
            },
        )


class ShareTypeVariationOverCapacity(ConflictError):
    """A share-type variation is sold out for the requested term — its
    farm-wide production cap (``ShareTypeVariation.capacity``) is exhausted.

    ``Conflict`` (409), not 400: the request is well-formed, but the state
    (the variation is full) forbids it. Twin of ``DeliveryStationOverCapacity``
    on the OTHER capacity axis — logistics (station-day) vs production
    (variation). The frontend greys out full variations from the free count; this
    is the race-time backstop when two orders target the last share.
    """

    code = "share_type_variation.over_capacity"

    def __init__(
        self,
        *,
        share_type_variation_id: str,
        capacity: int | None = None,
        occupied: int | None = None,
    ) -> None:
        super().__init__(
            f"Share type variation {share_type_variation_id} is sold out "
            f"({occupied}/{capacity}).",
            details={
                "share_type_variation_id": str(share_type_variation_id),
                "capacity": capacity,
                "occupied": occupied,
            },
        )


class WaitingListDisabled(BadRequestError):
    """The tenant has turned off the waiting list
    (``allows_waiting_list_for_subscriptions=False``), so no subscription may be
    queued and no spot offers exist. At-capacity share types are simply
    unavailable."""

    code = "waiting_list.disabled"


class WaitingListOfferNotAvailable(BadRequestError):
    """Cannot offer a freed spot for this subscription — it isn't a PENDING
    waiting-list entry (already offered, already promoted, or never queued)."""

    code = "waiting_list_offer.not_available"


class WaitingListOfferInvalid(NotFoundError):
    """The waiting-list offer link is invalid — no open (spot-available) offer
    matches the token (already used, declined, expired, or never existed)."""

    code = "waiting_list_offer.invalid"


class WaitingListOfferExpired(ConflictError):
    """The waiting-list offer link has expired — the member's response window
    elapsed before they accepted."""

    code = "waiting_list_offer.expired"


class WaitingListOfferMemberHasNoEmail(ConflictError):
    """The member has no email address, so the offer — a link only the email
    carries — would never reach them while the freed spot stayed on hold for
    them. Add an address to the member, then offer the spot."""

    code = "waiting_list_offer.member_has_no_email"


class DeliveryStationCapacityBelowOccupancy(BadRequestError):
    """Refuse setting a station-day's ``capacity`` below the shares already
    committed (confirmed deliveries + active draft reservations) for any week
    from the current ISO week onward. Past weeks are immutable and don't
    constrain the new value."""

    code = "delivery_station.capacity_below_occupancy"

    def __init__(
        self,
        *,
        capacity: int,
        peak: int,
        year: int | None = None,
        week: int | None = None,
    ) -> None:
        super().__init__(
            f"Cannot set capacity to {capacity}: {peak} share(s) are already "
            f"booked for week {year}-{week}.",
            field="capacity",
            details={
                "capacity": capacity,
                "peak": peak,
                "year": year,
                "week": week,
            },
        )


class DeliveryStationMoreThanOneFee(BadRequestError):
    """A station would carry more than one non-zero fee. Billing reads only the
    first of per box, per month and per year, so a station is paid one way."""

    code = "delivery_station.more_than_one_fee"


class ShareTypeVariationCapacityBelowOccupancy(BadRequestError):
    """The production-cap twin of ``DeliveryStationCapacityBelowOccupancy``: a
    variation's farm-wide ``capacity`` may not drop below the busiest
    current-or-future week's occupancy, which would push existing subscribers
    over the cap (a silent mass-waitlist). Past weeks don't constrain it."""

    code = "share_type_variation.capacity_below_occupancy"

    def __init__(self, *, capacity: int, peak: int) -> None:
        super().__init__(
            f"Cannot set capacity to {capacity}: {peak} share(s) are already "
            f"subscribed for a current or upcoming week.",
            field="capacity",
            details={"capacity": capacity, "peak": peak},
        )


# --------------------------------------------------------------------------- #
# Packing list                                                                 #
# --------------------------------------------------------------------------- #


class PackingAmountsDivergeAcrossStations(BadRequestError):
    """An all-stations packing list (no ``delivery_station`` scope) can't be
    rendered because two delivery stations carry DIFFERENT per-share amounts for
    the same (article, unit, size, variation). Collapsing them would silently
    hide one station's amount, so the caller must scope to a delivery station (or
    a tour / day where amounts are consistent — the office's granularity guard
    keeps the all-stations view to exactly those consistent cases).
    """

    code = "packing_list.amounts_diverge_across_stations"

    def __init__(
        self,
        *,
        share_article_id: str,
        unit: str,
        size: str,
        variation_id: str,
        amounts: list,
    ) -> None:
        super().__init__(
            f"Packing amounts differ across delivery stations for article "
            f"{share_article_id} ({unit}/{size}, variation {variation_id}): "
            f"{amounts}. Select a delivery station (or a tour/day where amounts "
            f"agree) to view the packing list.",
            details={
                "share_article_id": str(share_article_id),
                "unit": unit,
                "size": size,
                "variation_id": str(variation_id),
                "amounts": [str(a) for a in amounts],
            },
        )
