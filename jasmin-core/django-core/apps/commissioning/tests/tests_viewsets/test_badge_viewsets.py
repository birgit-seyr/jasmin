"""Tests for badge_viewsets.py — unconfirmed counts."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    CoopShareFactory,
    DeliveryStationDayFactory,
    MemberFactory,
    SubscriptionFactory,
)


# ---------------------------------------------------------------------------
# UnconfirmedSubscriptionsViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUnconfirmedSubscriptionsViewSet:
    URL = reverse("unconfirmed_subscriptions-unconfirmed-count")

    def test_zero_when_none(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_counts_unconfirmed(self, api_client, tenant):
        dsd = DeliveryStationDayFactory()
        m1 = MemberFactory()
        m2 = MemberFactory()
        SubscriptionFactory(
            admin_confirmed=False,
            is_trial=False,
            member=m1,
            default_delivery_station_day=dsd,
        )
        SubscriptionFactory(
            admin_confirmed=True,
            is_trial=False,
            member=m2,
            default_delivery_station_day=dsd,
        )
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 1

    def test_excludes_trial(self, api_client, tenant):
        SubscriptionFactory(admin_confirmed=False, is_trial=True)
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0

    def test_excludes_rejected(self, api_client, tenant):
        # A rejected subscription is handled — it must not keep the badge red.
        from django.utils import timezone

        SubscriptionFactory(
            admin_confirmed=False, is_trial=False, admin_rejected_at=timezone.now()
        )
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0


# ---------------------------------------------------------------------------
# UnconfirmedTrialSubscriptionsViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUnconfirmedTrialSubscriptionsViewSet:
    URL = reverse("unconfirmed_trial_subscriptions-unconfirmed-count")

    def test_zero_when_none(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_counts_unconfirmed_trial(self, api_client, tenant):
        SubscriptionFactory(admin_confirmed=False, is_trial=True)
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 1

    def test_excludes_non_trial(self, api_client, tenant):
        SubscriptionFactory(admin_confirmed=False, is_trial=False)
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0

    def test_excludes_rejected_trial(self, api_client, tenant):
        from django.utils import timezone

        SubscriptionFactory(
            admin_confirmed=False, is_trial=True, admin_rejected_at=timezone.now()
        )
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0


# ---------------------------------------------------------------------------
# UnconfirmedMembersViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUnconfirmedMembersViewSet:
    URL = reverse("unconfirmed_members-unconfirmed-count")

    def test_zero_when_none(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_counts_unconfirmed(self, api_client, tenant):
        MemberFactory(admin_confirmed=False, is_trial=False)
        MemberFactory(admin_confirmed=True, is_trial=False)
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 1

    def test_excludes_trial(self, api_client, tenant):
        MemberFactory(admin_confirmed=False, is_trial=True)
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0

    def test_excludes_rejected(self, api_client, tenant):
        # A rejected applicant has already been handled — they must NOT keep the
        # office badge red. Only members that still need attention are counted.
        from django.utils import timezone

        MemberFactory(
            admin_confirmed=False, is_trial=False, admin_rejected_at=timezone.now()
        )
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0


# ---------------------------------------------------------------------------
# UnconfirmedCoopSharesViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUnconfirmedCoopSharesViewSet:
    URL = reverse("unconfirmed_coop_shares-unconfirmed-count")

    def test_zero_when_none(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_counts_unconfirmed(self, api_client, tenant):
        CoopShareFactory(admin_confirmed=False)
        CoopShareFactory(admin_confirmed=True)
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 1

    def test_excludes_cancelled(self, api_client, tenant):
        # A cancelled coop share is handled — it must not keep the badge red.
        from django.utils import timezone

        CoopShareFactory(admin_confirmed=False, cancelled_at=timezone.now())
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0

    def test_excludes_rejected(self, api_client, tenant):
        from django.utils import timezone

        CoopShareFactory(admin_confirmed=False, admin_rejected_at=timezone.now())
        resp = api_client.get(self.URL)
        assert resp.data["count"] == 0
