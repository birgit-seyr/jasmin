"""SubscriptionViewSet (office abos) — quantity / price bounds, and the
solidarity-price floor re-checked on PATCH when the variation, start date or
trial flag changes without re-sending the price.

The clock is frozen to 2026-07-20 (a Monday) so ``VALID_FROM`` (2026-09-07)
stays beyond the subscription lead time forever; the floor itself is resolved at
the subscription's start date, not today.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.models import Subscription
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory
from apps.commissioning.tests.factories.shares import (
    ShareTypeVariationGrossPriceFactory,
)
from apps.shared.tenants.models import TenantSettings

ABOS_URL = reverse("abos-list")
VALID_FROM = datetime.date(2026, 9, 7)  # Monday
LATER_VALID_FROM = datetime.date(2026, 9, 21)  # Monday
VALID_UNTIL = datetime.date(2026, 10, 4)  # Sunday
DAY_NUMBER = 2  # matches the SharesDeliveryDayFactory default


@pytest.fixture(autouse=True)
def _frozen_today():
    with time_machine.travel(datetime.datetime(2026, 7, 20, 12, 0), tick=False):
        yield


@pytest.fixture
def dsd():
    return DeliveryStationDayFactory(
        delivery_day=SharesDeliveryDayFactory(day_number=DAY_NUMBER)
    )


def _settings(tenant, **flags):
    return TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        **flags,
    )


def _variation():
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
    )


def _price_window(variation, **fields):
    return ShareTypeVariationGrossPriceFactory(share_type_variation=variation, **fields)


def _payload(variation, dsd, **overrides):
    data = {
        "member": str(MemberFactory().id),
        "share_type_variation": str(variation.id),
        "valid_from": VALID_FROM.isoformat(),
        "valid_until": VALID_UNTIL.isoformat(),
        "quantity": 1,
        "price_per_delivery": "10.00",
        "payment_cycle": str(PaymentCycleFactory().id),
        "default_delivery_station_day": str(dsd.id),
        "is_trial": False,
    }
    data.update(overrides)
    return data


def _draft(variation, dsd, *, price):
    return SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
        price_per_delivery=Decimal(price),
        admin_confirmed=False,
    )


def _detail_url(subscription):
    return reverse("abos-detail", kwargs={"pk": subscription.pk})


@pytest.mark.django_db
class TestOfficeSubscriptionBounds:
    @pytest.mark.parametrize("quantity", [0, -1])
    def test_create_rejects_quantity_below_one(self, api_client, tenant, dsd, quantity):
        resp = api_client.post(
            ABOS_URL, _payload(_variation(), dsd, quantity=quantity), format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert "quantity" in str(resp.data)
        assert not Subscription.objects.exists()

    def test_create_rejects_negative_price(self, api_client, tenant, dsd):
        resp = api_client.post(
            ABOS_URL,
            _payload(_variation(), dsd, price_per_delivery="-1.00"),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert "price_per_delivery" in str(resp.data)
        assert not Subscription.objects.exists()

    def test_patch_rejects_quantity_zero(self, api_client, tenant, dsd):
        draft = _draft(_variation(), dsd, price="10.00")
        resp = api_client.patch(_detail_url(draft), {"quantity": 0}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        draft.refresh_from_db()
        assert draft.quantity == 1

    def test_create_accepts_price_zero(self, api_client, tenant, dsd):
        resp = api_client.post(
            ABOS_URL,
            _payload(_variation(), dsd, price_per_delivery="0.00"),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert Subscription.objects.get().price_per_delivery == Decimal("0.00")

    def test_create_accepts_free_trial(self, api_client, tenant, dsd):
        _settings(tenant, allows_trial_subscriptions=True)
        resp = api_client.post(
            ABOS_URL,
            _payload(_variation(), dsd, price_per_delivery="0.00", is_trial=True),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get()
        assert subscription.is_trial is True
        assert subscription.price_per_delivery == Decimal("0.00")


@pytest.mark.django_db
class TestSolidarityFloorOnPatch:
    def test_variation_change_keeping_a_price_below_the_new_floor_is_refused(
        self, api_client, tenant, dsd
    ):
        _settings(tenant, allows_solidarity_pricing=True)
        cheap = _variation()
        _price_window(
            cheap,
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("5.00"),
        )
        expensive = _variation()
        _price_window(
            expensive,
            price_per_delivery=Decimal("20.00"),
            solidarity_min_price_per_delivery=Decimal("15.00"),
        )
        draft = _draft(cheap, dsd, price="8.00")

        resp = api_client.patch(
            _detail_url(draft),
            {"share_type_variation": str(expensive.id)},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"
        assert resp.data["details"] == {"chosen": "8.00", "minimum": "15.00"}
        draft.refresh_from_db()
        assert draft.share_type_variation_id == cheap.id

    def test_variation_change_with_a_price_at_the_new_floor_passes(
        self, api_client, tenant, dsd
    ):
        _settings(tenant, allows_solidarity_pricing=True)
        cheap = _variation()
        _price_window(cheap, solidarity_min_price_per_delivery=Decimal("5.00"))
        expensive = _variation()
        _price_window(
            expensive,
            price_per_delivery=Decimal("20.00"),
            solidarity_min_price_per_delivery=Decimal("15.00"),
        )
        draft = _draft(cheap, dsd, price="8.00")

        resp = api_client.patch(
            _detail_url(draft),
            {"share_type_variation": str(expensive.id), "price_per_delivery": "15.00"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        draft.refresh_from_db()
        assert draft.share_type_variation_id == expensive.id

    def test_start_moved_into_a_window_with_a_higher_floor_is_refused(
        self, api_client, tenant, dsd
    ):
        _settings(tenant, allows_solidarity_pricing=True)
        variation = _variation()
        _price_window(
            variation,
            valid_until=datetime.date(2026, 9, 20),  # Sunday
            solidarity_min_price_per_delivery=Decimal("5.00"),
        )
        _price_window(
            variation,
            valid_from=LATER_VALID_FROM,
            solidarity_min_price_per_delivery=Decimal("9.00"),
        )
        draft = _draft(variation, dsd, price="6.00")

        resp = api_client.patch(
            _detail_url(draft),
            {"valid_from": LATER_VALID_FROM.isoformat()},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"
        draft.refresh_from_db()
        assert draft.valid_from == VALID_FROM

    def test_turning_a_draft_into_a_trial_checks_the_trial_floor(
        self, api_client, tenant, dsd
    ):
        _settings(
            tenant, allows_solidarity_pricing=True, allows_trial_subscriptions=True
        )
        variation = _variation()
        _price_window(
            variation,
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("3.00"),
            price_per_delivery_if_trial=Decimal("8.00"),
            solidarity_min_price_per_delivery_if_trial=Decimal("7.00"),
        )
        draft = _draft(variation, dsd, price="4.00")

        resp = api_client.patch(_detail_url(draft), {"is_trial": True}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.solidarity_price_below_minimum"
        draft.refresh_from_db()
        assert draft.is_trial is False

    def test_unrelated_edit_of_a_draft_priced_below_a_later_floor_is_not_blocked(
        self, api_client, tenant, dsd
    ):
        _settings(tenant, allows_solidarity_pricing=True)
        variation = _variation()
        _price_window(variation, solidarity_min_price_per_delivery=Decimal("5.00"))
        draft = _draft(variation, dsd, price="3.00")

        resp = api_client.patch(_detail_url(draft), {"quantity": 2}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        draft.refresh_from_db()
        assert draft.quantity == 2

    def test_variation_change_without_solidarity_pricing_keeps_price_discretion(
        self, api_client, tenant, dsd
    ):
        cheap = _variation()
        _price_window(cheap)
        expensive = _variation()
        _price_window(expensive, price_per_delivery=Decimal("20.00"))
        draft = _draft(cheap, dsd, price="8.00")

        resp = api_client.patch(
            _detail_url(draft),
            {"share_type_variation": str(expensive.id)},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
