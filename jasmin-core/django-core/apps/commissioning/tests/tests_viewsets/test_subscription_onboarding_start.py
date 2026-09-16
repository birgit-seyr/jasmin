"""Onboarding mode and the subscription start lead time.

``SubscriptionSerializer`` refuses a ``valid_from`` inside the tenant's lead
time (``subscription.start_too_soon``). While ``TenantSettings.onboarding_mode``
is on, ``SubscriptionViewSet`` lets office writes skip only that check, so the
office can enter subscriptions that are already running. Member self-service
keeps the lead time, and the end-date requirement stays.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from apps.commissioning.errors import SubscriptionStartTooSoon
from apps.commissioning.models import Subscription
from apps.commissioning.serializers import SubscriptionSerializer
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    ShareTypeVariationGrossPriceFactory,
    SubscriptionFactory,
)
from apps.commissioning.viewsets.members_viewsets import SubscriptionViewSet
from apps.shared.tenants.models import TenantSettings

ABOS_URL = reverse("abos-list")
SELF_SUBSCRIBE_URL = reverse("my_subscriptions_subscribe")
# With the frozen Monday 2026-07-20 and a two-week lead time the earliest start
# is 2026-08-03; this Monday is seven weeks in the past.
PAST_MONDAY = datetime.date(2026, 6, 1)
FUTURE_MONDAY = datetime.date(2026, 9, 7)
TERM_END = datetime.date(2026, 12, 27)  # a Sunday


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 20, 12, 0), tick=False):
        yield


def _set_tenant_settings(tenant, *, onboarding_mode: bool) -> None:
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    elif row.valid_from > timezone.now():
        # The frozen clock sits before a row opened in real time; move its start
        # back so ``get_current_settings`` sees it.
        row.valid_from = timezone.now() - datetime.timedelta(days=365)
    row.onboarding_mode = onboarding_mode
    row.min_weeks_from_creation_to_start_delivery = 2
    row.save()


@pytest.fixture()
def onboarding_mode(tenant):
    _set_tenant_settings(tenant, onboarding_mode=True)


@pytest.fixture()
def onboarding_mode_off(tenant):
    _set_tenant_settings(tenant, onboarding_mode=False)


@pytest.fixture()
def variation(tenant):
    variation = ShareTypeVariationFactory(
        share_type=ShareTypeFactory(share_option="HARVEST_SHARE")
    )
    ShareTypeVariationGrossPriceFactory(share_type_variation=variation)
    return variation


@pytest.fixture()
def station_day(tenant):
    return DeliveryStationDayFactory()


def _payload(variation, station_day, **overrides) -> dict:
    data = {
        "member": str(MemberFactory().id),
        "share_type_variation": str(variation.id),
        "valid_from": PAST_MONDAY.isoformat(),
        "valid_until": TERM_END.isoformat(),
        "quantity": 1,
        "price_per_delivery": "10.00",
        "payment_cycle": str(PaymentCycleFactory().id),
        "default_delivery_station_day": str(station_day.id),
        "is_trial": False,
    }
    data.update(overrides)
    return data


def _request_for(user) -> Request:
    request = Request(APIRequestFactory().post("/"))
    request.user = user
    return request


@pytest.mark.django_db
class TestOfficeStartFlagOff:
    def test_create_inside_the_lead_time_is_refused(
        self, api_client, onboarding_mode_off, variation, station_day
    ):
        resp = api_client.post(
            ABOS_URL, _payload(variation, station_day), format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.start_too_soon"

    def test_patch_to_a_past_start_is_refused(
        self, api_client, onboarding_mode_off, variation, station_day
    ):
        draft = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=station_day,
            valid_from=FUTURE_MONDAY,
            valid_until=TERM_END,
        )
        resp = api_client.patch(
            reverse("abos-detail", kwargs={"pk": draft.pk}),
            {"valid_from": PAST_MONDAY.isoformat()},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.start_too_soon"


@pytest.mark.django_db
class TestOfficeStartFlagOn:
    def test_create_with_a_past_start_is_accepted(
        self, api_client, onboarding_mode, variation, station_day
    ):
        resp = api_client.post(
            ABOS_URL, _payload(variation, station_day), format="json"
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        subscription = Subscription.objects.get(id=resp.data["id"])
        assert subscription.valid_from == PAST_MONDAY
        assert subscription.admin_confirmed is False

    def test_patch_to_a_past_start_is_accepted(
        self, api_client, onboarding_mode, variation, station_day
    ):
        draft = SubscriptionFactory(
            share_type_variation=variation,
            default_delivery_station_day=station_day,
            valid_from=FUTURE_MONDAY,
            valid_until=TERM_END,
        )
        resp = api_client.patch(
            reverse("abos-detail", kwargs={"pk": draft.pk}),
            {"valid_from": PAST_MONDAY.isoformat()},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        draft.refresh_from_db()
        assert draft.valid_from == PAST_MONDAY

    def test_end_date_is_still_required(
        self, api_client, onboarding_mode, variation, station_day
    ):
        payload = _payload(variation, station_day)
        del payload["valid_until"]
        resp = api_client.post(ABOS_URL, payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.open_ended_not_allowed"

    def test_member_self_subscribe_keeps_the_lead_time(
        self, member_user, onboarding_mode, variation, station_day
    ):
        MemberFactory(user=member_user)
        client = APIClient()
        client.force_authenticate(user=member_user)
        resp = client.post(
            SELF_SUBSCRIBE_URL,
            {
                "share_type_variation": str(variation.id),
                "quantity": 1,
                "payment_cycle": str(PaymentCycleFactory().id),
                "valid_from": PAST_MONDAY.isoformat(),
                "valid_until": TERM_END.isoformat(),
                "default_delivery_station_day": str(station_day.id),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "subscription.start_too_soon"
        assert not Subscription.objects.filter(member__user=member_user).exists()


@pytest.mark.django_db
class TestSerializerLeadTimeSkip:
    def test_office_request_with_onboarding_mode_skips_the_lead_time(
        self, onboarding_mode, variation, station_day
    ):
        serializer = SubscriptionSerializer(
            data=_payload(variation, station_day),
            context={
                "request": _request_for(JasminUserFactory(roles=["office"])),
                "onboarding_mode": True,
            },
        )
        assert serializer.is_valid(), serializer.errors

    def test_member_request_with_onboarding_mode_keeps_the_lead_time(
        self, onboarding_mode, variation, station_day
    ):
        serializer = SubscriptionSerializer(
            data=_payload(variation, station_day),
            context={
                "request": _request_for(JasminUserFactory(roles=["member"])),
                "onboarding_mode": True,
            },
        )
        with pytest.raises(SubscriptionStartTooSoon):
            serializer.is_valid()

    def test_office_request_without_onboarding_mode_keeps_the_lead_time(
        self, onboarding_mode, variation, station_day
    ):
        serializer = SubscriptionSerializer(
            data=_payload(variation, station_day),
            context={"request": _request_for(JasminUserFactory(roles=["office"]))},
        )
        with pytest.raises(SubscriptionStartTooSoon):
            serializer.is_valid()


@pytest.mark.django_db
class TestSubscriptionViewSetContext:
    @pytest.mark.parametrize("action", ["create", "update", "partial_update"])
    @pytest.mark.parametrize("enabled", [False, True])
    def test_writes_carry_the_flag(self, tenant, action, enabled):
        _set_tenant_settings(tenant, onboarding_mode=enabled)
        view = SubscriptionViewSet(action=action, format_kwarg=None)
        view.request = _request_for(JasminUserFactory(roles=["office"]))
        assert view.get_serializer_context()["onboarding_mode"] is enabled

    @pytest.mark.parametrize("action", ["list", "retrieve", "confirm"])
    def test_other_actions_leave_it_out(self, onboarding_mode, action):
        view = SubscriptionViewSet(action=action, format_kwarg=None)
        view.request = _request_for(JasminUserFactory(roles=["office"]))
        assert "onboarding_mode" not in view.get_serializer_context()

    def test_schema_generation_leaves_it_out(self, onboarding_mode):
        view = SubscriptionViewSet(
            action="create", format_kwarg=None, swagger_fake_view=True
        )
        view.request = _request_for(JasminUserFactory(roles=["office"]))
        assert "onboarding_mode" not in view.get_serializer_context()
