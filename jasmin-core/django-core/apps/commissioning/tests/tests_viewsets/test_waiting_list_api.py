"""API-level tests for the subscription waiting list — the exact office/member
HTTP flows, through the real serializers and viewsets.

Covers the reported bug ("a waiting_list create lands in the main Abos list and can
be admin-confirmed"): flag survival through POST /abos/, the on_waiting_list
list filter, the confirm-time capacity backstop, promotion after a slot frees,
PATCH flag-flip coherence, and the by-design additional-share capacity exemption.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
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
from apps.shared.tenants.models import TenantSettings

DAY_NUMBER = 2  # Wednesday — matches SharesDeliveryDayFactory default
# Far-future Monday..Sunday one-week term: clears any tenant lead-time floor.
VALID_FROM = datetime.date(2026, 9, 7)
VALID_UNTIL = datetime.date(2026, 9, 13)


@pytest.fixture(autouse=True)
def _frozen_today():
    """Freeze "today" to 2026-07-20 (ISO week 30) so ``VALID_FROM`` (2026-09-07)
    stays comfortably beyond the 2-week subscription lead time regardless of the
    wall clock. Without this the suite rots once the real clock reaches ~2 weeks
    before 2026-09-07 (``SubscriptionStartTooSoon`` → 400 masks the expected
    409/response).
    """
    with time_machine.travel(datetime.datetime(2026, 7, 20, 12, 0), tick=False):
        yield


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
class TestAdditionalShareCapacityExemption:
    """Station capacity counts STANDALONE boxes only — ADDITIONAL (packed-along)
    shares bypass the reservation AND the confirm backstop BY DESIGN (an add-on
    rides in another box and takes no slot). Pin that semantic so a change is
    deliberate."""

    def test_additional_share_create_succeeds_on_full_station(self, api_client, tenant):
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)
        member = MemberFactory()
        # An add-on ("Zusatz") may only be created when the member already holds
        # a base share for the same period (base-coverage guard). The factory
        # base bypasses the capacity gate, so the full station below still only
        # tests the ADD-ON's exemption.
        SubscriptionFactory(
            member=member,
            share_type_variation=_harvest_variation(),
            default_delivery_station_day=dsd,
            valid_from=VALID_FROM,
            valid_until=VALID_UNTIL,
        )
        share_type = ShareTypeFactory(
            share_option="BREAD_SHARE", is_additional_share_type=True
        )
        variation = ShareTypeVariationFactory(share_type=share_type)

        resp = api_client.post(
            ABOS_URL,
            _payload(member, variation, dsd),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get(id=resp.data["id"])
        assert subscription.on_waiting_list is False


@pytest.mark.django_db
class TestWaitingListStatusReadOnly:
    """``waiting_list_status`` is stamped only by the service / mixin — a client
    must not be able to forge it via the generic serializer (that would bypass
    the ``allows_waiting_list_for_subscriptions`` gate, which only fires on the
    ``on_waiting_list`` flip, and could even skew variation capacity)."""

    def test_client_waiting_list_status_is_ignored_on_create(self, api_client, tenant):
        dsd = _make_dsd(capacity=5)  # not full → a normal create
        resp = api_client.post(
            ABOS_URL,
            _payload(
                MemberFactory(),
                _harvest_variation(),
                dsd,
                waiting_list_status="confirmed",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get(id=resp.data["id"])
        # The forged status is ignored — the row is a normal, not-queued draft.
        assert (
            subscription.waiting_list_status
            == Subscription.WaitingListStatus.NOT_ON_LIST
        )
        assert subscription.on_waiting_list is False


def _disable_waiting_list(tenant):
    TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        allows_waiting_list_for_subscriptions=False,
    )


@pytest.mark.django_db
class TestWaitingListDisabled:
    """With ``allows_waiting_list_for_subscriptions=False`` the tenant has no
    waiting list: an ``on_waiting_list=True`` create is refused, and a full
    station still 409s (no waiting-list fallback)."""

    def test_create_with_flag_rejected(self, api_client, tenant):
        _disable_waiting_list(tenant)
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)

        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd, on_waiting_list=True),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "waiting_list.disabled"
        assert not Subscription.objects.filter(on_waiting_list=True).exists()

    def test_full_station_still_409_without_flag(self, api_client, tenant):
        _disable_waiting_list(tenant)
        dsd = _make_dsd(capacity=1)
        _occupy_slot(dsd)

        resp = api_client.post(
            ABOS_URL,
            _payload(MemberFactory(), _harvest_variation(), dsd),
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "delivery_station.over_capacity"
