"""Tests for share_options_views.py — share_options_list & active_share_options_list."""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    ShareTypeFactory,
    ShareTypeVariationFactory,
)

URL_ALL = reverse("share_options_list")
URL_ACTIVE = reverse("active_share_options_list")


# ---------------------------------------------------------------------------
# share_options_list
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareOptionsList:
    def test_returns_list_of_options(self, api_client, tenant):
        resp = api_client.get(URL_ALL)
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)
        assert len(resp.data) > 0
        # Each entry has value/label
        assert "value" in resp.data[0]
        assert "label" in resp.data[0]

    def test_options_have_expected_keys(self, api_client, tenant):
        resp = api_client.get(URL_ALL)
        values = {item["value"] for item in resp.data}
        # HARVEST_SHARE should always be in choices
        assert "HARVEST_SHARE" in values


# ---------------------------------------------------------------------------
# active_share_options_list
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestActiveShareOptionsList:
    def test_no_active_variations(self, api_client, tenant):
        resp = api_client.get(URL_ACTIVE)
        assert resp.status_code == status.HTTP_200_OK
        # All options should be False when no variations exist
        assert resp.data["fruit_and_veg_shares_are_separate"] is False

    @time_machine.travel(datetime.date(2026, 6, 1), tick=False)
    def test_active_harvest_share(self, api_client, tenant):
        # valid_from must be a Monday, valid_until must be a Sunday
        st = ShareTypeFactory(share_option="HARVEST_SHARE")
        ShareTypeVariationFactory(
            share_type=st,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2026, 12, 27),  # Sunday
        )

        resp = api_client.get(URL_ACTIVE)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["HARVEST_SHARE"] is True

    @time_machine.travel(datetime.date(2026, 6, 1), tick=False)
    def test_fruit_and_veg_separate(self, api_client, tenant):
        # valid_from must be a Monday, valid_until must be a Sunday
        st_veg = ShareTypeFactory(share_option="HARVEST_SHARE")
        ShareTypeVariationFactory(
            share_type=st_veg,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2026, 12, 27),  # Sunday
        )
        st_fruit = ShareTypeFactory(share_option="HARVEST_SHARE_FRUIT")
        ShareTypeVariationFactory(
            share_type=st_fruit,
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2026, 12, 27),  # Sunday
        )

        resp = api_client.get(URL_ACTIVE)
        assert resp.data["HARVEST_SHARE"] is True
        assert resp.data["HARVEST_SHARE_FRUIT"] is True
        assert resp.data["fruit_and_veg_shares_are_separate"] is True
