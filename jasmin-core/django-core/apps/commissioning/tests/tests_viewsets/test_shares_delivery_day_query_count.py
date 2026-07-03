"""PERF-1: the SharesDeliveryDay list endpoint bulk-precomputes
``can_be_deleted`` (one batch + one Subscription query for the page) instead of
the old per-row N+1. This locks the part most likely to regress under the bulk
refactor: that the bulk path yields the SAME boolean as the per-instance check.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    SharesDeliveryDayFactory,
    SubscriptionFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture()
def office_client(tenant):
    user = JasminUserFactory(roles=["office", "admin"])
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _rows(resp):
    data = resp.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


def test_list_can_be_deleted_matches_per_instance(tenant, office_client):
    # A free day (no shares, no subscriptions) is deletable.
    free_day = SharesDeliveryDayFactory(day_number=2)
    # A day referenced (2 hops) by a subscription's default delivery station-day
    # is NOT — this is the Subscription check bulk-precomputed once for the page.
    in_use_day = SharesDeliveryDayFactory(day_number=3)
    dsd = DeliveryStationDayFactory(delivery_day=in_use_day)
    SubscriptionFactory(default_delivery_station_day=dsd)

    resp = office_client.get(reverse("share_delivery_day-list"))
    assert resp.status_code == 200, resp.content[:200]

    by_id = {str(row["id"]): row for row in _rows(resp)}
    assert by_id[str(free_day.id)]["can_be_deleted"] is True
    assert by_id[str(in_use_day.id)]["can_be_deleted"] is False
