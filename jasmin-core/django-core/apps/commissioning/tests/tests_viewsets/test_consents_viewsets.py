"""HTTP-layer tests for the consent viewsets.

These tests prove the access matrix that an auditor will actually
care about: who can see what, who can write what, who can be
spoofed. The model + service tests in tests_models / tests_services
cover the data invariants — these cover the policy.

Access matrix locked in below:

  ConsentDocument
    list / retrieve / current   anonymous + member + office  →  200
    create / update / destroy   anonymous + member           →  403
                                office                        →  201/200/204

  ConsentRecord
    list                        anonymous                    →  401/403
                                member                       →  200 (own only)
                                office                       →  200 (all + ?member=)
    create                      anonymous                    →  401/403
                                member (no payload member)   →  201, pinned to self
                                member (payload says other)  →  403
                                office (payload says X)      →  201 for X
    revoke                      anonymous                    →  401/403
                                non-owning member            →  404 (scoped out)
                                owning member                →  200
                                office                       →  200
    destroy                     anonymous / member           →  401/403
                                office                       →  204
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.models import (
    ConsentDocument,
    ConsentKind,
    ConsentRecord,
    Member,
)
from apps.commissioning.tests.factories import MemberFactory

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_doc(
    *,
    kind: str = ConsentKind.PRIVACY,
    locale: str = "de",
    version: str = "v1",
    valid_from: datetime.date | None = None,
    body: str = "We process your data lawfully.",
) -> ConsentDocument:
    return ConsentDocument.objects.create(
        kind=kind,
        locale=locale,
        version=version,
        valid_from=valid_from or datetime.date(2026, 1, 1),
        body=body,
    )


def _authed_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def member_client(tenant, member_user):
    """APIClient authed as a member-role JasminUser that ALSO has a
    Member profile attached (needed for ``own_member_id`` lookups
    inside consent endpoints)."""
    member = MemberFactory(user=member_user)
    client = _authed_client(member_user)
    # Stash for convenience — tests need both the client and the
    # member to assert "scoped to own".
    client._test_member = member  # type: ignore[attr-defined]
    return client


# --------------------------------------------------------------------------- #
# ConsentDocument — read access (public)                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentDocumentReadAccess:
    """The registration wizard fetches documents anonymously; staff
    also need to list them. None of the read endpoints touch member
    PII, so they're ``AllowAny`` via ``public_read_actions``."""

    URL_LIST = reverse("consent_document-list")

    def test_anonymous_can_list(self, anon_client, tenant):
        _make_doc()
        resp = anon_client.get(self.URL_LIST)
        assert resp.status_code == status.HTTP_200_OK

    def test_anonymous_can_retrieve(self, anon_client, tenant):
        doc = _make_doc()
        resp = anon_client.get(reverse("consent_document-detail", args=[doc.pk]))
        assert resp.status_code == status.HTTP_200_OK

    def test_anonymous_can_call_current(self, anon_client, tenant):
        doc = _make_doc()
        resp = anon_client.get(
            reverse("consent_document-current"),
            {"kind": "privacy", "locale": "de"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == doc.pk

    def test_current_returns_404_when_no_document_exists(self, anon_client, tenant):
        resp = anon_client.get(
            reverse("consent_document-current"),
            {"kind": "privacy", "locale": "de"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_office_can_list(self, api_client, tenant):
        _make_doc()
        resp = api_client.get(self.URL_LIST)
        assert resp.status_code == status.HTTP_200_OK

    def test_member_can_list(self, member_client, tenant):
        _make_doc()
        resp = member_client.get(self.URL_LIST)
        assert resp.status_code == status.HTTP_200_OK


# --------------------------------------------------------------------------- #
# ConsentDocument — write access (office only)                                #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentDocumentWriteAccess:
    URL_LIST = reverse("consent_document-list")

    BASE_PAYLOAD = {
        "kind": "privacy",
        "locale": "de",
        "version": "v2",
        "valid_from": "2026-06-01",
        "body": "Updated text",
    }

    def test_anonymous_cannot_create(self, anon_client, tenant):
        resp = anon_client.post(self.URL_LIST, self.BASE_PAYLOAD, format="json")
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_member_cannot_create(self, member_client, tenant):
        resp = member_client.post(self.URL_LIST, self.BASE_PAYLOAD, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_can_create(self, api_client, tenant):
        resp = api_client.post(self.URL_LIST, self.BASE_PAYLOAD, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["kind"] == "privacy"
        # body_sha256 + can_be_deleted come back in the response — that's
        # the DeletableMixin + auto-hash wiring working end-to-end.
        assert "body_sha256" in resp.data
        assert resp.data["can_be_deleted"] is True

    def test_member_cannot_delete(self, member_client, tenant):
        doc = _make_doc()
        resp = member_client.delete(reverse("consent_document-detail", args=[doc.pk]))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_can_delete_unused_document(self, api_client, tenant):
        doc = _make_doc()
        resp = api_client.delete(reverse("consent_document-detail", args=[doc.pk]))
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    def test_office_cannot_delete_referenced_document(self, api_client, tenant):
        """Append-only invariant at the HTTP layer: once a member has
        consented, the document is locked. Returns 409 via
        ``ConsentDocumentInUse`` (translated from ``ProtectedError``)."""
        doc = _make_doc()
        member = MemberFactory()
        ConsentRecord.objects.create(member=member, document=doc)

        resp = api_client.delete(reverse("consent_document-detail", args=[doc.pk]))
        assert resp.status_code == status.HTTP_409_CONFLICT


# --------------------------------------------------------------------------- #
# ConsentRecord — create                                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentRecordCreate:
    URL_LIST = reverse("consent_record-list")

    def test_anonymous_cannot_create(self, anon_client, tenant):
        doc = _make_doc()
        resp = anon_client.post(self.URL_LIST, {"document_id": doc.pk}, format="json")
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_member_create_pins_to_self_even_without_member_in_payload(
        self, member_client, tenant
    ):
        """A member-role caller POST'ing without a ``member`` field
        must get the consent attached to THEIR own Member id
        (via ``own_member_id`` server-side)."""
        doc = _make_doc()
        resp = member_client.post(self.URL_LIST, {"document_id": doc.pk}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        own_member: Member = member_client._test_member  # type: ignore[attr-defined]
        assert resp.data["member"] == own_member.pk

    def test_member_cannot_record_consent_for_another_member(
        self, member_client, tenant
    ):
        """Spoofing check: a member POST'ing with someone else's
        ``member`` id must be rejected — otherwise any logged-in
        member could fabricate consents for any other member."""
        doc = _make_doc()
        someone_else = MemberFactory()
        resp = member_client.post(
            self.URL_LIST,
            {"document_id": doc.pk, "member": someone_else.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_office_can_record_on_behalf_of_a_member(self, api_client, tenant):
        doc = _make_doc()
        target = MemberFactory()
        resp = api_client.post(
            self.URL_LIST,
            {"document_id": doc.pk, "member": target.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["member"] == target.pk

    def test_ip_address_is_captured_from_x_forwarded_for(self, member_client, tenant):
        """Cookies + nginx + gunicorn pipeline: the gateway appends the real
        client IP to ``X-Forwarded-For`` (``$proxy_add_x_forwarded_for``,
        TRUSTED_PROXY_COUNT=1), so the recorded consent IP must be the LAST
        entry — NOT the client-supplied, spoofable first one."""
        doc = _make_doc()
        resp = member_client.post(
            self.URL_LIST,
            {"document_id": doc.pk},
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        # 203.0.113.7 is the client-supplied (spoofable) entry; 10.0.0.1 is the
        # gateway-appended real client IP that must be the one recorded.
        assert resp.data["ip_address"] == "10.0.0.1"

    def test_user_agent_is_captured(self, member_client, tenant):
        doc = _make_doc()
        resp = member_client.post(
            self.URL_LIST,
            {"document_id": doc.pk},
            format="json",
            HTTP_USER_AGENT="Mozilla/5.0 RegistrationWizard/1.0",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert "RegistrationWizard" in resp.data["user_agent"]

    def test_unknown_document_returns_404(self, member_client, tenant):
        resp = member_client.post(
            self.URL_LIST,
            {"document_id": "does-not-exist"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# --------------------------------------------------------------------------- #
# ConsentRecord — list (scoping)                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentRecordListScoping:
    URL_LIST = reverse("consent_record-list")

    def test_anonymous_cannot_list(self, anon_client, tenant):
        resp = anon_client.get(self.URL_LIST)
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_member_sees_only_own_consents(self, member_client, tenant):
        own_member: Member = member_client._test_member  # type: ignore[attr-defined]
        other_member = MemberFactory()
        doc = _make_doc()
        ConsentRecord.objects.create(member=own_member, document=doc)
        ConsentRecord.objects.create(member=other_member, document=doc)

        resp = member_client.get(self.URL_LIST)
        assert resp.status_code == status.HTTP_200_OK
        member_ids = {row["member"] for row in resp.data}
        assert member_ids == {own_member.pk}

    def test_office_sees_all_consents(self, api_client, tenant):
        m1 = MemberFactory()
        m2 = MemberFactory()
        doc = _make_doc()
        ConsentRecord.objects.create(member=m1, document=doc)
        ConsentRecord.objects.create(member=m2, document=doc)

        resp = api_client.get(self.URL_LIST)
        assert resp.status_code == status.HTTP_200_OK
        member_ids = {row["member"] for row in resp.data}
        assert {m1.pk, m2.pk}.issubset(member_ids)

    def test_office_member_filter_narrows_to_that_member(self, api_client, tenant):
        m1 = MemberFactory()
        m2 = MemberFactory()
        doc = _make_doc()
        ConsentRecord.objects.create(member=m1, document=doc)
        ConsentRecord.objects.create(member=m2, document=doc)

        resp = api_client.get(self.URL_LIST, {"member": m1.pk})
        assert resp.status_code == status.HTTP_200_OK
        member_ids = {row["member"] for row in resp.data}
        assert member_ids == {m1.pk}


# --------------------------------------------------------------------------- #
# ConsentRecord — revoke                                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentRecordRevoke:
    @staticmethod
    def _revoke_url(record_id) -> str:
        return reverse("consent_record-revoke", args=[record_id])

    def test_anonymous_cannot_revoke(self, anon_client, tenant):
        member = MemberFactory()
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=member, document=doc)

        resp = anon_client.post(self._revoke_url(record.pk), {}, format="json")
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_owning_member_can_revoke_own_consent(self, member_client, tenant):
        own_member: Member = member_client._test_member  # type: ignore[attr-defined]
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=own_member, document=doc)

        resp = member_client.post(
            self._revoke_url(record.pk),
            {"reason": "I changed my mind"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        record.refresh_from_db()
        assert record.revoked_at is not None
        assert record.revoked_reason == "I changed my mind"

    def test_member_cannot_revoke_other_members_consent(self, member_client, tenant):
        """``scope_to_member`` filters the queryset before ``get_object``
        runs, so the foreign record is invisible — DRF returns 404,
        not 403 (don't leak existence)."""
        someone_else = MemberFactory()
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=someone_else, document=doc)

        resp = member_client.post(self._revoke_url(record.pk), {}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_office_can_revoke_any_consent(self, api_client, tenant):
        member = MemberFactory()
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=member, document=doc)

        resp = api_client.post(
            self._revoke_url(record.pk),
            {"reason": "Office revoked on member request"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        record.refresh_from_db()
        assert record.revoked_at is not None

    def test_double_revoke_returns_conflict(self, api_client, tenant):
        member = MemberFactory()
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=member, document=doc)

        first = api_client.post(self._revoke_url(record.pk), {}, format="json")
        assert first.status_code == status.HTTP_200_OK

        second = api_client.post(self._revoke_url(record.pk), {}, format="json")
        assert second.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestConsentRecordDestroy:
    """Consent records are an append-only legal / GDPR audit trail. Members
    withdraw via the soft ``revoke`` action (preserves the row); only office
    may hard-delete (e.g. an erroneous entry). A member hard-deleting their
    own record would erase proof-of-consent — SEC-BE-2."""

    def test_member_cannot_hard_delete_own_consent(self, member_client, tenant):
        own_member: Member = member_client._test_member  # type: ignore[attr-defined]
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=own_member, document=doc)
        url = reverse("consent_record-detail", args=[record.pk])

        resp = member_client.delete(url)

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        # The audit row must survive the rejected delete.
        assert ConsentRecord.objects.filter(pk=record.pk).exists()

    def test_office_can_delete_consent(self, api_client, tenant):
        member = MemberFactory()
        doc = _make_doc()
        record = ConsentRecord.objects.create(member=member, document=doc)
        url = reverse("consent_record-detail", args=[record.pk])

        resp = api_client.delete(url)

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not ConsentRecord.objects.filter(pk=record.pk).exists()


# --------------------------------------------------------------------------- #
# ConsentDocument PDF download (WeasyPrint, generate-once + store)            #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentDocumentPDFDownload:
    URL_NAME = "consent_document-download-pdf"

    @patch("apps.commissioning.services.consent_pdf.render_consent_pdf")
    def test_download_renders_stores_then_serves_cached(
        self, mock_render, api_client, tenant
    ):
        mock_render.return_value = ContentFile(b"%PDF-1.4 fake")
        doc = _make_doc()
        assert not doc.pdf
        url = reverse(self.URL_NAME, kwargs={"pk": doc.pk})

        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"] == "application/pdf"
        doc.refresh_from_db()
        assert doc.pdf  # stored on first access
        assert mock_render.call_count == 1

        # Second download serves the stored file — idempotent, no re-render.
        resp2 = api_client.get(url)
        assert resp2.status_code == status.HTTP_200_OK
        assert mock_render.call_count == 1

    @patch("apps.commissioning.services.consent_pdf.render_consent_pdf")
    def test_download_is_public(self, mock_render, anon_client, tenant):
        # The PDF is the same public policy text as retrieve (no member data).
        mock_render.return_value = ContentFile(b"%PDF-1.4 fake")
        doc = _make_doc()
        resp = anon_client.get(reverse(self.URL_NAME, kwargs={"pk": doc.pk}))
        assert resp.status_code == status.HTTP_200_OK

    def test_ensure_pdf_real_render(self, tenant):
        # Actually exercise WeasyPrint (skips cleanly where its native libs
        # aren't present, e.g. a minimal CI image).
        doc = _make_doc(body="<h1>Datenschutz</h1><p>ä ö ü ß</p>")
        try:
            doc.ensure_pdf()
        except OSError as exc:
            pytest.skip(f"WeasyPrint native libs unavailable: {exc}")
        doc.refresh_from_db()
        assert doc.pdf
        with doc.pdf.open("rb") as handle:
            assert handle.read(5).startswith(b"%PDF")
