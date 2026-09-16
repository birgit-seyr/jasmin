"""Tests for statistic_views.py — member_growth_statistics & historical_share_type_variation_averages."""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.tests.factories import (
    MemberFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

URL_MEMBER_GROWTH = reverse("member_growth_statistics")
URL_VARIATION_AVERAGES = reverse("historical_share_type_variation_averages")


def _admitted(entry_date, *, exit_date=None):
    """A confirmed member who joined on ``entry_date`` and, with ``exit_date``,
    has left."""
    fields = {"admin_confirmed": True, "entry_date": entry_date}
    if exit_date is not None:
        fields["cancelled_at"] = timezone.now()
        fields["cancelled_effective_at"] = exit_date
    return MemberFactory(**fields)


# ---------------------------------------------------------------------------
# member_growth_statistics
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberGrowthStatistics:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        # A Monday away from any year boundary: exits after it haven't happened.
        with time_machine.travel(datetime.datetime(2025, 7, 14, 12, 0), tick=False):
            yield

    def test_returns_entries_exits_and_totals_per_month(self, api_client, tenant):
        _admitted(datetime.date(2025, 3, 10))
        _admitted(datetime.date(2025, 3, 20))
        _admitted(datetime.date(2025, 4, 5))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "month"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == [
            {
                "period": "2025-03-01",
                "new_members": 2,
                "exited_members": 0,
                "total_members": 2,
            },
            {
                "period": "2025-04-01",
                "new_members": 1,
                "exited_members": 0,
                "total_members": 3,
            },
        ]

    def test_unconfirmed_and_trial_members_are_left_out(self, api_client, tenant):
        _admitted(datetime.date(2025, 3, 10))
        MemberFactory(admin_confirmed=False, entry_date=datetime.date(2025, 3, 11))
        MemberFactory(
            admin_confirmed=True,
            is_trial=True,
            member_number=None,
            entry_date=datetime.date(2025, 3, 12),
        )

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "month"})
        assert resp.status_code == status.HTTP_200_OK
        assert [(row["new_members"], row["total_members"]) for row in resp.data] == [
            (1, 1)
        ]

    def test_exits_are_subtracted_in_the_exit_period(self, api_client, tenant):
        _admitted(datetime.date(2025, 1, 10))
        _admitted(datetime.date(2025, 1, 20), exit_date=datetime.date(2025, 3, 31))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "month"})
        assert resp.status_code == status.HTTP_200_OK
        assert [
            (
                row["period"],
                row["new_members"],
                row["exited_members"],
                row["total_members"],
            )
            for row in resp.data
        ] == [("2025-01-01", 2, 0, 2), ("2025-03-01", 0, 1, 1)]

    def test_exit_after_today_is_not_counted_yet(self, api_client, tenant):
        _admitted(datetime.date(2025, 2, 3), exit_date=datetime.date(2025, 12, 31))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "month"})
        assert resp.status_code == status.HTTP_200_OK
        assert [(row["exited_members"], row["total_members"]) for row in resp.data] == [
            (0, 1)
        ]

    def test_filter_by_year_starts_from_the_members_before_it(self, api_client, tenant):
        _admitted(datetime.date(2023, 5, 2), exit_date=datetime.date(2024, 6, 30))
        _admitted(datetime.date(2024, 1, 1))
        _admitted(datetime.date(2025, 6, 1))

        resp = api_client.get(URL_MEMBER_GROWTH, {"year": 2025})
        assert resp.status_code == status.HTTP_200_OK
        assert [
            (row["period"], row["new_members"], row["total_members"])
            for row in resp.data
        ] == [("2025-06-01", 1, 2)]

    def test_start_date_starts_from_the_members_before_it(self, api_client, tenant):
        _admitted(datetime.date(2025, 1, 10))
        _admitted(datetime.date(2025, 4, 1))

        resp = api_client.get(URL_MEMBER_GROWTH, {"start_date": "2025-03-01"})
        assert resp.status_code == status.HTTP_200_OK
        assert [
            (row["period"], row["new_members"], row["total_members"])
            for row in resp.data
        ] == [("2025-04-01", 1, 2)]

    def test_week_periods_start_on_monday(self, api_client, tenant):
        _admitted(datetime.date(2025, 3, 12))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "week"})
        assert resp.status_code == status.HTTP_200_OK
        assert [row["period"] for row in resp.data] == ["2025-03-10"]

    def test_invalid_period_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_MEMBER_GROWTH, {"period": "invalid"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] == "period"

    def test_empty_period_falls_back_to_month(self, api_client, tenant):
        _admitted(datetime.date(2025, 3, 10))

        resp = api_client.get(URL_MEMBER_GROWTH, {"period": ""})

        assert resp.status_code == status.HTTP_200_OK
        assert [row["period"] for row in resp.data] == ["2025-03-01"]

    def test_empty_when_no_members(self, api_client, tenant):
        resp = api_client.get(URL_MEMBER_GROWTH)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


# ---------------------------------------------------------------------------
# historical_share_type_variation_averages
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHistoricalShareTypeVariationAverages:
    def test_returns_averages(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        dd = SharesDeliveryDayFactory()
        # Create share content for two past years, reusing the same delivery day
        for year in (2024, 2025):
            share = ShareFactory(
                year=year,
                delivery_week=15,
                share_type_variation=variation,
                delivery_day=dd,
            )
            ShareContentFactory(share=share, amount=10)

        resp = api_client.get(
            URL_VARIATION_AVERAGES,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_type_variation_ids": str(variation.id),
                "years_back": 2,
            },
        )

        assert resp.status_code == status.HTTP_200_OK

    def test_missing_params_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_VARIATION_AVERAGES)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_for_no_data(self, api_client, tenant):
        variation = ShareTypeVariationFactory()
        resp = api_client.get(
            URL_VARIATION_AVERAGES,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_type_variation_ids": str(variation.id),
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {}
