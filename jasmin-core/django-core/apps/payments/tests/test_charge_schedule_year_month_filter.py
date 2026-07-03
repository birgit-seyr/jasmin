"""Regression tests for the year/month query-param filter on
ChargeScheduleViewSet (powers the ChargesAbos page).

The viewset code lives in apps/payments/viewsets.py — the filter is
applied via ``due_date__year`` / ``due_date__month`` lookups in
``filter_queryset`` (around lines 134-147).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule


def _make_charge(member, subscription, *, due_date, amount=Decimal("10")):
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=due_date,
        period_end=due_date + datetime.timedelta(days=27),
        due_date=due_date,
        expected_amount=amount,
        currency="EUR",
        description=f"charge {due_date.isoformat()}",
        status=ChargeStatus.PLANNED,
    )


@pytest.mark.django_db
class TestChargeScheduleYearMonthFilter:
    # Note: router uses underscores, not hyphens (see apps/payments/urls.py).
    URL = "/api/payments/charge_schedules/"

    def _seed(self, member, subscription):
        return [
            _make_charge(member, subscription, due_date=datetime.date(2026, 1, 5)),
            _make_charge(member, subscription, due_date=datetime.date(2026, 2, 5)),
            _make_charge(member, subscription, due_date=datetime.date(2026, 3, 5)),
            _make_charge(member, subscription, due_date=datetime.date(2027, 2, 5)),
        ]

    def test_no_params_returns_all(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        resp = api_client.get(self.URL)
        assert resp.status_code == 200
        assert len(resp.data) == 4

    def test_year_only(self, api_client, tenant, tenant_settings, member, subscription):
        self._seed(member, subscription)
        resp = api_client.get(self.URL, {"year": 2026})
        assert resp.status_code == 200
        assert len(resp.data) == 3

    def test_year_and_month(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        resp = api_client.get(self.URL, {"year": 2026, "month": 2})
        assert resp.status_code == 200
        assert len(resp.data) == 1

    def test_invalid_year_returns_400(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        # Garbage query params surface as a 400 so a buggy client
        # doesn't receive every row in the table. The service raises the
        # typed ``InvalidQueryParam`` (code ``query.invalid_param``), rendered
        # by ``core.exception_handler`` as ``{code, message, field, details}``.
        self._seed(member, subscription)
        resp = api_client.get(self.URL, {"year": "abc"})
        assert resp.status_code == 400
        assert resp.data["field"] == "year"
        assert "year" in resp.data["details"]

    def test_invalid_month_returns_400(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        resp = api_client.get(self.URL, {"year": 2026, "month": "xyz"})
        assert resp.status_code == 400
        assert resp.data["field"] == "month"
        assert "month" in resp.data["details"]

    def test_year_with_no_matches_returns_empty(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        resp = api_client.get(self.URL, {"year": 2030})
        assert resp.status_code == 200
        assert len(resp.data) == 0
