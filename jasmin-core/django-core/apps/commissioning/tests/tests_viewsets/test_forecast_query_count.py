"""Query-count locks for the forecast endpoints.

The list answers from ``ForecastService.get_forecasts_with_relations``, which
prefetches the variation and offer-group links, so more forecasts in the week
must not add queries. No route prefetches the linked objects, so
``ForecastSerializer``'s variation and offer-group flags must come from the
link rows' foreign-key ids, not from one fetch of the linked object per link. Validating a payload looks its flags' ids
up once per kind, however many flags it carries.
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


def _detail_url(forecast: Forecast) -> str:
    return reverse("forecast-detail", kwargs={"pk": forecast.pk})


def test_a_patch_that_rewrites_the_links_answers_with_the_new_ones(
    tenant, office_client
):
    # The detail route loads the forecast with its links prefetched; the
    # response must read the links the update wrote, not that prefetch.
    old_variation, new_variation = _variations(2)
    old_group, new_group = OfferGroupFactory(), OfferGroupFactory()
    forecast = ForecastFactory(
        year=YEAR, delivery_week=WEEK, for_all_harvest_shares=False
    )
    ForecastShareTypeVariation.objects.create(
        forecast=forecast, share_type_variation=old_variation
    )
    ForecastOfferGroup.objects.create(forecast=forecast, offer_group=old_group)

    resp = office_client.patch(
        _detail_url(forecast),
        {
            f"variation_{old_variation.pk}": False,
            f"variation_{new_variation.pk}": True,
            f"offer_group_{old_group.pk}": False,
            f"offer_group_{new_group.pk}": True,
        },
        format="json",
    )

    assert resp.status_code == 200, resp.content[:300]
    flags = {
        key
        for key, value in resp.data.items()
        if key.startswith(("variation_", "offer_group_")) and value
    }
    assert flags == {
        f"variation_{new_variation.pk}",
        f"offer_group_{new_group.pk}",
    }


def _validation_queries(variations, offer_groups) -> int:
    payload = {
        **{f"variation_{variation.pk}": True for variation in variations},
        **{f"offer_group_{group.pk}": True for group in offer_groups},
    }
    serializer = ForecastSerializer(
        ForecastFactory(year=YEAR, delivery_week=WEEK), data=payload, partial=True
    )
    with CaptureQueriesContext(connection) as ctx:
        assert serializer.is_valid(), serializer.errors
    return len(ctx.captured_queries)


def test_validating_the_flags_is_one_lookup_per_kind(tenant):
    variations = _variations(6)
    offer_groups = [OfferGroupFactory() for _ in range(6)]

    small = _validation_queries(variations[:1], offer_groups[:1])
    large = _validation_queries(variations, offer_groups)

    assert large == small, f"{small} queries for 1 flag each, {large} for 6"


def test_a_loaded_forecast_renders_with_only_the_deletability_probes(tenant):
    # Names come from the select_related, the flags and the links' share of
    # the deletability check from the prefetch; what is left is one existence
    # probe per other relation that would block a delete. Without links, so
    # that the check reaches every relation.
    forecast = ForecastFactory(year=YEAR, delivery_week=WEEK)
    loaded = (
        Forecast.objects.select_related("share_article", "plot")
        .prefetch_related("forecastsharetypevariation_set", "forecastoffergroup_set")
        .get(pk=forecast.pk)
    )

    with CaptureQueriesContext(connection) as ctx:
        assert ForecastSerializer(loaded).data["id"] == forecast.pk

    tables = {
        query["sql"].split(" FROM ")[1].split()[0].strip('"')
        for query in ctx.captured_queries
        if " FROM " in query["sql"]
    }
    assert tables == {
        "commissioning_theoreticalharvest",
        "commissioning_sharecontent",
    }
