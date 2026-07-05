"""API-level tests for the subscription waiting list — the exact office/member
HTTP flows, through the real serializers and viewsets.

Covers the reported bug ("a waiting_list create lands in the main Abos list and can
be admin-confirmed"): flag survival through POST /abos/, the on_waiting_list
list filter, the confirm-time capacity backstop, promotion after a slot frees,
PATCH flag-flip coherence, and the by-design non-harvest capacity exemption.
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.models import (
    CapacityReservation,
    ShareDelivery,
    Subscription,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory
from apps.commissioning.tests.factories.shares import (
    ShareTypeVariationGrossPriceFactory,
)

DAY_NUMBER = 2  # Wednesday — matches SharesDeliveryDayFactory default
# Far-future Monday..Sunday one-week term: clears any tenant lead-time floor.
VALID_FROM = datetime.date(2026, 9, 7)
VALID_UNTIL = datetime.date(2026, 9, 13)

ABOS_URL = reverse("abos-list")


def _make_dsd(*, capacity=None, delivery_day=None):
    if delivery_day is None:
        delivery_day = SharesDeliveryDayFactory(day_number=DAY_NUMBER)
    return DeliveryStationDayFactory(delivery_day=delivery_day, capacity=capacity)


def _occupy_slot(dsd):
    """Hold one slot at ``dsd`` for the test term via an active reservation."""
    share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
    variation = ShareTypeVariationFactory(share_type=share_type)
    occupier = SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        valid_from=VALID_FROM,
        valid_until=VALID_UNTIL,
    )
    year, week = SubscriptionService._get_delivery_weeks(
        VALID_FROM, VALID_UNTIL, DAY_NUMBER
    )[0]
    return CapacityReservation.objects.create(
        subscription=occupier,
        delivery_station_day=dsd,
        year=year,
        week=week,
        expires_at=timezone.now() + datetime.timedelta(days=1),
    )


def _payload(member, variation, dsd, **overrides):
    data = {
        "member": str(member.id),
        "share_type_variation": str(variation.id),
        "valid_from": VALID_FROM.isoformat(),
        "valid_until": VALID_UNTIL.isoformat(),
        "quantity": 1,
        "price_per_delivery": "10.00",
        "payment_cycle": str(PaymentCycleFactory().id),
        "default_delivery_station_day": str(dsd.id),
        "is_trial": False,
    }
    data.update(overrides)
    return data


def _harvest_variation():
    share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
    return ShareTypeVariationFactory(share_type=share_type)


@pytest.mark.django_db
class TestWaitingListCreateApi:
    def test_office_create_with_flag_waiting_lists(self, api_client, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)

        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd, on_waiting_list=True),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get(id=resp.data["id"])
        assert subscription.on_waiting_list is True
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.PENDING
        )
        assert subscription.waiting_list_position == 1
        assert not CapacityReservation.objects.filter(
            subscription=subscription
        ).exists()

    def test_office_create_without_flag_on_full_station_409(self, api_client, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)

        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd),
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "delivery_station.over_capacity"

    def test_list_filter_separates_waiting_listed(self, api_client, tenant):
        dsd = _make_dsd(capacity=5)
        waiting_listed = SubscriptionFactory(
            default_delivery_station_day=dsd,
            valid_from=VALID_FROM,
            valid_until=VALID_UNTIL,
            on_waiting_list=True,
        )
        normal = SubscriptionFactory(
            default_delivery_station_day=dsd,
            valid_from=VALID_FROM,
            valid_until=VALID_UNTIL,
        )

        listed_false = api_client.get(ABOS_URL, {"on_waiting_list": "false"})
        listed_true = api_client.get(ABOS_URL, {"on_waiting_list": "true"})
        listed_all = api_client.get(ABOS_URL)

        ids_false = {row["id"] for row in listed_false.data}
        ids_true = {row["id"] for row in listed_true.data}
        ids_all = {row["id"] for row in listed_all.data}

        # The main Abos page filters on_waiting_list=false — a waiting_listed row
        # must NEVER appear there (the reported bug's first symptom).
        assert str(waiting_listed.id) not in ids_false
        assert str(normal.id) in ids_false
        assert str(waiting_listed.id) in ids_true
        assert str(normal.id) not in ids_true
        assert {str(waiting_listed.id), str(normal.id)} <= ids_all

    def test_member_subscribe_with_flag_waiting_lists(self, member_user, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        member = MemberFactory(user=member_user)
        variation = _harvest_variation()
        ShareTypeVariationGrossPriceFactory(share_type_variation=variation)

        client = APIClient()
        client.force_authenticate(user=member_user)
        resp = client.post(
            reverse("my_subscriptions_subscribe"),
            {
                "share_type_variation": str(variation.id),
                "quantity": 1,
                "payment_cycle": str(PaymentCycleFactory().id),
                "valid_from": VALID_FROM.isoformat(),
                "valid_until": VALID_UNTIL.isoformat(),
                "default_delivery_station_day": str(dsd.id),
                "on_waiting_list": True,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get(id=resp.data["id"])
        assert subscription.member_id == member.id
        assert subscription.on_waiting_list is True
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.PENDING
        )
        assert not CapacityReservation.objects.filter(
            subscription=subscription
        ).exists()


@pytest.mark.django_db
class TestWaitingListConfirmApi:
    def test_confirm_while_full_is_409_and_stays_waiting_listed(
        self, api_client, tenant
    ):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd, on_waiting_list=True),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        sub_id = resp.data["id"]

        confirm = api_client.post(reverse("abos-confirm", kwargs={"pk": sub_id}))

        assert confirm.status_code == status.HTTP_409_CONFLICT, confirm.data
        assert confirm.data["code"] == "delivery_station.over_capacity"
        subscription = Subscription.objects.get(id=sub_id)
        assert subscription.admin_confirmed is False
        assert subscription.on_waiting_list is True
        assert not ShareDelivery.objects.filter(subscription=subscription).exists()

    def test_confirm_after_slot_freed_promotes(self, api_client, tenant):
        dsd = _make_dsd(capacity=1)
        blocking_hold = _occupy_slot(dsd)
        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd, on_waiting_list=True),
            format="json",
        )
        sub_id = resp.data["id"]

        blocking_hold.delete()
        confirm = api_client.post(reverse("abos-confirm", kwargs={"pk": sub_id}))

        assert confirm.status_code == status.HTTP_200_OK, confirm.data
        subscription = Subscription.objects.get(id=sub_id)
        assert subscription.admin_confirmed is True
        assert subscription.on_waiting_list is False
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.CONFIRMED
        )
        assert ShareDelivery.objects.filter(subscription=subscription).exists()


@pytest.mark.django_db
class TestWaitingListPatchFlipApi:
    """Flipping on_waiting_list on a DRAFT via PATCH must keep the whole
    waiting_list state coherent (flag vs status vs position vs reservations)."""

    def test_patch_flip_to_waiting_listed_enqueues_and_releases_holds(
        self, api_client, tenant
    ):
        dsd = _make_dsd(capacity=5)
        created = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd),
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        sub_id = created.data["id"]
        assert CapacityReservation.objects.filter(subscription_id=sub_id).exists()

        patched = api_client.patch(
            reverse("abos-detail", kwargs={"pk": sub_id}),
            {"on_waiting_list": True},
            format="json",
        )

        assert patched.status_code == status.HTTP_200_OK, patched.data
        subscription = Subscription.objects.get(id=sub_id)
        assert subscription.on_waiting_list is True
        assert (
            subscription.waiting_list_status == Subscription.WaitingListStatus.PENDING
        )
        assert subscription.waiting_list_position is not None
        # A waiting_list entry holds NO capacity — the draft's reservation must go.
        assert not CapacityReservation.objects.filter(subscription_id=sub_id).exists()

    def test_patch_flip_off_waiting_list_requires_capacity(self, api_client, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        created = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd, on_waiting_list=True),
            format="json",
        )
        sub_id = created.data["id"]

        patched = api_client.patch(
            reverse("abos-detail", kwargs={"pk": sub_id}),
            {"on_waiting_list": False},
            format="json",
        )

        # The station is still full: leaving the waiting list must be refused,
        # otherwise the flip silently overbooks the station.
        assert patched.status_code == status.HTTP_409_CONFLICT, patched.data
        subscription = Subscription.objects.get(id=sub_id)
        assert subscription.on_waiting_list is True

    def test_patch_flip_off_waiting_list_with_capacity_reserves_and_clears(
        self, api_client, tenant
    ):
        dsd = _make_dsd(capacity=5)
        created = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd, on_waiting_list=True),
            format="json",
        )
        sub_id = created.data["id"]

        patched = api_client.patch(
            reverse("abos-detail", kwargs={"pk": sub_id}),
            {"on_waiting_list": False},
            format="json",
        )

        assert patched.status_code == status.HTTP_200_OK, patched.data
        subscription = Subscription.objects.get(id=sub_id)
        assert subscription.on_waiting_list is False
        assert (
            subscription.waiting_list_status
            == Subscription.WaitingListStatus.NOT_ON_LIST
        )
        assert subscription.waiting_list_position is None
        assert CapacityReservation.objects.filter(subscription_id=sub_id).exists()


@pytest.mark.django_db
class TestNonHarvestCapacityExemption:
    """Station capacity counts HARVEST boxes only — other share options bypass
    the reservation AND the confirm backstop BY DESIGN (a bread share doesn't
    occupy a harvest slot). Pin that semantic so a change is deliberate."""

    def test_non_harvest_create_succeeds_on_harvest_full_station(
        self, api_client, tenant
    ):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        share_type = ShareTypeFactory(share_option="BREAD_SHARE")
        variation = ShareTypeVariationFactory(share_type=share_type)

        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), variation, dsd),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get(id=resp.data["id"])
        assert subscription.on_waiting_list is False
