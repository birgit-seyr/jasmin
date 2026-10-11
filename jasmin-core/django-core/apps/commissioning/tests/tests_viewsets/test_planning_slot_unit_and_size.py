"""A planning update takes the slot's unit and size from its id and writes them
into the rebuilt rows, so a unit or size the column doesn't allow is refused,
not stored."""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import ShareContent
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ShareArticleFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
)

YEAR, WEEK = 2026, 20
HARVEST = "HARVEST_SHARE"


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday ten weeks before the planned week, away from a year boundary.
    with time_machine.travel(datetime.datetime(2026, 3, 2, 12, 0), tick=False):
        yield


@pytest.fixture
def setup(tenant):
    day = SharesDeliveryDayFactory()
    DeliveryStationDayFactory(
        delivery_station=DeliveryStationFactory(is_active=True),
        delivery_day=day,
        tour_number=1,
    )
    variation = ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option=HARVEST)
    )
    return {
        "article": ShareArticleFactory(),
        "cell": f"day_{day.id}_variation_{variation.id}",
    }


@pytest.mark.django_db
class TestPlanningSlotSize:
    @pytest.mark.parametrize(
        "size_and_option",
        ["", f"_{HARVEST}", "X", f"X_{HARVEST}"],
        ids=["empty", "empty-with-option", "unknown", "unknown-with-option"],
    )
    def test_an_update_refuses_a_size_the_column_does_not_allow(
        self, api_client, setup, size_and_option
    ):
        slot_id = f"{YEAR}_{WEEK}_{setup['article'].id}_KG_{size_and_option}"

        resp = api_client.put(
            reverse("harvest_share_planning-detail", args=[slot_id]),
            {setup["cell"]: "5"},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "share_content.invalid_pk"
        assert not ShareContent.objects.filter(share_article=setup["article"]).exists()

    def test_an_update_with_a_known_size_stores_it(self, api_client, setup):
        slot_id = f"{YEAR}_{WEEK}_{setup['article'].id}_KG_L_{HARVEST}"

        resp = api_client.put(
            reverse("harvest_share_planning-detail", args=[slot_id]),
            {setup["cell"]: "5"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        sizes = set(
            ShareContent.objects.filter(share_article=setup["article"]).values_list(
                "size", flat=True
            )
        )
        assert sizes == {"L"}


@pytest.mark.django_db
class TestPlanningSlotUnit:
    @pytest.mark.parametrize(
        "unit_and_rest",
        ["_L", f"_L_{HARVEST}", "X_L", f"X_L_{HARVEST}", f"kg_L_{HARVEST}"],
        ids=[
            "empty",
            "empty-with-option",
            "unknown",
            "unknown-with-option",
            "wrong-case",
        ],
    )
    def test_an_update_refuses_a_unit_the_column_does_not_allow(
        self, api_client, setup, unit_and_rest
    ):
        slot_id = f"{YEAR}_{WEEK}_{setup['article'].id}_{unit_and_rest}"

        resp = api_client.put(
            reverse("harvest_share_planning-detail", args=[slot_id]),
            {setup["cell"]: "5"},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "share_content.invalid_pk"
        assert not ShareContent.objects.filter(share_article=setup["article"]).exists()

    def test_an_update_with_a_known_unit_stores_it(self, api_client, setup):
        slot_id = f"{YEAR}_{WEEK}_{setup['article'].id}_PCS_L_{HARVEST}"

        resp = api_client.put(
            reverse("harvest_share_planning-detail", args=[slot_id]),
            {setup["cell"]: "5"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        units = set(
            ShareContent.objects.filter(share_article=setup["article"]).values_list(
                "unit", flat=True
            )
        )
        assert units == {"PCS"}
