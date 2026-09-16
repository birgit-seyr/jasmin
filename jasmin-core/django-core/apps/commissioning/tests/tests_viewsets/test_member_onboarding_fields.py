"""Onboarding mode on the members grid.

``member_number`` and ``entry_date`` are server-stamped by admin confirmation
and read-only on ``MemberSerializer``. While ``TenantSettings.onboarding_mode``
is on, ``MemberViewSet`` serves ``MemberOnboardingSerializer`` for office writes
so both can carry the historical values of members that already exist on paper.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.models import Member
from apps.commissioning.serializers import (
    MemberOnboardingSerializer,
    MemberSerializer,
)
from apps.commissioning.services.onboarding_policy import onboarding_mode_enabled
from apps.commissioning.tests.factories import MemberFactory
from apps.commissioning.viewsets.members_viewsets import MemberViewSet
from apps.shared.tenants.models import TenantSettings

HISTORICAL_ENTRY = datetime.date(2019, 4, 1)
HISTORICAL_NUMBER = 987654


@pytest.fixture(autouse=True)
def _frozen_clock():
    # A Monday away from any year boundary.
    with time_machine.travel(datetime.datetime(2026, 7, 13, 12, 0), tick=False):
        yield


def _set_onboarding_mode(tenant, enabled: bool) -> None:
    row = TenantSettings.objects.filter(tenant=tenant, valid_until__isnull=True).first()
    if row is None:
        row = TenantSettings.objects.create(
            tenant=tenant, valid_from=timezone.now() - datetime.timedelta(days=365)
        )
    elif row.valid_from > timezone.now():
        # The frozen clock sits before a row opened in real time; move its start
        # back so ``get_current_settings`` sees it.
        row.valid_from = timezone.now() - datetime.timedelta(days=365)
    row.onboarding_mode = enabled
    row.save()


@pytest.fixture()
def onboarding_mode(tenant):
    _set_onboarding_mode(tenant, True)
    yield
    _set_onboarding_mode(tenant, False)


@pytest.fixture()
def onboarding_mode_off(tenant):
    _set_onboarding_mode(tenant, False)


def _member_url(member: Member) -> str:
    return reverse("member-detail", kwargs={"pk": member.pk})


def _create_payload(**overrides) -> dict:
    payload = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada.onboarding@example.com",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestOnboardingPolicy:
    def test_setting_defaults_off(self, tenant):
        assert TenantSettings._meta.get_field("onboarding_mode").get_default() is False

    def test_disabled_when_flag_off(self, onboarding_mode_off):
        assert onboarding_mode_enabled() is False

    def test_enabled_when_flag_on(self, onboarding_mode):
        assert onboarding_mode_enabled() is True

    def test_disabled_without_a_settings_row(self, tenant):
        with mock.patch(
            "apps.commissioning.services.onboarding_policy._settings",
            return_value=None,
        ):
            assert onboarding_mode_enabled() is False


@pytest.mark.django_db
class TestMemberSerializerSelection:
    @staticmethod
    def _view(action: str, *, schema: bool = False) -> MemberViewSet:
        view = MemberViewSet()
        view.action = action
        view.request = mock.Mock(user=None)
        if schema:
            view.swagger_fake_view = True
        return view

    @pytest.mark.parametrize("action", ["create", "update", "partial_update"])
    def test_writes_use_onboarding_serializer_when_on(self, onboarding_mode, action):
        assert self._view(action).get_serializer_class() is MemberOnboardingSerializer

    @pytest.mark.parametrize("action", ["create", "update", "partial_update"])
    def test_writes_use_member_serializer_when_off(self, onboarding_mode_off, action):
        assert self._view(action).get_serializer_class() is MemberSerializer

    @pytest.mark.parametrize("action", ["list", "retrieve", "confirm"])
    def test_other_actions_keep_member_serializer_when_on(
        self, onboarding_mode, action
    ):
        assert self._view(action).get_serializer_class() is MemberSerializer

    def test_schema_generation_keeps_member_serializer(self, onboarding_mode):
        view = self._view("partial_update", schema=True)
        assert view.get_serializer_class() is MemberSerializer


@pytest.mark.django_db
class TestMemberNumberAndEntryDateFlagOff:
    def test_patch_drops_member_number(self, api_client, onboarding_mode_off):
        member = MemberFactory(member_number=None)
        resp = api_client.patch(
            _member_url(member),
            {"member_number": HISTORICAL_NUMBER, "note": "edited"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.note == "edited"
        assert member.member_number is None

    def test_patch_drops_entry_date(self, api_client, onboarding_mode_off):
        member = MemberFactory(entry_date=None)
        resp = api_client.patch(
            _member_url(member),
            {"entry_date": HISTORICAL_ENTRY.isoformat(), "note": "edited"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.note == "edited"
        assert member.entry_date is None

    def test_create_drops_both(self, api_client, onboarding_mode_off):
        resp = api_client.post(
            reverse("member-list"),
            _create_payload(
                member_number=HISTORICAL_NUMBER,
                entry_date=HISTORICAL_ENTRY.isoformat(),
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        member = Member.objects.get(email="ada.onboarding@example.com")
        assert member.member_number is None
        assert member.entry_date is None


@pytest.mark.django_db
class TestMemberNumberAndEntryDateFlagOn:
    def test_patch_writes_both(self, api_client, onboarding_mode):
        member = MemberFactory(member_number=None, entry_date=None)
        resp = api_client.patch(
            _member_url(member),
            {
                "member_number": HISTORICAL_NUMBER,
                "entry_date": HISTORICAL_ENTRY.isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.member_number == HISTORICAL_NUMBER
        assert member.entry_date == HISTORICAL_ENTRY

    def test_create_writes_both(self, api_client, onboarding_mode):
        resp = api_client.post(
            reverse("member-list"),
            _create_payload(
                member_number=HISTORICAL_NUMBER,
                entry_date=HISTORICAL_ENTRY.isoformat(),
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["member_number"] == HISTORICAL_NUMBER
        member = Member.objects.get(email="ada.onboarding@example.com")
        assert member.member_number == HISTORICAL_NUMBER
        assert member.entry_date == HISTORICAL_ENTRY

    def test_duplicate_member_number_is_a_clean_400(self, api_client, onboarding_mode):
        MemberFactory(member_number=HISTORICAL_NUMBER)
        member = MemberFactory(member_number=None)
        resp = api_client.patch(
            _member_url(member),
            {"member_number": HISTORICAL_NUMBER},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert "member_number" in resp.data["details"]
        member.refresh_from_db()
        assert member.member_number is None

    def test_member_number_on_existing_trial_member_is_refused(
        self, api_client, onboarding_mode
    ):
        member = MemberFactory(is_trial=True, member_number=None, entry_date=None)
        resp = api_client.patch(
            _member_url(member),
            {"member_number": HISTORICAL_NUMBER},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "member.number_not_allowed_for_trial"
        member.refresh_from_db()
        assert member.member_number is None

    def test_member_number_on_new_trial_member_is_refused(
        self, api_client, onboarding_mode
    ):
        resp = api_client.post(
            reverse("member-list"),
            _create_payload(is_trial=True, member_number=HISTORICAL_NUMBER),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == "member.number_not_allowed_for_trial"
        assert not Member.objects.filter(email="ada.onboarding@example.com").exists()

    def test_trial_member_without_number_still_saves(self, api_client, onboarding_mode):
        member = MemberFactory(is_trial=True, member_number=None, entry_date=None)
        resp = api_client.patch(
            _member_url(member),
            {"member_number": None, "note": "edited"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.note == "edited"
        assert member.member_number is None
