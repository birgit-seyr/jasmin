"""Seed the commissioning set-up the Playwright suite's office flows book into.

Runs inside one tenant schema; ``seed_e2e`` calls it for the ``e2e`` tenant:

    python manage.py tenant_command seed_e2e_commissioning --schema=e2e

Creates (or leaves as they are) one share type with one variation and a price,
one delivery day and one delivery station that delivers on it, and lets a
subscription start next week for a member without cooperative shares.
Capacities are far above what any number of runs books, because every run adds
a subscription and none is ever removed.

Idempotent: each row is looked up by its name before it is created.

Dev only: refuses to run when ``DEBUG`` is False.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.commissioning.models import (
    DeliveryStation,
    DeliveryStationDay,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
)
from apps.shared.tenants.models import TenantSettings
from core.tenant_db import connection

# A Monday in the past, so every row is valid in every week a test books.
VALID_FROM = date(2026, 1, 5)
SHARE_TYPE_NAME = "E2E vegetables"
STATION_NAME = "E2E station"
CAPACITY = 1_000_000


class Command(BaseCommand):
    help = "Seed one share type, delivery day and station for the E2E suite."

    def handle(self, *args: Any, **opts: Any) -> None:
        if not settings.DEBUG:
            raise CommandError(
                "seed_e2e_commissioning is a development helper and refuses to "
                "run with DEBUG=False."
            )
        with transaction.atomic():
            variation = self._share_type_variation()
            station_day = self._station_day()
        self._relax_booking_rules()
        self.stdout.write(
            self.style.SUCCESS(
                f"variation={variation.id}  station_day={station_day.id}"
            )
        )

    def _share_type_variation(self) -> ShareTypeVariation:
        share_type, _ = ShareType.objects.get_or_create(
            name=SHARE_TYPE_NAME,
            defaults={
                "short_name": "E2E",
                "valid_from": VALID_FROM,
                "needs_complex_planning": False,
            },
        )
        variation, created = ShareTypeVariation.objects.get_or_create(
            share_type=share_type,
            size="M",
            defaults={"valid_from": VALID_FROM, "capacity": CAPACITY},
        )
        if created:
            ShareTypeVariationGrossPrice.objects.create(
                share_type_variation=variation,
                valid_from=VALID_FROM,
                price_per_delivery=Decimal("20.00"),
                tax_rate=Decimal("7.00"),
            )
        return variation

    def _station_day(self) -> DeliveryStationDay:
        delivery_day, _ = SharesDeliveryDay.objects.get_or_create(
            day_number=3,
            valid_until=None,
            defaults={"valid_from": VALID_FROM},
        )
        station, _ = DeliveryStation.objects.get_or_create(short_name=STATION_NAME)
        station_day, _ = DeliveryStationDay.objects.get_or_create(
            delivery_station=station,
            delivery_day=delivery_day,
            defaults={"valid_from": VALID_FROM, "capacity": CAPACITY},
        )
        return station_day

    def _relax_booking_rules(self) -> None:
        """Let a subscription start next week, for a member without coop shares.

        The office flows book a subscription for a member they just created;
        the default lead time (two weeks) and coop-share minimum (three) would
        each refuse its approval.
        """
        current = TenantSettings.get_current_settings(connection.tenant)
        if current is None:
            raise CommandError("The tenant has no current settings row.")
        # A plain UPDATE: the settings row is versioned, and a lead-time change
        # for a test tenant needs no new version.
        TenantSettings.objects.filter(pk=current.pk).update(
            min_weeks_from_creation_to_start_delivery=0,
            min_number_coop_shares=0,
        )
