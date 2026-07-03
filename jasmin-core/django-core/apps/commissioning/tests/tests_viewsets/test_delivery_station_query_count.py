"""Performance regression lock for the delivery-stations list endpoint (PERF-5).

Mirrors ``apps/payments/tests/test_query_count_locks.py``: it does not measure
wall-clock latency — it asserts that adding more stations to
``/api/commissioning/delivery_stations/`` does **not** add proportional
queries.

The two surfaces this guards:

- ``DeliveryStationSerializer.get_can_be_deleted`` /
  ``get_linked_reseller_can_be_deleted`` ran ``can_delete_instance`` (R
  queries) per row — now bulk-precomputed once per page by
  ``DeliveryStationListSerializer``.
- ``obj.linked_reseller`` (forward OneToOne) was an extra query per row —
  now ``select_related`` in the viewset queryset.

A regression that drops either the select_related or the bulk precompute
shows up as +N queries per station.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    DeliveryStationFactory,
    JasminUserFactory,
    ResellerFactory,
)

pytestmark = pytest.mark.django_db

# Generous absolute ceiling that still catches obvious regressions.
HARD_CEILING = 80


def _count_queries_on(client: APIClient, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url)
    assert resp.status_code in (200, 204), (
        f"{url} returned {resp.status_code}; perf-lock test cannot validate "
        f"a failing endpoint. Body: {resp.content[:200]!r}"
    )
    return len(ctx.captured_queries)


@pytest.fixture()
def office_client(tenant):
    user = JasminUserFactory(roles=["office", "admin"])
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _seed_station() -> None:
    """One station with a linked reseller per row.

    The linked reseller exercises ``get_linked_reseller_can_be_deleted`` —
    the path that short-circuits (returns True) when ``linked_reseller`` is
    None, so without a reseller the lock would catch nothing on that surface.
    """
    DeliveryStationFactory(linked_reseller=ResellerFactory())


def test_delivery_stations_list_is_scale_invariant(tenant, office_client):
    url = reverse("delivery_station-list")

    for _ in range(2):
        _seed_station()
    small = _count_queries_on(office_client, url)

    for _ in range(8):
        _seed_station()
    large = _count_queries_on(office_client, url)

    assert large - small <= 3, (
        f"delivery_stations/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small}). The per-row "
        f"deletability checks must be bulk-precomputed and linked_reseller "
        f"select_related."
    )
    assert large <= HARD_CEILING, f"delivery_stations/ exceeded hard ceiling: {large}"
