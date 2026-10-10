"""Tour numbers start at 1 on every write path of the station-day API.

The station-day CRUD and the tours update refuse a tour below 1 with
``delivery_station_day.tour_number_below_one``. A row stored with tour 0
before the rule can't be saved again until it names a tour.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import DeliveryStationDay
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    SharesDeliveryDayFactory,
)
from apps.commissioning.tests.factories.days import store_legacy_tour_number_zero

CODE = "delivery_station_day.tour_number_below_one"


def _detail_url(station_day: DeliveryStationDay) -> str:
    return reverse("delivery_station_day-detail", kwargs={"pk": station_day.pk})


@pytest.mark.django_db
class TestStationDayCreate:
    URL = reverse("delivery_station_day-list")

    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        # The create guard refuses a valid_from before today; a Monday well
        # before the one below keeps it in the future.
        with time_machine.travel(datetime.datetime(2026, 2, 2, 12, 0), tick=False):
            yield

    @staticmethod
    def _payload(**extra):
        return {
            "delivery_station": str(DeliveryStationFactory().id),
            "delivery_day": str(SharesDeliveryDayFactory().id),
            "valid_from": "2026-03-02",
            **extra,
        }

    @pytest.mark.parametrize("tour_number", [0, -1])
    def test_a_tour_below_one_is_refused(self, api_client, tenant, tour_number):
        payload = self._payload(tour_number=tour_number)

        resp = api_client.post(self.URL, payload, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == CODE
        assert resp.data["field"] == "tour_number"
        assert not DeliveryStationDay.objects.filter(
            delivery_station_id=payload["delivery_station"]
        ).exists()

    def test_tour_one_is_accepted(self, api_client, tenant):
        resp = api_client.post(self.URL, self._payload(tour_number=1), format="json")

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["tour_number"] == 1

    def test_leaving_the_tour_out_defaults_to_one(self, api_client, tenant):
        resp = api_client.post(self.URL, self._payload(), format="json")

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["tour_number"] == 1


@pytest.mark.django_db
class TestStationDayUpdate:
    def test_setting_tour_zero_is_refused(self, api_client, tenant):
        station_day = DeliveryStationDayFactory(tour_number=2)

        resp = api_client.patch(
            _detail_url(station_day), {"tour_number": 0}, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == CODE
        station_day.refresh_from_db()
        assert station_day.tour_number == 2

    def test_a_legacy_tour_zero_row_edit_without_a_tour_is_refused(
        self, api_client, tenant
    ):
        station_day = DeliveryStationDayFactory(special_instructions="old")
        store_legacy_tour_number_zero(station_day)

        resp = api_client.patch(
            _detail_url(station_day), {"special_instructions": "new"}, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == CODE
        station_day.refresh_from_db()
        assert station_day.special_instructions == "old"

    def test_a_legacy_tour_zero_row_takes_a_tour(self, api_client, tenant):
        station_day = DeliveryStationDayFactory()
        store_legacy_tour_number_zero(station_day)

        resp = api_client.patch(
            _detail_url(station_day), {"tour_number": 2}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK
        station_day.refresh_from_db()
        assert station_day.tour_number == 2


@pytest.mark.django_db
class TestUpdateTours:
    def test_tour_zero_is_refused_with_the_code(self, api_client, tenant):
        station = DeliveryStationFactory()
        day = SharesDeliveryDayFactory(day_number=4)

        resp = api_client.post(
            reverse("delivery_tours-update-tours"),
            {
                "delivery_day": str(day.id),
                "tours": [
                    {
                        "tour_number": 0,
                        "positions": [
                            {"position": 1, "delivery_station_id": str(station.id)}
                        ],
                    }
                ],
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == CODE
        assert not DeliveryStationDay.objects.filter(
            delivery_station=station, delivery_day=day
        ).exists()
