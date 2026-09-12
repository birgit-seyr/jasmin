from __future__ import annotations

import datetime

from django.db import models
from django.utils import timezone

from .base import JasminModel
from .choices import PaymentCycleOptions
from .mixin import TimeBoundMixin, time_bound_valid_range_constraint


class DeliveryStation(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    short_name = models.CharField(max_length=100, blank=True, null=True)
    contact = models.ForeignKey(
        "ContactEntity", on_delete=models.SET_NULL, blank=True, null=True
    )

    number = models.PositiveIntegerField(blank=True, null=True, unique=True)

    is_also_reseller = models.BooleanField(default=False)
    is_also_seller = models.BooleanField(default=False)
    linked_reseller = models.OneToOneField(
        "Reseller",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        # Reverse accessor: ``reseller.linked_delivery_station`` (single source
        # of truth for the link — there is no separate FK on ``Reseller``).
        related_name="linked_delivery_station",
    )

    info = models.CharField(max_length=1024, blank=True, null=True)
    access_code = models.CharField(max_length=100, blank=True, null=True)
    messenger_group_link = models.CharField(max_length=150, blank=True, null=True)
    contact_name = models.CharField(max_length=150, blank=True, null=True)
    contact_phone = models.CharField(max_length=50, blank=True, null=True)
    # An uploaded photo of the pickup spot. ``photo_link`` stays for stations
    # that prefer to point at an external URL instead.
    picture = models.FileField(
        blank=True, null=True, upload_to="pictures_delivery_station"
    )
    photo_link = models.CharField(max_length=512, blank=True, null=True)

    self_service = models.BooleanField(default=False)
    # Station fees the solawi owes the pickup station, NET (no VAT). DecimalField
    # (not Integer) per the repo money/Decimal hygiene rule — keeps cents and
    # stays Decimal end-to-end into the billing. Either/or: at most one of the
    # three is set per station.
    fee_per_box_net = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    fee_per_month_net = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    fee_per_year_net = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    fees_billing_period = models.CharField(
        max_length=20, choices=PaymentCycleOptions.choices, blank=True, null=True
    )

    class Meta:
        constraints = [
            # One DeliveryStation per ContactEntity — the
            # ``get_or_create(contact=…)`` / ``.get(contact=…)`` callers assume
            # 1:1. The constraint turns a concurrent ``get_or_create`` race into
            # a catchable IntegrityError (re-fetched) instead of duplicate rows
            # that later blow up ``.get(contact=…)`` with MultipleObjectsReturned.
            models.UniqueConstraint(
                fields=["contact"],
                condition=models.Q(contact__isnull=False),
                name="delivery_station_unique_contact",
            ),
        ]

    def __str__(self) -> str:
        if self.short_name:
            name = self.short_name
        elif self.contact:
            name = self.contact.name
        else:
            name = "Unnamed"
        return f"{name} (#{self.number or 'N/A'})"


class DeliveryExceptionPeriod(JasminModel, TimeBoundMixin):
    """A "Lieferpause": a whole-week range ``[valid_from (Monday) … valid_until
    (Sunday)]`` during which a share-type variation is NOT delivered.

    No ``ShareDelivery`` rows are materialised for the variation's confirmed
    subscriptions in those weeks — so there is no production demand and (since
    billing is driven off ShareDeliveries) no billing either. Creating, editing
    or deleting a period resyncs the affected confirmed subscriptions'
    deliveries in the window and recomputes (see
    ``services.delivery_exceptions``).

    ``overlap_unique_fields=("share_type_variation",)`` keeps two periods for the
    same variation from overlapping in time (a variation can still have several
    non-overlapping pauses — summer + winter, say).
    """

    overlap_unique_fields = ("share_type_variation",)

    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.CASCADE
    )
    note = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        constraints = [
            time_bound_valid_range_constraint("deliveryexceptionperiod_valid_range"),
        ]

    def __str__(self) -> str:
        return f"{self.share_type_variation}: {self.valid_from} to {self.valid_until}"

    def has_started(self, on: datetime.date | None = None) -> bool:
        """True once the pause has begun (``valid_from <= today``), i.e. it is
        active or already past. Such a period is FROZEN: its deliveries/billing
        for the started portion already stand, so it may not be edited or
        deleted (only future, not-yet-started pauses are mutable)."""
        today = on or timezone.localdate()
        return self.valid_from is not None and self.valid_from <= today
