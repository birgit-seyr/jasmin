"""Query-count locks for the forecast endpoints.

The list answers from ``ForecastService.get_forecasts_with_relations``, which
prefetches the variation and offer-group links, so more forecasts in the week
must not add queries. ``ForecastSerializer`` renders the create and update
responses from a forecast that carries no prefetch, so its variation and
offer-group flags must come from the link rows' foreign-key ids, not from one
fetch of the linked object per link.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.models import (
    Forecast,
    ForecastOfferGroup,
    ForecastShareTypeVariation,
    ShareTypeVariation,
)
from apps.commissioning.models.choices import ShareOptions
from apps.commissioning.serializers import ForecastSerializer
from apps.commissioning.tests.factories import (
    ForecastFactory,
    JasminUserFactory,
    OfferGroupFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
)

pytestmark = pytest.mark.django_db

YEAR = 2026
WEEK = 15


@pytest.fixture(autouse=True)
def _frozen_clock():
    # The list hides past weeks unless asked; on Monday of week 15 the
    # forecasts' week is the current one.
    with time_machine.travel(datetime.datetime(2026, 4, 6, 12, 0), tick=False):
        yield


@pytest.fixture()
def office_client(tenant):
    user = JasminUserFactory(roles=["office", "admin"])
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _variations(count: int) -> list[ShareTypeVariation]:
    # One share type per share option: a share type holds one open variation
    # per size, so variations of a single share type would run out of sizes.
    return [
        ShareTypeVariationFactory(share_type=ShareTypeFactory(share_option=option))
        for option in list(ShareOptions)[:count]
    ]


def _add_links(forecast: Forecast, variations: list[ShareTypeVariation]) -> None:
    for variation in variations:
        ForecastShareTypeVariation.objects.create(
            forecast=forecast, share_type_variation=variation
        )
        ForecastOfferGroup.objects.create(
            forecast=forecast, offer_group=OfferGroupFactory()
        )


def _count_list_queries(client: APIClient) -> int:
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(
            reverse("forecast-list"), {"year": YEAR, "delivery_week": WEEK}
        )
    assert resp.status_code == 200, resp.content[:200]
    return len(ctx.captured_queries)


def _count_serializer_queries(forecast_id: str) -> tuple[int, dict]:
    forecast = Forecast.objects.get(pk=forecast_id)
    with CaptureQueriesContext(connection) as ctx:
        data = ForecastSerializer(forecast).data
    return len(ctx.captured_queries), data


def test_forecast_list_is_scale_invariant(tenant, office_client):
    variations = _variations(2)
    for _ in range(2):
        _add_links(ForecastFactory(year=YEAR, delivery_week=WEEK), variations)
    small = _count_list_queries(office_client)

    for _ in range(8):
        _add_links(ForecastFactory(year=YEAR, delivery_week=WEEK), variations)
    large = _count_list_queries(office_client)

    assert large == small, f"{small} queries for 2 forecasts, {large} for 10"


def test_serializer_flags_do_not_fetch_per_link(tenant):
    variations = _variations(6)
    few = ForecastFactory(year=YEAR, delivery_week=WEEK)
    _add_links(few, variations[:1])
    many = ForecastFactory(year=YEAR, delivery_week=WEEK)
    _add_links(many, variations)

    small, _ = _count_serializer_queries(few.pk)
    large, data = _count_serializer_queries(many.pk)

    assert large == small, f"{small} queries for 1 link each, {large} for 6"
    assert sum(key.startswith("variation_") for key in data) == 6
    assert sum(key.startswith("offer_group_") for key in data) == 6
