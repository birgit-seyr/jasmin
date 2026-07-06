"""Tests for delivery_viewsets.py — DeliveryStation, DeliveryStationDay, DeliveryTours."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)


# ---------------------------------------------------------------------------
# DeliveryStationViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryStationViewSet:
    URL = reverse("delivery_station-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_stations(self, api_client, tenant):
        DeliveryStationFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_is_active(self, api_client, tenant):
        DeliveryStationFactory(is_active=True)
        DeliveryStationFactory(is_active=False)
        resp = api_client.get(self.URL, {"is_active": "true"})
        assert all(s["is_active"] for s in resp.data)

    def test_retrieve_station(self, api_client, tenant):
        ds = DeliveryStationFactory()
        url = reverse("delivery_station-detail", kwargs={"pk": ds.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK

    def test_can_be_deleted_reflects_delivery_station_days(self, api_client, tenant):
        # A station configured with a delivery-station-day is undeletable: the
        # day CASCADEs off the station but is itself PROTECTed downstream
        # (import demand rows / share content / a member's default station-day),
        # so deleting the station would raise ProtectedError mid-cascade. The
        # office must not be offered a delete button -> can_be_deleted is False.
        # A bare station (no days) is still deletable.
        plain = DeliveryStationFactory()
        dsd = DeliveryStationDayFactory()
        configured = dsd.delivery_station

        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        flags = {s["id"]: s["can_be_deleted"] for s in resp.data}
        assert flags[str(plain.id)] is True
        assert flags[str(configured.id)] is False

    def test_filter_by_member_returns_only_subscribed_stations(
        self, api_client, tenant
    ):
        # A confirmed, still-running subscription pins the member to station A
        # (its default_delivery_station_day's station).
        dsd = DeliveryStationDayFactory()
        station_a = dsd.delivery_station
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd,
            admin_confirmed=True,
        )
        # An unrelated station the member has no subscription to.
        station_b = DeliveryStationFactory()

        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {s["id"] for s in resp.data}
        assert str(station_a.id) in ids
        assert str(station_b.id) not in ids

    def test_filter_by_member_excludes_unconfirmed_subscription(
        self, api_client, tenant
    ):
        # A not-yet-confirmed subscription must NOT surface its station.
        dsd = DeliveryStationDayFactory()
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd,
            admin_confirmed=False,
        )
        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {s["id"] for s in resp.data}
        assert str(dsd.delivery_station.id) not in ids

    def test_member_role_can_list(self, anon_client, member_user, tenant):
        # Members read the list too (their member-detail stations card).
        DeliveryStationFactory()
        anon_client.force_authenticate(user=member_user)
        resp = anon_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# DeliveryStationDayViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryStationDayViewSet:
    URL = reverse("delivery_station_day-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_entries(self, api_client, tenant):
        DeliveryStationDayFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_by_delivery_station(self, api_client, tenant):
        dsd = DeliveryStationDayFactory()
        resp = api_client.get(
            self.URL, {"delivery_station": str(dsd.delivery_station.id)}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_filter_by_delivery_day(self, api_client, tenant):
        dsd = DeliveryStationDayFactory()
        resp = api_client.get(self.URL, {"delivery_day": str(dsd.delivery_day.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_filter_by_member_returns_only_assigned_station_days(
        self, api_client, tenant
    ):
        # A confirmed, still-running subscription assigns the member to station-day
        # A (its default_delivery_station_day); a second station-day is unrelated.
        # Distinct day_numbers so the two SharesDeliveryDays don't collide on the
        # one-open-per-day_number constraint.
        dsd_a = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=1)
        )
        dsd_b = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=3)
        )
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd_a,
            admin_confirmed=True,
        )
        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(dsd_a.id) in ids
        assert str(dsd_b.id) not in ids

    def test_filter_by_member_excludes_unconfirmed_subscription(
        self, api_client, tenant
    ):
        # A not-yet-confirmed subscription must NOT surface its station-day.
        dsd = DeliveryStationDayFactory()
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd,
            admin_confirmed=False,
        )
        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(dsd.id) not in ids

    def test_member_cannot_query_another_members_station_days(
        self, anon_client, member_user, tenant
    ):
        # A crafted ?member=<other id> from a non-staff member is rejected — the
        # member↔station-day association must not be readable cross-member.
        other = SubscriptionFactory(admin_confirmed=True)
        anon_client.force_authenticate(user=member_user)
        resp = anon_client.get(self.URL, {"member": str(other.member.id)})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_filter_by_member_includes_reassigned_upcoming_delivery(
        self, api_client, tenant
    ):
        # Subscription defaults to station-day A, but the member reassigned an
        # UPCOMING delivery to station-day B — both must appear.
        dsd_a = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=1)
        )
        dsd_b = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=3)
        )
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd_a,
            admin_confirmed=True,
        )
        future_share = ShareFactory(
            delivery_day=dsd_b.delivery_day,
            share_type_variation=sub.share_type_variation,
            year=2027,
            delivery_week=15,
        )
        ShareDeliveryFactory(
            subscription=sub, share=future_share, delivery_station_day=dsd_b
        )
        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(dsd_a.id) in ids
        assert str(dsd_b.id) in ids

    def test_filter_by_member_excludes_past_reassigned_delivery(
        self, api_client, tenant
    ):
        # A PAST one-off reassignment isn't actionable — station-day B must NOT
        # surface just because an old delivery used it.
        dsd_a = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=1)
        )
        dsd_b = DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=3)
        )
        sub = SubscriptionFactory(
            default_delivery_station_day=dsd_a,
            admin_confirmed=True,
        )
        past_share = ShareFactory(
            delivery_day=dsd_b.delivery_day,
            share_type_variation=sub.share_type_variation,
            year=2020,
            delivery_week=15,
        )
        ShareDeliveryFactory(
            subscription=sub, share=past_share, delivery_station_day=dsd_b
        )
        resp = api_client.get(self.URL, {"member": str(sub.member.id)})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data}
        assert str(dsd_a.id) in ids
        assert str(dsd_b.id) not in ids

    def test_capacity_without_year_week_returns_null(self, api_client, tenant):
        DeliveryStationDayFactory(capacity=10)
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data[0]["capacity_by_week"] is None

    def test_capacity_no_deliveries(self, api_client, tenant):
        dsd = DeliveryStationDayFactory(capacity=10)
        resp = api_client.get(
            self.URL, {"year": 2026, "delivery_week": 15, "num_weeks": 1}
        )
        assert resp.status_code == status.HTTP_200_OK
        entry = next(e for e in resp.data if e["id"] == str(dsd.id))
        assert entry["capacity_by_week"]["2026-15"]["occupied"] == 0
        assert entry["capacity_by_week"]["2026-15"]["free"] == 10

    def test_capacity_counts_harvest_shares(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=3)
        dsd = DeliveryStationDayFactory(delivery_day=dd, capacity=10)

        # Create 3 HARVEST_SHARE deliveries (each needs unique share_type for variation unique_together)
        for _ in range(3):
            harvest_type = ShareTypeFactory(share_option="HARVEST_SHARE")
            harvest_var = ShareTypeVariationFactory(share_type=harvest_type)
            share = ShareFactory(
                delivery_day=dd,
                share_type_variation=harvest_var,
                year=2026,
                delivery_week=15,
            )
            ShareDeliveryFactory(share=share, delivery_station_day=dsd)

        resp = api_client.get(
            self.URL, {"year": 2026, "delivery_week": 15, "num_weeks": 1}
        )
        entry = next(e for e in resp.data if e["id"] == str(dsd.id))
        assert entry["capacity_by_week"]["2026-15"]["occupied"] == 3
        assert entry["capacity_by_week"]["2026-15"]["free"] == 7

    def test_capacity_counts_fruit_shares(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=4)
        dsd = DeliveryStationDayFactory(delivery_day=dd, capacity=5)

        for _ in range(2):
            fruit_type = ShareTypeFactory(share_option="HARVEST_SHARE_FRUIT")
            fruit_var = ShareTypeVariationFactory(share_type=fruit_type)
            share = ShareFactory(
                delivery_day=dd,
                share_type_variation=fruit_var,
                year=2026,
                delivery_week=15,
            )
            ShareDeliveryFactory(share=share, delivery_station_day=dsd)

        resp = api_client.get(
            self.URL, {"year": 2026, "delivery_week": 15, "num_weeks": 1}
        )
        entry = next(e for e in resp.data if e["id"] == str(dsd.id))
        assert entry["capacity_by_week"]["2026-15"]["occupied"] == 2
        assert entry["capacity_by_week"]["2026-15"]["free"] == 3

    def test_capacity_excludes_other_share_types(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=5)
        dsd = DeliveryStationDayFactory(delivery_day=dd, capacity=10)

        # HARVEST_SHARE counts
        harvest_type = ShareTypeFactory(share_option="HARVEST_SHARE")
        harvest_var = ShareTypeVariationFactory(share_type=harvest_type)
        share_h = ShareFactory(
            delivery_day=dd,
            share_type_variation=harvest_var,
            year=2026,
            delivery_week=15,
        )
        ShareDeliveryFactory(share=share_h, delivery_station_day=dsd)

        # CHICKEN_SHARE does NOT count
        chicken_type = ShareTypeFactory(share_option="CHICKEN_SHARE")
        chicken_var = ShareTypeVariationFactory(share_type=chicken_type)
        share_c = ShareFactory(
            delivery_day=dd,
            share_type_variation=chicken_var,
            year=2026,
            delivery_week=15,
        )
        ShareDeliveryFactory(share=share_c, delivery_station_day=dsd)

        resp = api_client.get(
            self.URL, {"year": 2026, "delivery_week": 15, "num_weeks": 1}
        )
        entry = next(e for e in resp.data if e["id"] == str(dsd.id))
        assert entry["capacity_by_week"]["2026-15"]["occupied"] == 1  # only harvest
        assert entry["capacity_by_week"]["2026-15"]["free"] == 9

    def test_capacity_different_week_not_counted(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=0)
        dsd = DeliveryStationDayFactory(delivery_day=dd, capacity=10)

        harvest_type = ShareTypeFactory(share_option="HARVEST_SHARE")
        harvest_var = ShareTypeVariationFactory(share_type=harvest_type)
        # Delivery in week 16
        share = ShareFactory(
            delivery_day=dd,
            share_type_variation=harvest_var,
            year=2026,
            delivery_week=16,
        )
        ShareDeliveryFactory(share=share, delivery_station_day=dsd)

        # Query for week 15 — should be empty
        resp = api_client.get(
            self.URL, {"year": 2026, "delivery_week": 15, "num_weeks": 1}
        )
        entry = next(e for e in resp.data if e["id"] == str(dsd.id))
        assert entry["capacity_by_week"]["2026-15"]["occupied"] == 0
        assert entry["capacity_by_week"]["2026-15"]["free"] == 10


# ---------------------------------------------------------------------------
# DeliveryToursViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryToursViewSet:
    URL = reverse("delivery_tours-list")

    def test_list_requires_delivery_day(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_with_delivery_day(self, api_client, tenant):
        dd = SharesDeliveryDayFactory(day_number=1)
        DeliveryStationDayFactory(delivery_day=dd, tour_number=1, stop_order=1)
        resp = api_client.get(self.URL, {"delivery_day": str(dd.id)})
        assert resp.status_code == status.HTTP_200_OK
