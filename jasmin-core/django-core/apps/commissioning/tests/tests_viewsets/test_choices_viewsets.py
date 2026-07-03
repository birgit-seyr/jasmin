"""Tests for choices_models_viewsets.py — SharesDeliveryDay, OrdersDeliveryDay, PaymentCycle."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    OrdersDeliveryDayFactory,
    PaymentCycleFactory,
    SharesDeliveryDayFactory,
    SubscriptionFactory,
)


# ---------------------------------------------------------------------------
# SharesDeliveryDayViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSharesDeliveryDayViewSet:
    URL = reverse("share_delivery_day-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_days(self, api_client, tenant):
        SharesDeliveryDayFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_retrieve_day(self, api_client, tenant):
        dd = SharesDeliveryDayFactory()
        url = reverse("share_delivery_day-detail", kwargs={"pk": dd.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK

    def _in_use_day(self, number_of_tours, day_number):
        # A delivery day a subscription references is "in use" (not deletable).
        day = SharesDeliveryDayFactory(
            number_of_tours=number_of_tours, day_number=day_number
        )
        SubscriptionFactory(
            default_delivery_station_day=DeliveryStationDayFactory(delivery_day=day)
        )
        return day

    def test_in_use_day_cannot_reduce_tours(self, api_client, tenant):
        day = self._in_use_day(number_of_tours=3, day_number=1)
        url = reverse("share_delivery_day-detail", kwargs={"pk": day.pk})
        resp = api_client.patch(url, {"number_of_tours": 2}, format="json")
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "shares_delivery_day.tours_reduced_while_in_use"

    def test_in_use_day_can_raise_tours(self, api_client, tenant):
        day = self._in_use_day(number_of_tours=3, day_number=1)
        url = reverse("share_delivery_day-detail", kwargs={"pk": day.pk})
        resp = api_client.patch(url, {"number_of_tours": 4}, format="json")
        assert resp.status_code == status.HTTP_200_OK

    def test_unused_day_can_reduce_tours(self, api_client, tenant):
        day = SharesDeliveryDayFactory(number_of_tours=3, day_number=2)
        url = reverse("share_delivery_day-detail", kwargs={"pk": day.pk})
        resp = api_client.patch(url, {"number_of_tours": 2}, format="json")
        assert resp.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# OrdersDeliveryDayViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOrdersDeliveryDayViewSet:
    URL = reverse("orders_delivery_day-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_days(self, api_client, tenant):
        OrdersDeliveryDayFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# PaymentCycleViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPaymentCycleViewSet:
    URL = reverse("payment_cycle-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_cycles(self, api_client, tenant):
        PaymentCycleFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_is_active(self, api_client, tenant):
        PaymentCycleFactory(is_active=True)
        PaymentCycleFactory(is_active=False)
        resp = api_client.get(self.URL, {"is_active": "true"})
        for pc in resp.data:
            assert pc["is_active"] is True
