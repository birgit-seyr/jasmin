"""Tests for the ``income_by_month`` action on ChargeScheduleViewSet
(powers the DashboardAbos billed-income chart).

Billed income = SUM(expected_amount) of PLANNED / ISSUED / PARTIAL / PAID
charges, grouped by due-date month within [date_from, date_to]. WAIVED
(forgiven) and FAILED (returned by bank) are excluded.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule


def _charge(member, subscription, *, due_date, amount, status=ChargeStatus.PLANNED):
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=due_date,
        period_end=due_date + datetime.timedelta(days=27),
        due_date=due_date,
        expected_amount=Decimal(amount),
        currency="EUR",
        description=f"charge {due_date.isoformat()}",
        status=status,
    )


@pytest.mark.django_db
class TestChargeScheduleIncomeByMonth:
    # Router uses underscores, not hyphens (see apps/payments/urls.py).
    URL = "/api/payments/charge_schedules/income_by_month/"

    def _seed(self, member, subscription):
        # January: two billed charges → 10.00 + 5.50 = 15.50
        _charge(
            member, subscription, due_date=datetime.date(2026, 1, 5), amount="10.00"
        )
        _charge(
            member,
            subscription,
            due_date=datetime.date(2026, 1, 20),
            amount="5.50",
            status=ChargeStatus.ISSUED,
        )
        # February: two billed charges → 12.00 + 3.00 = 15.00 …
        _charge(
            member,
            subscription,
            due_date=datetime.date(2026, 2, 5),
            amount="12.00",
            status=ChargeStatus.PAID,
        )
        _charge(
            member,
            subscription,
            due_date=datetime.date(2026, 2, 10),
            amount="3.00",
            status=ChargeStatus.PARTIAL,
        )
        # … plus a WAIVED and a FAILED one that must NOT count.
        _charge(
            member,
            subscription,
            due_date=datetime.date(2026, 2, 15),
            amount="99.00",
            status=ChargeStatus.WAIVED,
        )
        _charge(
            member,
            subscription,
            due_date=datetime.date(2026, 2, 20),
            amount="88.00",
            status=ChargeStatus.FAILED,
        )
        # March: outside the queried window.
        _charge(member, subscription, due_date=datetime.date(2026, 3, 5), amount="7.00")

    def test_sums_billed_income_per_month(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        resp = api_client.get(
            self.URL, {"date_from": "2026-01-01", "date_to": "2026-02-28"}
        )
        assert resp.status_code == 200
        # Two months, sorted ascending; WAIVED + FAILED excluded; March out of range.
        assert resp.data == [
            {"month": "2026-01", "amount": "15.50"},
            {"month": "2026-02", "amount": "15.00"},
        ]

    def test_amount_is_two_decimal_string(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        _charge(member, subscription, due_date=datetime.date(2026, 5, 4), amount="8")
        resp = api_client.get(
            self.URL, {"date_from": "2026-05-01", "date_to": "2026-05-31"}
        )
        assert resp.status_code == 200
        assert resp.data == [{"month": "2026-05", "amount": "8.00"}]
        assert isinstance(resp.data[0]["amount"], str)

    def test_range_excludes_out_of_window_months(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        # Only March is in range now.
        resp = api_client.get(
            self.URL, {"date_from": "2026-03-01", "date_to": "2026-03-31"}
        )
        assert resp.status_code == 200
        assert resp.data == [{"month": "2026-03", "amount": "7.00"}]

    def test_no_matches_returns_empty(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        self._seed(member, subscription)
        resp = api_client.get(
            self.URL, {"date_from": "2030-01-01", "date_to": "2030-12-31"}
        )
        assert resp.status_code == 200
        assert resp.data == []

    def test_missing_date_returns_400(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        resp = api_client.get(self.URL, {"date_from": "2026-01-01"})
        assert resp.status_code == 400

    def test_from_after_to_returns_400(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        resp = api_client.get(
            self.URL, {"date_from": "2026-02-01", "date_to": "2026-01-01"}
        )
        assert resp.status_code == 400
        assert resp.data["field"] == "date_from"

    def test_invalid_date_returns_400(
        self, api_client, tenant, tenant_settings, member, subscription
    ):
        resp = api_client.get(
            self.URL, {"date_from": "not-a-date", "date_to": "2026-01-01"}
        )
        assert resp.status_code == 400
        assert resp.data["field"] == "date_from"

    def test_office_only(
        self, member_api_client, tenant, tenant_settings, member, subscription
    ):
        # A member-role caller must not read farm-wide income.
        resp = member_api_client.get(
            self.URL, {"date_from": "2026-01-01", "date_to": "2026-12-31"}
        )
        assert resp.status_code == 403
