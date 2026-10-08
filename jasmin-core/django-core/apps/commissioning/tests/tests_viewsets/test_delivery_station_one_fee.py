"""A delivery station is paid in one way only: per box, per month or per year.

Billing reads the first non-zero of the three fees, so the server refuses a
write that would leave more than one of them above zero. A partial update is
judged together with the fees the station already stores. A station stored with
several fees stays readable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import DeliveryStation
from apps.commissioning.tests.factories import DeliveryStationFactory

CODE = "delivery_station.more_than_one_fee"


def _detail(station):
    return reverse("delivery_station-detail", kwargs={"pk": station.pk})


def _patch(api_client, station, payload):
    return api_client.patch(_detail(station), payload, format="json")


@pytest.mark.django_db
class TestDeliveryStationOneFee:
    def test_a_new_station_with_two_fees_is_refused(self, api_client, tenant):
        resp = api_client.post(
            reverse("delivery_station-list"),
            {
                "short_name": "Two fees",
                "fee_per_box_net": "1.50",
                "fee_per_month_net": "20.00",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == CODE
        assert not DeliveryStation.objects.filter(short_name="Two fees").exists()

    def test_a_new_station_with_one_fee_is_saved(self, api_client, tenant):
        resp = api_client.post(
            reverse("delivery_station-list"),
            {"short_name": "One fee", "fee_per_year_net": "120.00"},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        assert resp.json()["fee_per_year_net"] == "120.00"

    def test_setting_all_three_fees_is_refused(self, api_client, tenant):
        station = DeliveryStationFactory()

        resp = _patch(
            api_client,
            station,
            {
                "fee_per_box_net": "1.00",
                "fee_per_month_net": "2.00",
                "fee_per_year_net": "3.00",
            },
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == CODE

    def test_adding_a_second_fee_to_a_stored_one_is_refused(self, api_client, tenant):
        station = DeliveryStationFactory(fee_per_box_net=Decimal("1.50"))

        resp = _patch(api_client, station, {"fee_per_month_net": "20.00"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == CODE
        station.refresh_from_db()
        assert station.fee_per_box_net == Decimal("1.50")
        assert station.fee_per_month_net == Decimal("0")

    def test_switching_the_fee_by_clearing_the_old_one_is_saved(
        self, api_client, tenant
    ):
        station = DeliveryStationFactory(fee_per_box_net=Decimal("1.50"))

        resp = _patch(
            api_client,
            station,
            {
                "fee_per_box_net": "0",
                "fee_per_month_net": "20.00",
                "fee_per_year_net": "0",
            },
        )

        assert resp.status_code == status.HTTP_200_OK, resp.content
        station.refresh_from_db()
        assert station.fee_per_box_net == Decimal("0")
        assert station.fee_per_month_net == Decimal("20.00")

    def test_another_field_of_a_one_fee_station_is_saved(self, api_client, tenant):
        station = DeliveryStationFactory(fee_per_month_net=Decimal("20.00"))

        resp = _patch(api_client, station, {"short_name": "Renamed"})

        assert resp.status_code == status.HTTP_200_OK, resp.content
        station.refresh_from_db()
        assert station.short_name == "Renamed"

    def test_a_stored_station_with_two_fees_stays_readable(self, api_client, tenant):
        station = DeliveryStationFactory(
            fee_per_box_net=Decimal("1.50"), fee_per_year_net=Decimal("100.00")
        )

        resp = api_client.get(_detail(station))

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["fee_per_box_net"] == "1.50"
        assert resp.json()["fee_per_year_net"] == "100.00"

    def test_a_stored_station_with_two_fees_saves_once_one_is_cleared(
        self, api_client, tenant
    ):
        station = DeliveryStationFactory(
            fee_per_box_net=Decimal("1.50"), fee_per_year_net=Decimal("100.00")
        )

        refused = _patch(api_client, station, {"short_name": "Renamed"})
        cleared = _patch(api_client, station, {"fee_per_year_net": "0"})

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert refused.json()["code"] == CODE
        assert cleared.status_code == status.HTTP_200_OK, cleared.content
