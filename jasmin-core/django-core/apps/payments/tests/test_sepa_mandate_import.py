"""SEPA-mandate CSV import — HTTP upload + create-only semantics.

The mandate importer is a payments serializer (``SepaMandateImportSerializer``)
registered INTO commissioning's data-list registry from
``PaymentsConfig.ready()`` (payments→commissioning is the allowed direction), so
it rides the same ``POST /api/commissioning/data_import/`` endpoint as the other
imports. This exercises that wiring end to end by uploading the shipped sample
CSV (``commissioning/tests/fixtures/import_samples/sepa_mandates_sample.csv``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

# The sample lives with the other import samples in the commissioning tests.
import apps.commissioning.tests as _commissioning_tests
from apps.commissioning.tests.factories import MemberFactory
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile

_SAMPLES = (
    Path(_commissioning_tests.__file__).resolve().parent / "fixtures" / "import_samples"
)
URL = reverse("data_import")


def _upload() -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "sepa_mandates_sample.csv",
        (_SAMPLES / "sepa_mandates_sample.csv").read_bytes(),
        content_type="text/csv",
    )


@pytest.mark.django_db
class TestSepaMandateImport:
    def test_office_uploads_mandate_sample(self, api_client):
        MemberFactory(member_number=1001)
        MemberFactory(member_number=1002)

        resp = api_client.post(
            URL,
            {"model_name": "sepa_mandate", "file": _upload()},
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 2, body["errors"]
        assert body["failed"] == 0

        # Row 1 keeps the imported Mandatsreferenz (continuity with the bank).
        p1 = BillingProfile.objects.get(member__member_number=1001)
        assert p1.payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT
        assert p1.sepa_mandate_reference == "MND-LEGACY-0001"
        assert p1.iban == "CH9300762011623852957"
        assert p1.account_holder == "Ada Lovelace"
        assert p1.is_sepa_ready is True

        # Row 2 left the reference blank → the model minted a fresh one.
        p2 = BillingProfile.objects.get(member__member_number=1002)
        assert p2.sepa_mandate_reference
        assert p2.sepa_mandate_reference != "MND-LEGACY-0001"
        assert p2.sepa_mandate_paper_received_at is None

    def test_dry_run_persists_nothing(self, api_client):
        MemberFactory(member_number=1001)
        MemberFactory(member_number=1002)
        resp = api_client.post(
            URL,
            {
                "model_name": "sepa_mandate",
                "file": _upload(),
                "dry_run": "true",
            },
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 2
        assert BillingProfile.objects.count() == 0

    def test_create_only_skips_member_with_existing_profile(self, api_client):
        # Member 1001 already has a profile → that row is a per-row conflict and
        # is left untouched; member 1002 (no profile) still imports.
        member_1001 = MemberFactory(member_number=1001)
        MemberFactory(member_number=1002)
        existing = BillingProfile.objects.create(
            member=member_1001,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban="CH9300762011623852957",
            account_holder="Existing Holder",
            sepa_mandate_reference="MND-ALREADY-HERE",
            sepa_mandate_signed_at="2020-01-01",
        )

        resp = api_client.post(
            URL,
            {"model_name": "sepa_mandate", "file": _upload()},
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 1
        assert body["failed"] == 1
        assert "already has a billing profile" in body["errors"][0]["error"]

        # The existing mandate was NOT overwritten.
        existing.refresh_from_db()
        assert existing.sepa_mandate_reference == "MND-ALREADY-HERE"
        assert existing.account_holder == "Existing Holder"
        # Member 1002's mandate did import.
        assert BillingProfile.objects.filter(member__member_number=1002).exists()

    def test_unknown_member_is_a_row_error(self, api_client):
        # No members created → both rows fail to resolve, none crash the batch.
        resp = api_client.post(
            URL,
            {"model_name": "sepa_mandate", "file": _upload()},
            format="multipart",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["successful"] == 0
        assert body["failed"] == 2
        assert BillingProfile.objects.count() == 0

    def test_anonymous_is_rejected(self, tenant, anon_client):
        # Permission is checked before any row work, so no members are needed;
        # ``tenant`` just activates the schema for the BillingProfile assertion.
        resp = anon_client.post(
            URL,
            {"model_name": "sepa_mandate", "file": _upload()},
            format="multipart",
        )
        assert resp.status_code in (401, 403)
        assert BillingProfile.objects.count() == 0


@pytest.mark.django_db
class TestSepaMandateMirrorsToMember:
    """The mandate's IBAN / holder are also written to the member's OWN
    encrypted columns.

    ``Member.iban`` / ``Member.account_owner`` are a separate pair from
    ``BillingProfile.iban`` / ``account_holder`` with no syncing between them.
    Only the BillingProfile copy drives collection; the Member copy is what the
    office grid shows, so without this an onboarded member looks half-migrated.
    """

    IBAN = "CH9300762011623852957"

    def _import_one(self, api_client, member_number: int, iban: str | None = None):
        csv = (
            "Member no.,Account holder,IBAN,Ref,Signed,Paper\n"
            "member_number,account_holder,iban,sepa_mandate_reference,"
            "sepa_mandate_signed_at,sepa_mandate_paper_received_at\n"
            "integer,text,text,text,date,date\n"
            f"{member_number},Ada Lovelace,{iban or self.IBAN},,2024-03-04,\n"
        ).encode()
        return api_client.post(
            URL,
            {
                "model_name": "sepa_mandate",
                "file": SimpleUploadedFile("m.csv", csv, content_type="text/csv"),
            },
            format="multipart",
        )

    def test_iban_and_holder_land_on_the_member(self, api_client, tenant):
        member = MemberFactory(member_number=4001)
        assert not member.iban

        resp = self._import_one(api_client, 4001)
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 1, resp.json()["errors"]

        member.refresh_from_db()
        assert member.iban == self.IBAN
        assert member.account_owner == "Ada Lovelace"
        # ...and the mandate copy that actually drives collection is set too.
        profile = BillingProfile.objects.get(member=member)
        assert profile.iban == self.IBAN

    def test_an_existing_member_iban_is_never_overwritten(self, api_client, tenant):
        """Silently rewriting a stored IBAN is what the UI gates behind step-up
        auth — this path has no such check, so it fills only."""
        existing = "DE89370400440532013000"
        member = MemberFactory(member_number=4002, iban=existing)

        resp = self._import_one(api_client, 4002, iban=self.IBAN)
        assert resp.status_code == 200, resp.content
        assert resp.json()["successful"] == 1, resp.json()["errors"]

        member.refresh_from_db()
        assert member.iban == existing, "existing member IBAN must be preserved"
        # The mandate still records what the CSV said — the two legitimately
        # differ here, and the mandate is the one the bank sees.
        assert BillingProfile.objects.get(member=member).iban == self.IBAN

    def test_values_are_encrypted_at_rest(self, api_client, tenant):
        """Both copies are ``EncryptedCharField`` — the raw column must not
        contain the plaintext IBAN."""
        from django.db import connection

        member = MemberFactory(member_number=4003)
        assert self._import_one(api_client, 4003).status_code == 200

        with connection.cursor() as cur:
            cur.execute(
                "SELECT iban FROM commissioning_member WHERE id = %s", [member.pk]
            )
            raw_member = cur.fetchone()[0]
            cur.execute(
                "SELECT iban FROM payments_billingprofile WHERE member_id = %s",
                [member.pk],
            )
            raw_profile = cur.fetchone()[0]

        for raw in (raw_member, raw_profile):
            assert raw, "column should not be empty"
            assert self.IBAN not in str(raw), "plaintext IBAN found in the column!"
