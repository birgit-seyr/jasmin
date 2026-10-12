"""Seed the commissioning set-up the Playwright suite's office flows book into.

Runs inside one tenant schema; ``seed_e2e`` calls it for the ``e2e`` tenant:

    python manage.py tenant_command seed_e2e_commissioning --schema=e2e

Creates (or leaves as they are) one share type with one variation and a price,
one delivery day and one delivery station that delivers on it, and lets a
subscription start next week for a member without cooperative shares.
Capacities are far above what any number of runs books, because every run adds
a subscription and none is ever removed.

Also:

  * one active share article, which the reseller document flow orders, and
    order-day defaults for every delivery day (harvest, wash, clean and pack
    on the delivery day itself), without which an order can't be saved;
  * a confirmed weekly subscription for the member persona, so the member
    sees the member page (not the "application under review" gate) and a
    payment plan with upcoming charges. A new one starts next Monday whenever
    the persona has none that still runs for another four weeks, so the plan
    never runs out.

Idempotent: each row is looked up by its name before it is created.

Dev only: refuses to run when ``DEBUG`` is False.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.commissioning.models import (
    DeliveryStation,
    DeliveryStationDay,
    Member,
    OrdersDeliveryDay,
    PaymentCycle,
    ShareArticle,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
    Subscription,
)
from apps.commissioning.models.choices import (
    DayNumberOptions,
    PaymentCycleOptions,
    UnitOptions,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.shared.tenants.models import TenantSettings
from core.tenant_db import connection

# A Monday in the past, so every row is valid in every week a test books.
VALID_FROM = date(2026, 1, 5)
SHARE_TYPE_NAME = "E2E vegetables"
STATION_NAME = "E2E station"
SHARE_ARTICLE_NAME = "E2E carrots"
CAPACITY = 1_000_000
PRICE_PER_DELIVERY = Decimal("20.00")
MEMBER_PERSONA_EMAIL = "test-member@example.com"
ADMIN_PERSONA_EMAIL = "test-admin@example.com"
MEMBER_SUBSCRIPTION_WEEKS = 26
# A subscription ending sooner than this is replaced by a new one.
MEMBER_SUBSCRIPTION_MIN_WEEKS_LEFT = 4


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
            self._share_article()
            self._orders_delivery_days()
        self._relax_booking_rules()
        with transaction.atomic():
            subscription = self._member_persona_subscription(variation, station_day)
        self.stdout.write(
            self.style.SUCCESS(
                f"variation={variation.id}  station_day={station_day.id}  "
                f"member_subscription={subscription.id}"
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
                price_per_delivery=PRICE_PER_DELIVERY,
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

    def _share_article(self) -> ShareArticle:
        article, _ = ShareArticle.objects.get_or_create(
            name=SHARE_ARTICLE_NAME,
            defaults={
                "is_active": True,
                "is_sold_to_resellers": True,
                "default_movement_unit": UnitOptions.KG,
            },
        )
        return article

    def _orders_delivery_days(self) -> None:
        for day_number in DayNumberOptions.values:
            OrdersDeliveryDay.objects.get_or_create(
                day_number=day_number,
                defaults={
                    "default_harvesting_day": day_number,
                    "default_washing_day": day_number,
                    "default_cleaning_day": day_number,
                    "default_packing_day": day_number,
                },
            )

    def _member_persona_subscription(
        self, variation: ShareTypeVariation, station_day: DeliveryStationDay
    ) -> Subscription:
        """A confirmed weekly subscription for the member persona.

        Confirming it confirms the member too (member number, entry date) and
        plans its weekly charges.
        """
        member = Member.objects.filter(email=MEMBER_PERSONA_EMAIL).first()
        if member is None:
            raise CommandError(
                f"No member {MEMBER_PERSONA_EMAIL}; seed_test_users runs first."
            )
        today = timezone.localdate()
        running = (
            Subscription.objects.filter(
                member_id=member.pk,
                admin_confirmed=True,
                valid_until__gte=today
                + timedelta(weeks=MEMBER_SUBSCRIPTION_MIN_WEEKS_LEFT),
            )
            .order_by("-valid_until")
            .first()
        )
        if running is not None:
            return running

        next_monday = today + timedelta(days=7 - today.weekday())
        subscription = SubscriptionService().create_bare_subscription(
            {
                "member": member.pk,
                "share_type_variation": variation.pk,
                "valid_from": next_monday,
                "valid_until": next_monday
                + timedelta(weeks=MEMBER_SUBSCRIPTION_WEEKS, days=-1),
                "payment_cycle": PaymentCycle.objects.get(
                    choice=PaymentCycleOptions.WEEKLY
                ),
                "default_delivery_station_day": station_day,
                "quantity": 1,
                "price_per_delivery": PRICE_PER_DELIVERY,
            }
        )
        admin = get_user_model().objects.get(email=ADMIN_PERSONA_EMAIL)
        subscription.confirm(admin_user=admin)
        return subscription

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
