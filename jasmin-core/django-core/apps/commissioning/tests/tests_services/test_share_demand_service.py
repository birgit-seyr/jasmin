"""Tests for :class:`ShareDemandService` (the hexagonal façade) and its two
backends.

The service routes every "how many share_type_variations do we need" call
to one of:

* :class:`SubscriptionDemandBackend` — derived from ``ShareDelivery`` /
  ``Subscription`` rows (the historical behaviour).
* :class:`ExternalDemandBackend` — reads the CSV-imported
  ``ExternalShareDemand`` table.

The dispatcher picks one based on
``TenantSettings.uploads_weekly_share_amount``. We bypass settings here by
patching the dispatcher directly: the backends are pure objects and easier
to exercise in isolation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.commissioning.models import ExternalShareDemand
from apps.commissioning.services.share_demand_service import (
    ExternalDemandBackend,
    ShareDemandService,
    SubscriptionDemandBackend,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_subscription_delivery(
    *,
    variation,
    delivery_day,
    station_day,
    year=2026,
    delivery_week=15,
    quantity=2,
    joker_taken=False,
):
    """Create one ``ShareDelivery`` linked to a real subscription."""
    from apps.commissioning.models import Share

    member = MemberFactory()
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        payment_cycle=PaymentCycleFactory(),
        default_delivery_station_day=station_day,
        quantity=quantity,
    )
    share, _ = Share.objects.get_or_create(
        year=year,
        delivery_week=delivery_week,
        delivery_day=delivery_day,
        share_type_variation=variation,
    )
    delivery = ShareDeliveryFactory(
        share=share,
        delivery_station_day=station_day,
        joker_taken=joker_taken,
    )
    delivery.subscription = subscription
    delivery.save()
    return share, delivery


def _make_external_demand(
    *,
    batch,
    variation,
    station_day,
    year=2026,
    delivery_week=15,
    quantity=5,
):
    return ExternalShareDemand.objects.create(
        batch=batch,
        year=year,
        delivery_week=delivery_week,
        delivery_station_day=station_day,
        share_type_variation=variation,
        quantity=quantity,
    )


def _make_import_batch(year=2026, delivery_week=15):
    """Minimal applied import batch — needed as FK target for
    ``ExternalShareDemand.batch``."""
    from apps.commissioning.models import ShareImportBatch

    return ShareImportBatch.objects.create(
        year=year,
        delivery_week=delivery_week,
        file_checksum="0" * 64,
        original_filename="seed.csv",
        status=ShareImportBatch.STATUS_APPLIED,
    )


# ---------------------------------------------------------------------------
# SubscriptionDemandBackend
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubscriptionDemandBackend:
    def test_quantity_for_share_sums_subscription_quantity(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day, tour_number=1)
        share, _ = _make_subscription_delivery(
            variation=variation, delivery_day=day, station_day=sd, quantity=3
        )

        backend = SubscriptionDemandBackend()
        assert backend.quantity_for_share(share) == 3

    def test_quantity_for_share_excludes_opted_out_on_off(self, tenant):
        """On-off (``requires_optin``) deliveries the member opted OUT of do
        not ship, so they must not count as demand — mirrors the billing
        rule in apps/payments/services.py."""
        variation = ShareTypeVariationFactory(
            requires_optin=True, default_optin_state=False
        )
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day, tour_number=1)

        # Same share, two members: one opted out (default_optin_state=False
        # stamps is_opted_in=False on insert), one toggled opted in.
        share, opted_out = _make_subscription_delivery(
            variation=variation, delivery_day=day, station_day=sd, quantity=5
        )
        assert opted_out.is_opted_in is False

        _, opted_in = _make_subscription_delivery(
            variation=variation, delivery_day=day, station_day=sd, quantity=3
        )
        opted_in.is_opted_in = True
        opted_in.save(update_fields=["is_opted_in"])

        backend = SubscriptionDemandBackend()
        assert backend.quantity_for_share(share) == 3

    def test_aggregated_rows_excludes_opted_out_on_off(self, tenant):
        variation = ShareTypeVariationFactory(
            requires_optin=True, default_optin_state=False
        )
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day, tour_number=1)

        _make_subscription_delivery(
            variation=variation, delivery_day=day, station_day=sd, quantity=4
        )  # opted out
        _, opted_in = _make_subscription_delivery(
            variation=variation, delivery_day=day, station_day=sd, quantity=2
        )
        opted_in.is_opted_in = True
        opted_in.save(update_fields=["is_opted_in"])

        rows = SubscriptionDemandBackend().aggregated_rows(year=2026, delivery_week=15)
        assert sum(r["count"] for r in rows) == 2

    def test_aggregated_rows_excludes_joker_by_default(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day, tour_number=1)
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd,
            quantity=2,
        )
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd,
            quantity=99,
            joker_taken=True,
        )

        backend = SubscriptionDemandBackend()
        rows = backend.aggregated_rows(year=2026, delivery_week=15)
        assert sum(r["count"] for r in rows) == 2

    def test_aggregated_rows_can_include_only_jokers(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day, tour_number=1)
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd,
            quantity=2,
        )
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd,
            quantity=7,
            joker_taken=True,
        )

        rows = SubscriptionDemandBackend().aggregated_rows(
            year=2026, delivery_week=15, joker=True
        )
        assert sum(r["count"] for r in rows) == 7

    def test_aggregated_rows_filters_by_station(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        st_a = DeliveryStationFactory()
        st_b = DeliveryStationFactory()
        sd_a = DeliveryStationDayFactory(
            delivery_day=day, delivery_station=st_a, tour_number=1
        )
        sd_b = DeliveryStationDayFactory(
            delivery_day=day, delivery_station=st_b, tour_number=2
        )
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd_a,
            quantity=4,
        )
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd_b,
            quantity=6,
        )

        rows = SubscriptionDemandBackend().aggregated_rows(
            year=2026, delivery_week=15, delivery_station_id=st_a.id
        )
        assert sum(r["count"] for r in rows) == 4

    def test_share_option_capacity_count_sums_subscription_quantity(self, tenant):
        share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
        variation = ShareTypeVariationFactory(share_type=share_type)
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day)
        # Capacity is in SHARES (COR-15): two deliveries from subscriptions of
        # quantity 3 and 5 occupy 3+5=8 slots — NOT 2 rows. The old method
        # counted rows, letting a capped station-day overfill with multi-
        # quantity subscriptions.
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd,
            quantity=3,
        )
        _make_subscription_delivery(
            variation=variation,
            delivery_day=day,
            station_day=sd,
            quantity=5,
        )

        n = SubscriptionDemandBackend().share_option_capacity_count(
            delivery_station_day_id=sd.id,
            year=2026,
            delivery_week=15,
            share_options=["HARVEST_SHARE", "HARVEST_SHARE_FRUITS_ONLY"],
        )
        assert n == 8


# ---------------------------------------------------------------------------
# ExternalDemandBackend
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExternalDemandBackend:
    def test_quantity_for_share_sums_external_rows(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=day,
            share_type_variation=variation,
        )
        batch = _make_import_batch()
        _make_external_demand(
            batch=batch, variation=variation, station_day=sd, quantity=8
        )

        assert ExternalDemandBackend().quantity_for_share(share) == 8

    def test_aggregated_rows_groups_by_station_day(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd1 = DeliveryStationDayFactory(delivery_day=day, tour_number=1)
        sd2 = DeliveryStationDayFactory(delivery_day=day, tour_number=2)
        batch = _make_import_batch()
        _make_external_demand(
            batch=batch, variation=variation, station_day=sd1, quantity=3
        )
        _make_external_demand(
            batch=batch, variation=variation, station_day=sd2, quantity=4
        )

        rows = ExternalDemandBackend().aggregated_rows(year=2026, delivery_week=15)
        totals = {r["station_day_id"]: r["count"] for r in rows}
        assert totals[sd1.id] == 3
        assert totals[sd2.id] == 4
        # Tour numbers come through from DeliveryStationDay.
        tour_numbers = {r["station_day_id"]: r["tour_number"] for r in rows}
        assert tour_numbers[sd1.id] == 1
        assert tour_numbers[sd2.id] == 2

    def test_aggregated_rows_joker_true_returns_empty(self, tenant):
        # CSV demand has no concept of "joker" — asking for "only jokers"
        # must always be empty.
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day)
        batch = _make_import_batch()
        _make_external_demand(
            batch=batch, variation=variation, station_day=sd, quantity=3
        )

        rows = ExternalDemandBackend().aggregated_rows(
            year=2026, delivery_week=15, joker=True
        )
        assert rows == []

    def test_share_option_capacity_count_sums_quantities(self, tenant):
        share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
        variation = ShareTypeVariationFactory(share_type=share_type)
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day)
        batch = _make_import_batch()
        _make_external_demand(
            batch=batch, variation=variation, station_day=sd, quantity=5
        )

        n = ExternalDemandBackend().share_option_capacity_count(
            delivery_station_day_id=sd.id,
            year=2026,
            delivery_week=15,
            share_options=["HARVEST_SHARE", "HARVEST_SHARE_FRUITS_ONLY"],
        )
        # CSV stores quantity directly, so capacity == sum(quantity) (5),
        # not the row count.
        assert n == 5


# ---------------------------------------------------------------------------
# Dispatcher / façade
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestShareDemandServiceDispatcher:
    def test_facade_delegates_to_subscription_backend_by_default(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day, tour_number=1)
        share, _ = _make_subscription_delivery(
            variation=variation, delivery_day=day, station_day=sd, quantity=3
        )

        # No ExternalShareDemand rows -> with default settings we must use
        # the subscription backend.
        assert ShareDemandService.quantity_for_share(share) == 3

    def test_facade_delegates_to_external_backend_when_flag_on(self, tenant):
        variation = ShareTypeVariationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        sd = DeliveryStationDayFactory(delivery_day=day)
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=day,
            share_type_variation=variation,
        )
        batch = _make_import_batch()
        _make_external_demand(
            batch=batch, variation=variation, station_day=sd, quantity=11
        )

        with patch(
            "apps.commissioning.services.share_demand_service._resolve_backend",
            return_value=ExternalDemandBackend(),
        ):
            assert ShareDemandService.quantity_for_share(share) == 11

    def test_resolve_backend_falls_back_to_schema_name(self, tenant):
        # TEN-1: on the Huey worker, connection.tenant under schema_context is a
        # FakeTenant (not a Tenant model), so get_current_settings(FakeTenant)
        # matches nothing and the backend silently wrongly falls back to
        # subscriptions. _resolve_backend must resolve the real Tenant by
        # schema_name instead. Simulate the non-Tenant connection.tenant.
        import datetime

        from django.db import connection
        from django.utils import timezone

        from apps.commissioning.services.share_demand_service import (
            _resolve_backend,
        )
        from apps.shared.tenants.models import Tenant, TenantSettings

        real = Tenant.objects.get(schema_name=connection.schema_name)
        current = TenantSettings.get_current_settings(real)
        if current:
            current.uploads_weekly_share_amount = True
            current.save(update_fields=["uploads_weekly_share_amount"])
        else:
            TenantSettings.objects.create(
                tenant=real,
                valid_from=timezone.now() - datetime.timedelta(days=1),
                uploads_weekly_share_amount=True,
            )

        class _NotATenant:
            schema_name = connection.schema_name

        original = connection.tenant
        try:
            connection.tenant = _NotATenant()
            backend = _resolve_backend()
        finally:
            connection.tenant = original

        # With the fix, the real tenant's uploads_weekly_share_amount=True is
        # found via schema_name → external backend (old code returned the
        # subscription backend here).
        assert isinstance(backend, ExternalDemandBackend)


# ---------------------------------------------------------------------------
# Virtual-variation asymmetry locks (demand decomposes; capacity does NOT)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVirtualVariationShipPredicateAndCapacity:
    def _virtual_setup(self, *, requires_optin=False, default_optin_state=False):
        """A virtual variation composed of two physical components (qty 2 + 3)."""
        from apps.commissioning.tests.factories import (
            VirtualVariationComponentFactory,
        )

        share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
        virtual = ShareTypeVariationFactory(
            share_type=share_type,
            variation_type="virtual",
            requires_optin=requires_optin,
            default_optin_state=default_optin_state,
        )
        physical_a = ShareTypeVariationFactory(
            share_type=share_type, variation_type="physical", size="S"
        )
        physical_b = ShareTypeVariationFactory(
            share_type=share_type, variation_type="physical", size="L"
        )
        VirtualVariationComponentFactory(
            virtual_variation=virtual, physical_variation=physical_a, quantity=2
        )
        VirtualVariationComponentFactory(
            virtual_variation=virtual, physical_variation=physical_b, quantity=3
        )
        return virtual, physical_a, physical_b

    def test_opted_out_virtual_delivery_contributes_zero_to_physical_totals(
        self, tenant
    ):
        # The ship predicate runs on the SOURCE rows BEFORE the virtual→physical
        # distribution, so an opted-out on-off virtual delivery must contribute
        # nothing to its physical components. (The flat aggregation is covered
        # elsewhere; this locks the virtual-DISTRIBUTION path.)
        from apps.commissioning.utils.share_type_variation_amounts import (
            batch_get_physical_variation_totals_for_weeks,
        )

        virtual, physical_a, physical_b = self._virtual_setup(
            requires_optin=True, default_optin_state=False
        )
        day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=day)
        _, delivery = _make_subscription_delivery(
            variation=virtual, delivery_day=day, station_day=station_day, quantity=1
        )
        assert delivery.is_opted_in is False  # seeded from default_optin_state

        totals_by_week = batch_get_physical_variation_totals_for_weeks(
            [physical_a, physical_b], 2026, [15]
        )
        week_totals = totals_by_week[15]
        basic = week_totals.get("basic", {})
        assert all(total == 0 for total in basic.values()) or not basic

        # Opting IN makes the same delivery count — decomposed by component
        # quantity onto each physical variation.
        delivery.is_opted_in = True
        delivery.save(update_fields=["is_opted_in"])

        totals_by_week = batch_get_physical_variation_totals_for_weeks(
            [physical_a, physical_b], 2026, [15]
        )
        basic = totals_by_week[15]["basic"]
        by_variation = {
            variation_id: total for (_day_id, variation_id), total in basic.items()
        }
        assert by_variation.get(physical_a.id) == 2
        assert by_variation.get(physical_b.id) == 3

    def test_capacity_counts_virtual_delivery_as_one_slot_not_decomposed(self, tenant):
        # Capacity is pickup SLOTS at the station-day: a virtual subscription
        # occupies quantity slots, NOT quantity × Σ(component quantities).
        # This asymmetry vs. the demand path above is deliberate and
        # load-bearing — a refactor that "unifies" the two paths through the
        # decomposition helper would falsely reject new subscribers.
        virtual, _physical_a, _physical_b = self._virtual_setup()
        day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=day)
        _make_subscription_delivery(
            variation=virtual, delivery_day=day, station_day=station_day, quantity=4
        )

        n = SubscriptionDemandBackend().share_option_capacity_count(
            delivery_station_day_id=station_day.id,
            year=2026,
            delivery_week=15,
            share_options=["HARVEST_SHARE", "HARVEST_SHARE_FRUITS_ONLY"],
        )
        # 4 slots (subscription quantity), not 4 × (2+3) = 20.
        assert n == 4
