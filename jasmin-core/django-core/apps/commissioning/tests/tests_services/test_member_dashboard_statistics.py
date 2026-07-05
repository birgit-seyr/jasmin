"""Tests for calculate_member_dashboard_statistics — the office member snapshot."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.services import calculate_member_dashboard_statistics
from apps.commissioning.tests.factories import CoopShareFactory, MemberFactory


@pytest.mark.django_db
class TestMemberDashboardStatistics:
    def test_member_and_coopshare_aggregates(self, tenant):
        today = timezone.localdate()
        entry = datetime.date(2020, 1, 6)

        confirmed = MemberFactory(
            admin_confirmed=True,
            is_active=True,
            entry_date=entry,
            birth_date=today.replace(year=today.year - 30),
        )
        MemberFactory(admin_confirmed=False, is_active=True, entry_date=entry)
        MemberFactory(
            admin_confirmed=True, is_trial=True, is_active=True, entry_date=entry
        )
        cancelled = MemberFactory(
            admin_confirmed=True,
            entry_date=entry,
            cancelled_at=timezone.now(),
            cancelled_effective_at=today,
        )

        # Live cooperative shares on the confirmed member: 3 paid + confirmed,
        # 2 unpaid + pending.
        CoopShareFactory(
            member=confirmed,
            amount_of_coop_shares=Decimal("3"),
            admin_confirmed=True,
            paid_at=timezone.now(),
        )
        CoopShareFactory(
            member=confirmed,
            amount_of_coop_shares=Decimal("2"),
            admin_confirmed=False,
            paid_at=None,
        )
        # The cancelled member's share is owed back (payback due, not paid back).
        CoopShareFactory(
            member=cancelled,
            amount_of_coop_shares=Decimal("5"),
            admin_confirmed=True,
            paid_at=timezone.now(),
            cancelled_at=timezone.now(),
            cancelled_effective_at=today,
            payback_due_date=today,
            paid_back_date=None,
        )

        stats = calculate_member_dashboard_statistics()

        assert stats["total_members"] == 4
        assert stats["confirmed_members"] == 3  # confirmed, trial, cancelled
        assert stats["pending_members"] == 1
        assert stats["trial_members"] == 1
        assert stats["cancelled_members"] == 1
        assert stats["average_age"] == pytest.approx(30.0, abs=0.1)

        # Live shares (cancelled excluded): 3 + 2 = 5.
        assert stats["total_coop_shares"] == 5.0
        assert stats["confirmed_coop_shares"] == 3.0
        assert stats["pending_coop_shares"] == 2.0
        assert stats["paid_coop_shares"] == 3.0
        assert stats["unpaid_coop_shares"] == 2.0
        # The cancelled share is owed back.
        assert stats["payback_due_coop_shares"] == 5.0

    def test_empty_tenant_is_zeroed(self, tenant):
        stats = calculate_member_dashboard_statistics()
        assert stats["total_members"] == 0
        assert stats["average_age"] == 0.0
        assert stats["total_coop_shares"] == 0.0
        assert stats["payback_due_coop_shares"] == 0.0

    def test_endpoint(self, api_client, tenant):
        from django.urls import reverse
        from rest_framework import status

        MemberFactory(admin_confirmed=True, is_active=True)
        resp = api_client.get(reverse("member_dashboard_statistics"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["total_members"] == 1
        assert resp.data["confirmed_members"] == 1
