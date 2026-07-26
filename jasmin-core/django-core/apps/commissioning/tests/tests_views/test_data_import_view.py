"""HTTP (multipart) tests for the data-list CSV import endpoint.

The import *logic* is covered service-side in
``tests_services/test_data_import_service.py`` +
``tests_services/test_subscription_import.py``. THIS file exercises the actual
``POST /api/commissioning/data_import/`` boundary — multipart parsing, the
office-only permission, ``dry_run``, and the JSON response shape — by uploading
the very sample CSVs shipped under ``fixtures/import_samples/`` (the same files
the office downloads/uses to try the upload by hand). Keep the samples and these
expectations in sync.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
import time_machine
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.models import (
    CoopShare,
    Member,
    PaymentCycle,
    Subscription,
)
from apps.commissioning.models.choices import PaymentCycleOptions
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
)

_SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "import_samples"
URL = reverse("data_import")

# The subscription sample's valid_from is 2026-01-05 (a Monday); freeze there so
# the fixed dates stay valid (Monday/Sunday) and the variation is active.
_FROZEN = datetime.date(2026, 1, 5)


def _upload(sample_name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        sample_name,
        (_SAMPLES / sample_name).read_bytes(),
        content_type="text/csv",
    )


@pytest.mark.django_db
class TestMemberSampleUpload:
    def test_office_uploads_member_sample(self, api_client):
        resp = api_client.post(
            URL,
            {"model_name": "member", "file": _upload("members_sample.csv")},
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["model_name"] == "member"
        assert body["successful"] == 3, body["errors"]
        assert body["failed"] == 0
        assert Member.objects.filter(email="ada.lovelace@example.org").exists()
        # Imported members land unconfirmed — the office confirms them after.
        assert not Member.objects.get(email="ada.lovelace@example.org").admin_confirmed

    def test_dry_run_previews_but_persists_nothing(self, api_client):
        resp = api_client.post(
            URL,
            {
                "model_name": "member",
                "file": _upload("members_sample.csv"),
                "dry_run": "true",
            },
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 3
        assert Member.objects.count() == 0

    def test_anonymous_is_rejected(self, anon_client):
        resp = anon_client.post(
            URL,
            {"model_name": "member", "file": _upload("members_sample.csv")},
            format="multipart",
        )
        assert resp.status_code in (401, 403)
        assert Member.objects.count() == 0

    def test_member_role_is_rejected(self, member_user):
        client = APIClient()
        client.force_authenticate(user=member_user)
        resp = client.post(
            URL,
            {"model_name": "member", "file": _upload("members_sample.csv")},
            format="multipart",
        )
        assert resp.status_code in (401, 403)
        assert Member.objects.count() == 0


@pytest.mark.django_db
class TestSubscriptionSampleUpload:
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    def _reference_data(self) -> None:
        """Create the natural keys ``subscriptions_sample.csv`` references."""
        MemberFactory(member_number=1001)
        MemberFactory(member_number=1002)
        share_type = ShareTypeFactory(name="Standard")
        ShareTypeVariationFactory(share_type=share_type, size="M")
        ShareTypeVariationFactory(share_type=share_type, size="L")
        PaymentCycle.objects.get_or_create(choice=PaymentCycleOptions.MONTHLY)
        DeliveryStationDayFactory(
            delivery_station__short_name="CENTER",
            delivery_day__day_number=2,
        )

    def test_office_uploads_subscription_sample(self, api_client):
        self._reference_data()
        resp = api_client.post(
            URL,
            {
                "model_name": "subscription",
                "file": _upload("subscriptions_sample.csv"),
            },
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 2, body["errors"]
        assert body["failed"] == 0
        # Both land as unconfirmed drafts, wired to the resolved FKs.
        draft = Subscription.objects.get(subscription_number=5001)
        assert draft.admin_confirmed is False
        assert draft.member.member_number == 1001
        assert draft.share_type_variation.size == "M"
        assert draft.payment_cycle.choice == PaymentCycleOptions.MONTHLY
        assert draft.default_delivery_station_day is not None

    def test_missing_reference_data_is_per_row_errors_not_a_crash(self, api_client):
        # No reference data created → every FK fails to resolve, but the upload
        # still returns 200 with per-row errors (never a 500 / batch abort).
        resp = api_client.post(
            URL,
            {
                "model_name": "subscription",
                "file": _upload("subscriptions_sample.csv"),
            },
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 0
        assert body["failed"] == 2
        assert Subscription.objects.count() == 0


@pytest.mark.django_db
class TestCoopShareSampleUpload:
    def test_office_uploads_coop_share_sample(self, api_client):
        MemberFactory(member_number=1001)
        MemberFactory(member_number=1002)
        resp = api_client.post(
            URL,
            {"model_name": "coop_share", "file": _upload("coop_shares_sample.csv")},
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 2, body["errors"]
        assert body["failed"] == 0
        share = CoopShare.objects.get(member__member_number=1002)
        assert share.is_increase is True
        # Unconfirmed — the office confirms through the normal (GenG) flow.
        assert share.admin_confirmed is False
