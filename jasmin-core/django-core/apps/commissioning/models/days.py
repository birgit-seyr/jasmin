from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from .base import JasminModel
from .choices_text import DayNumberOptions
from .mixin import TimeBoundMixin, time_bound_valid_range_constraint


# delivery days of the week for shares (delivery days for orders for resellers might be different)
class SharesDeliveryDay(JasminModel, TimeBoundMixin):
    overlap_unique_fields = ("day_number",)

    day_number = models.PositiveSmallIntegerField(choices=DayNumberOptions.choices)
    default_packing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_harvesting_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_washing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_cleaning_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_get_current_stock_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )  # for getting current amounts of shares / Bestand
    name = models.CharField(max_length=200, blank=True, null=True)
    number_of_tours = models.IntegerField(
        default=1, blank=True, null=True
    )  # if there are more than one tour per day, we need to know
    acronym = models.CharField(max_length=4, blank=True, null=True)

    class Meta:
        constraints = [
            # Only one currently-active row per day_number (mirrors
            # DeliveryStationDay's open-row partial-unique). The whole
            # day-number resolution chain — delivery_utils.get_shares_delivery_day
            # and shares_delivery_day_service's predecessor pick — assumes
            # exactly one open SharesDeliveryDay per day_number; this turns the
            # unlocked TOCTOU on the create path into a hard IntegrityError on a
            # second open row, so .first()-style resolution is unambiguous.
            # Historical / closed-out rows (valid_until set) may still exist.
            models.UniqueConstraint(
                fields=["day_number"],
                condition=Q(valid_until__isnull=True),
                name="sharesdeliveryday_one_open_per_day_number",
            ),
            time_bound_valid_range_constraint("sharesdeliveryday_valid_range"),
        ]

    def __str__(self) -> str:
        return self.name or DayNumberOptions(self.day_number).label


class OrdersDeliveryDay(JasminModel):
    day_number = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, unique=True
    )
    default_last_possible_ordering_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_last_possible_ordering_time = models.TimeField(blank=True, null=True)
    default_packing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_harvesting_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_washing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_cleaning_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    default_get_current_stock_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )  # for getting current amounts of shares / Bestand

    acronym = models.CharField(max_length=4, blank=True, null=True)

    def __str__(self) -> str:
        return DayNumberOptions(self.day_number).label


class DeliveryStationDay(JasminModel, TimeBoundMixin):
    overlap_unique_fields = ("delivery_station", "delivery_day")

    delivery_station = models.ForeignKey("DeliveryStation", on_delete=models.CASCADE)
    delivery_day = models.ForeignKey("SharesDeliveryDay", on_delete=models.CASCADE)
    delivery_time_begin = models.TimeField(blank=True, null=True)
    delivery_time_end = models.TimeField(blank=True, null=True)
    pickup_time_begin = models.TimeField(blank=True, null=True)
    pickup_time_end = models.TimeField(blank=True, null=True)
    additional_pickup_days = models.IntegerField(
        blank=True, null=True
    )  # this is if a following day is also a possible pickup day
    additional_pickup_time_begin_1 = models.TimeField(blank=True, null=True)
    additional_pickup_time_end_1 = models.TimeField(blank=True, null=True)
    additional_pickup_time_begin_2 = models.TimeField(blank=True, null=True)
    additional_pickup_time_end_2 = models.TimeField(
        blank=True, null=True
    )  # more then 2 additional pickup days are unlikely
    special_instructions = models.TextField(blank=True, null=True)
    tour_number = models.PositiveIntegerField(
        default=1
    )  # which tour this object is in (tour is an integer)
    stop_order = models.PositiveIntegerField(null=True, blank=True)
    capacity = models.PositiveIntegerField(
        default=50
    )  # maximum number of shares that can be delivered to this station on this day

    class Meta:
        indexes = [
            models.Index(fields=["delivery_station", "delivery_day", "valid_from"]),
            models.Index(fields=["tour_number", "stop_order"]),
            models.Index(fields=["delivery_station", "valid_from", "valid_until"]),
        ]
        constraints = [
            # Only one currently-active row per (delivery_station, delivery_day).
            # Historical / closed-out rows (valid_until set) may still exist.
            models.UniqueConstraint(
                fields=["delivery_station", "delivery_day"],
                condition=Q(valid_until__isnull=True),
                name="deliverystationday_unique_active_per_station_day",
            ),
            time_bound_valid_range_constraint("deliverystationday_valid_range"),
        ]

    def __str__(self) -> str:
        return f"{self.delivery_station} - {self.delivery_day} - {self.valid_from} - {self.valid_until}"

    def clean(self) -> None:
        super().clean()
        self.validate_time_ranges(
            delivery_time_begin=self.delivery_time_begin,
            delivery_time_end=self.delivery_time_end,
            pickup_time_begin=self.pickup_time_begin,
            pickup_time_end=self.pickup_time_end,
            additional_pickup_time_begin_1=self.additional_pickup_time_begin_1,
            additional_pickup_time_end_1=self.additional_pickup_time_end_1,
            additional_pickup_time_begin_2=self.additional_pickup_time_begin_2,
            additional_pickup_time_end_2=self.additional_pickup_time_end_2,
        )

    @staticmethod
    def validate_time_ranges(
        *,
        delivery_time_begin=None,
        delivery_time_end=None,
        pickup_time_begin=None,
        pickup_time_end=None,
        additional_pickup_time_begin_1=None,
        additional_pickup_time_end_1=None,
        additional_pickup_time_begin_2=None,
        additional_pickup_time_end_2=None,
    ) -> None:
        """Validate that all time ranges have end > begin.

        Exposed as a staticmethod so service-layer bulk operations can call
        the same logic that ``clean()`` uses.
        """
        if delivery_time_begin and delivery_time_end:
            if delivery_time_end <= delivery_time_begin:
                raise ValidationError(
                    {"delivery_time_end": "Delivery end time must be after begin time"}
                )

        if pickup_time_begin and pickup_time_end:
            if pickup_time_end <= pickup_time_begin:
                raise ValidationError(
                    {"pickup_time_end": "Pickup end time must be after begin time"}
                )

        if additional_pickup_time_begin_1 and additional_pickup_time_end_1:
            if additional_pickup_time_end_1 <= additional_pickup_time_begin_1:
                raise ValidationError(
                    {
                        "additional_pickup_time_end_1": "End time must be after begin time"
                    }
                )

        if additional_pickup_time_begin_2 and additional_pickup_time_end_2:
            if additional_pickup_time_end_2 <= additional_pickup_time_begin_2:
                raise ValidationError(
                    {
                        "additional_pickup_time_end_2": "End time must be after begin time"
                    }
                )

    def get_occupied_capacity(self, year: int, delivery_week: int) -> int:
        """Count how many shares occupy this station-day.

        Only STANDALONE (non-additional) shares occupy a pickup slot — an
        additional share (``is_additional_share_type``) is packed into another
        share's box and takes no capacity. Routed through
        :class:`ShareDemandService` so the value is correct for both
        subscription-driven tenants and tenants whose demand is sourced from
        the weekly CSV import.

        Feeds both the office UI's "X / Y full" indicator and hard
        enforcement: :class:`apps.commissioning.services.
        capacity_reservation_service.CapacityReservationService` reserves a
        slot at draft/order time under a ``select_for_update`` row lock on
        this DeliveryStationDay (race-safe check-then-insert), and
        ``DeliveryStationDaySerializer.validate_capacity`` floors a manual
        capacity edit at the busiest upcoming week's occupancy.
        """
        from ..services.share_demand_service import ShareDemandService

        return ShareDemandService.share_option_capacity_count(
            delivery_station_day_id=self.id,
            year=year,
            delivery_week=delivery_week,
        )


class CapacityReservation(JasminModel):
    """A draft subscription's hold on one ``DeliveryStationDay`` slot for a
    single ``(year, week)``.

    Capacity is reserved when a subscription is ordered/drafted — BEFORE its
    ``ShareDelivery`` rows are materialised at admin-confirm — so two members
    can't both grab the last slot and then both fail at confirm. Occupancy is
    therefore ``confirmed ShareDeliveries + active reservations``
    (:class:`apps.commissioning.services.share_demand_service.
    SubscriptionDemandBackend`).

    Lifecycle:
      * created at order/draft save (race-safe under a row lock),
      * deleted at confirm (the ShareDelivery now holds the slot — no double
        count),
      * deleted automatically on reject/delete via ``on_delete=CASCADE``.

    "Active" is purely ``expires_at > now`` — expiry is automatic in the read
    path, so no job is needed for correctness; a periodic sweep only prunes
    dead rows. Only created for harvest-share subscriptions (the share options
    capacity actually counts).
    """

    delivery_station_day = models.ForeignKey(
        "DeliveryStationDay", on_delete=models.CASCADE, related_name="reservations"
    )
    subscription = models.ForeignKey(
        "Subscription", on_delete=models.CASCADE, related_name="capacity_reservations"
    )
    year = models.PositiveSmallIntegerField()
    week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "delivery_station_day", "year", "week"],
                name="capres_unique_sub_dsd_week",
            ),
        ]
        indexes = [
            # Drives the occupancy count: active reservations per (dsd, week).
            models.Index(
                fields=["delivery_station_day", "year", "week", "expires_at"],
                name="capres_dsd_week_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Reservation {self.delivery_station_day_id} "
            f"W{self.week}/{self.year} (sub {self.subscription_id})"
        )
