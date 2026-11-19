"""A delivery station's surcharge on its loose packing list is written on its
own, the way the commissioning settings' station window sends it: the rest of
the station stays as stored, and an empty value clears it."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import DeliveryStationFactory

FIELD = "percentage_added_to_bulk_packing_list"


def _patch(api_client, station, value):
    return api_client.patch(
        reverse("delivery_station-detail", kwargs={"pk": station.pk}),
        {FIELD: value},
        format="json",
    )


@pytest.mark.django_db
class TestDeliveryStationBulkPackingPercentage:
    def test_the_surcharge_alone_is_saved(self, api_client, tenant):
        station = DeliveryStationFactory(short_name="Market hall")

        resp = _patch(api_client, station, 10)

        assert resp.status_code == status.HTTP_200_OK, resp.content
        assert resp.json()[FIELD] == 10
        station.refresh_from_db()
        assert station.percentage_added_to_bulk_packing_list == 10
        assert station.short_name == "Market hall"

    def test_an_empty_surcharge_clears_it(self, api_client, tenant):
        station = DeliveryStationFactory(percentage_added_to_bulk_packing_list=10)

        resp = _patch(api_client, station, None)

        assert resp.status_code == status.HTTP_200_OK, resp.content
        station.refresh_from_db()
        assert station.percentage_added_to_bulk_packing_list is None

    def test_a_negative_surcharge_is_refused(self, api_client, tenant):
        station = DeliveryStationFactory()

        resp = _patch(api_client, station, -5)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        station.refresh_from_db()
        assert station.percentage_added_to_bulk_packing_list is None
