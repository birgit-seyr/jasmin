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

import csv
import datetime
from pathlib import Path

import pytest
import time_machine
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.models import (
    CoopShare,
    Crate,
    DeliveryStation,
    Member,
    PaymentCycle,
    Reseller,
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
        assert body["successful"] == 4, body["errors"]
        assert body["failed"] == 0
        assert Member.objects.filter(email="ada.lovelace@example.org").exists()
        # Imported members land unconfirmed — the office confirms them after.
        assert not Member.objects.get(email="ada.lovelace@example.org").admin_confirmed
        # The sample's departed member keeps their historical Austrittsdatum,
        # and the derived ``cancelled_at`` keeps them out of the active-member
        # queries (which all filter ``cancelled_at__isnull=True``).
        departed = Member.objects.get(email="edsger.dijkstra@example.org")
        assert departed.cancelled_effective_at == datetime.date(2023, 12, 31)
        assert departed.cancelled_at is not None

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
        assert resp.json()["successful"] == 4
        assert Member.objects.count() == 0

    @pytest.mark.parametrize("raw", ["false", "0"])
    def test_explicit_false_dry_run_persists(self, api_client, raw):
        """``dry_run`` is parsed, not truth-tested — the multipart part arrives
        as a string, so a truthy cast would preview instead of importing."""
        resp = api_client.post(
            URL,
            {
                "model_name": "member",
                "file": _upload("members_sample.csv"),
                "dry_run": raw,
            },
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 4
        assert Member.objects.count() == 4

    def test_unparseable_dry_run_is_400(self, api_client):
        resp = api_client.post(
            URL,
            {
                "model_name": "member",
                "file": _upload("members_sample.csv"),
                "dry_run": "maybe",
            },
            format="multipart",
        )
        assert resp.status_code == 400, resp.content
        assert resp.json()["code"] == "query.invalid_param"
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


_BANK_IBAN = "DE89370400440532013000"


def _member_csv_with_bank_columns(layout: str) -> SimpleUploadedFile:
    """One member row carrying ``iban`` + ``account_owner``, as the three-row
    download template or as a hand-rolled header + data CSV."""
    fields = (
        "first_name,last_name,email,address,zip_code,city,country,iban,account_owner"
    )
    row = (
        "Ada,Lovelace,ada.bank@example.org,1 Analytical Way,8000,Zurich,CH,"
        f"{_BANK_IBAN},Ada Lovelace"
    )
    if layout == "template":
        rows = [
            "First name,Last name,Email,Address,ZIP,City,Country,IBAN,Account owner",
            fields,
            "text,text,email,text,text,text,text,text,text",
            row,
        ]
    else:
        rows = [fields, row]
    return SimpleUploadedFile(
        "members_bank.csv", ("\n".join(rows) + "\n").encode(), content_type="text/csv"
    )


@pytest.mark.django_db
class TestBankColumnsRequireStepUp:
    """A real import whose schema row names a bank column writes IBANs, so it
    needs the same fresh step-up claim as the interactive IBAN writes. A dry run
    persists nothing and stays open to a plain office session."""

    @pytest.mark.parametrize("layout", ["template", "two_row"])
    def test_real_import_without_step_up_is_refused(self, api_client, layout):
        resp = api_client.post(
            URL,
            {"model_name": "member", "file": _member_csv_with_bank_columns(layout)},
            format="multipart",
        )
        assert resp.status_code == 403, resp.content
        assert resp.json()["code"] == "auth.step_up_required"
        assert Member.objects.count() == 0

    def test_dry_run_without_step_up_is_allowed(self, api_client):
        resp = api_client.post(
            URL,
            {
                "model_name": "member",
                "file": _member_csv_with_bank_columns("template"),
                "dry_run": "true",
            },
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 1, resp.json()["errors"]
        assert Member.objects.count() == 0

    def test_real_import_with_step_up_imports(self, step_up_client):
        resp = step_up_client.post(
            URL,
            {"model_name": "member", "file": _member_csv_with_bank_columns("template")},
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 1, resp.json()["errors"]
        member = Member.objects.get(email="ada.bank@example.org")
        assert member.iban == _BANK_IBAN
        assert member.account_owner == "Ada Lovelace"

    def test_unknown_model_is_a_400_not_a_step_up_prompt(self, api_client):
        resp = api_client.post(
            URL,
            {"model_name": "nope", "file": _member_csv_with_bank_columns("template")},
            format="multipart",
        )
        assert resp.status_code == 400, resp.content
        assert resp.json()["code"] == "data_import.invalid"


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


_RESELLER_CSV = (
    "Company,Address,ZIP,City,Reseller,Customer number\n"
    "company_name,address,zip_code,city,is_reseller,customer_number\n"
    "string,string,string,string,true|false,integer\n"
    "Kern Farm Shop,4 Market Lane,8010,Graz,true,4711\n"
)

_DELIVERY_STATION_CSV = (
    "Short name,Company,Address,ZIP,City\n"
    "short_name,company_name,address,zip_code,city\n"
    "string,string,string,string,string\n"
    "CENTER,Community Center,12 Main Street,8020,Graz\n"
)


def _inline_upload(name: str, content: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content.encode(), content_type="text/csv")


@pytest.mark.django_db
class TestResellerAndDeliveryStationUpload:
    """Both models keep their address block on a linked ``ContactEntity``, which
    only the create service knows how to split off. The upload must land the
    same rows the office create form does."""

    def test_office_uploads_resellers(self, api_client):
        resp = api_client.post(
            URL,
            {
                "model_name": "reseller",
                "file": _inline_upload("resellers.csv", _RESELLER_CSV),
            },
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 1, body["errors"]
        assert body["failed"] == 0
        reseller = Reseller.objects.get(customer_number=4711)
        assert reseller.contact.company_name == "Kern Farm Shop"
        assert reseller.contact.city == "Graz"

    def test_office_uploads_delivery_stations(self, api_client):
        resp = api_client.post(
            URL,
            {
                "model_name": "delivery_station",
                "file": _inline_upload("stations.csv", _DELIVERY_STATION_CSV),
            },
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 1, body["errors"]
        assert body["failed"] == 0
        station = DeliveryStation.objects.get(short_name="CENTER")
        assert station.contact.address == "12 Main Street"


@pytest.mark.django_db
class TestOversizedUpload:
    def test_a_file_past_the_byte_cap_is_refused_naming_the_field(self, api_client):
        """The row cap bounds parsing, not memory — the bytes and their decoded
        copy are already resident by the time it applies. An export nobody
        meant to upload has to be refused on its size first."""
        over_the_cap = "A" * (10 * 1024 * 1024 + 1024)
        content = f"Name,Number\nname,number\ntext,int\n{over_the_cap},1\n"

        resp = api_client.post(
            URL,
            {"model_name": "crate", "file": _inline_upload("crates.csv", content)},
            format="multipart",
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "data_import.invalid"
        assert body["field"] == "file"
        assert not Crate.objects.exists()


@pytest.mark.django_db
class TestUnreadableRowUpload:
    def test_a_cell_the_parser_refuses_is_a_reported_row_not_a_500(self, api_client):
        """A stray quote running past csv's field limit used to escape the
        per-row handling; the office must get the row number back instead."""
        oversized = '"' + "x" * (csv.field_size_limit() + 10) + '"'
        content = (
            "Name,Number\n"
            "name,number\n"
            "text,int\n"
            "GoodOne,1\n"
            f"{oversized},2\n"
            "GoodTwo,3\n"
        )

        resp = api_client.post(
            URL,
            {"model_name": "crate", "file": _inline_upload("crates.csv", content)},
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 2, body["errors"]
        assert body["failed"] == 1
        assert body["errors"][0]["row"] == 5
        assert Crate.objects.filter(name__in=["GoodOne", "GoodTwo"]).count() == 2
