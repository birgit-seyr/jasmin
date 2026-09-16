"""Tests for choices_models_viewsets.py — SharesDeliveryDay, OrdersDeliveryDay, PaymentCycle."""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    OrdersDeliveryDayFactory,
    PaymentCycleFactory,
    ShareFactory,
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

    def test_get_delivery_stations_false_omits_the_stations(self, api_client, tenant):
        """Prefetch flag, not a filter: an explicit false must leave the
        stations off instead of switching the prefetch on."""
        day = SharesDeliveryDayFactory(day_number=3)
        DeliveryStationDayFactory(delivery_day=day)

        for raw in ("false", "0"):
            resp = api_client.get(
                self.URL,
                {"get_delivery_stations": raw, "active_at_date": "2026-06-01"},
            )
            row = next(d for d in resp.data if d["id"] == day.id)
            assert row["delivery_stations"] == [], raw

        resp = api_client.get(
            self.URL, {"get_delivery_stations": "true", "active_at_date": "2026-06-01"}
        )
        row = next(d for d in resp.data if d["id"] == day.id)
        assert len(row["delivery_stations"]) == 1

    def test_get_delivery_stations_without_active_at_date_returns_400(
        self, api_client, tenant
    ):
        """The station prefetch resolves "active at a date" and has no answer
        without one, so the date is required rather than compared as None."""
        SharesDeliveryDayFactory(day_number=4)

        resp = api_client.get(self.URL, {"get_delivery_stations": "true"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "active_at_date"

    def test_get_delivery_stations_false_without_active_at_date_is_fine(
        self, api_client, tenant
    ):
        """Only the prefetch needs the date; not asking for stations is still
        a plain unfiltered list."""
        SharesDeliveryDayFactory(day_number=5)

        resp = api_client.get(self.URL, {"get_delivery_stations": "false"})

        assert resp.status_code == status.HTTP_200_OK

    def test_need_info_on_tours_false_omits_used_tours(self, api_client, tenant):
        day = SharesDeliveryDayFactory(day_number=3)
        DeliveryStationDayFactory(delivery_day=day, tour_number=2)

        for raw in ("false", "0"):
            resp = api_client.get(
                self.URL,
                {"need_info_on_tours": raw, "active_at_date": "2026-06-01"},
            )
            row = next(d for d in resp.data if d["id"] == day.id)
            assert "used_tours" not in row, raw

        resp = api_client.get(
            self.URL, {"need_info_on_tours": "true", "active_at_date": "2026-06-01"}
        )
        row = next(d for d in resp.data if d["id"] == day.id)
        assert row["used_tours"] == [2]


# ---------------------------------------------------------------------------
# SharesDeliveryDayViewSet — moving valid_from
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSharesDeliveryDayValidFromMove:
    """Moving the START of a delivery day's window later leaves its existing
    children before the new date uncovered.

    Nothing re-homes them — the child-migration services run only on the
    create/succession path — so the row silently stops covering rows that still
    point at it. All dates here sit in the past so the assertions never depend
    on the wall clock.
    """

    @staticmethod
    def _url(day):
        return reverse("share_delivery_day-detail", kwargs={"pk": day.pk})

    def test_moving_start_later_past_existing_shares_returns_409(
        self, api_client, tenant
    ):
        day = SharesDeliveryDayFactory(valid_from=datetime.date(2026, 1, 5))
        # ISO week 15/2026 starts 2026-04-06 — before the proposed new start.
        ShareFactory(delivery_day=day, year=2026, delivery_week=15)

        resp = api_client.patch(
            self._url(day), {"valid_from": "2026-06-01"}, format="json"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "shares_delivery_day.start_move_strands_children"
        assert resp.data["details"]["stranded_count"] == 1
        day.refresh_from_db()
        assert day.valid_from == datetime.date(2026, 1, 5)

    def test_moving_start_later_past_existing_station_days_returns_409(
        self, api_client, tenant
    ):
        day = SharesDeliveryDayFactory(valid_from=datetime.date(2026, 1, 5))
        DeliveryStationDayFactory(
            delivery_day=day, valid_from=datetime.date(2026, 1, 5)
        )

        resp = api_client.patch(
            self._url(day), {"valid_from": "2026-06-01"}, format="json"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "shares_delivery_day.start_move_strands_children"
        day.refresh_from_db()
        assert day.valid_from == datetime.date(2026, 1, 5)

    def test_moving_start_earlier_into_the_past_is_allowed(self, api_client, tenant):
        """Widening the window backwards strands nothing, and a start in the
        past is deliberately permitted — onboarding backfills a schedule that
        has been running for a while."""
        day = SharesDeliveryDayFactory(valid_from=datetime.date(2026, 1, 5))
        ShareFactory(delivery_day=day, year=2026, delivery_week=15)

        resp = api_client.patch(
            self._url(day), {"valid_from": "2025-11-03"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK
        day.refresh_from_db()
        assert day.valid_from == datetime.date(2025, 11, 3)

    def test_moving_start_later_with_nothing_before_it_is_allowed(
        self, api_client, tenant
    ):
        day = SharesDeliveryDayFactory(valid_from=datetime.date(2026, 1, 5))
        # Week 40/2026 starts 2026-09-28 — after the proposed new start.
        ShareFactory(delivery_day=day, year=2026, delivery_week=40)

        resp = api_client.patch(
            self._url(day), {"valid_from": "2026-06-01"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK
        day.refresh_from_db()
        assert day.valid_from == datetime.date(2026, 6, 1)


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
