"""Tests for the Art-17 deletion PREVIEW (dry-run) — roadmap Step 5.

Covers persona detection (Member / Customer / Staff), the ``preview_deletion``
payload shape + fidelity to ``FIELD_CLASSIFICATION`` and the retention check,
the "writes nothing" guarantee, and the admin-only endpoint (200 / 403 / 404).
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
)
from apps.gdpr.services import GDPRService, Persona


def _models_by_label(preview: dict) -> dict[str, dict]:
    return {m["model"]: m for m in preview["models"]}


@pytest.mark.django_db
class TestDetectPersona:
    def test_member_is_member_persona(self, tenant):
        user = JasminUserFactory(roles=["member"])
        MemberFactory(user=user)
        assert GDPRService.detect_persona(user) is Persona.MEMBER

    def test_reseller_only_is_customer_persona(self, tenant):
        user = JasminUserFactory(roles=["member"])
        ResellerFactory(linked_user=user)
        assert GDPRService.detect_persona(user) is Persona.CUSTOMER

    def test_no_member_no_reseller_is_staff_persona(self, tenant):
        user = JasminUserFactory(roles=["office"])
        assert GDPRService.detect_persona(user) is Persona.STAFF

    def test_member_who_is_also_reseller_is_member_persona(self, tenant):
        # The stricter registry obligation governs — MEMBER wins the label.
        user = JasminUserFactory(roles=["member"])
        MemberFactory(user=user)
        ResellerFactory(linked_user=user)
        assert GDPRService.detect_persona(user) is Persona.MEMBER


@pytest.mark.django_db
class TestPreviewDeletionShape:
    def test_staff_preview_lists_jasmin_user_fields_and_can_delete(self, tenant):
        user = JasminUserFactory(roles=["office"], email="clerk@example.com")

        preview = GDPRService.preview_deletion(user)

        assert preview["persona"] == "staff"
        assert preview["has_member"] is False
        assert preview["has_reseller"] is False
        assert preview["can_anonymize_now"] is True
        assert preview["retention_blocks"] == []

        models = _models_by_label(preview)
        assert "accounts.JasminUser" in models
        scrubbed = {
            f["field"] for f in models["accounts.JasminUser"]["scrubbed_fields"]
        }
        assert {"email", "first_name", "last_name"} <= scrubbed
        assert preview["field_count"] >= len(scrubbed)
        assert preview["model_count"] == len(preview["models"])

    def test_member_preview_includes_member_model(self, tenant):
        user = JasminUserFactory(roles=["member"])
        MemberFactory(user=user)

        preview = GDPRService.preview_deletion(user)

        assert preview["persona"] == "member"
        assert preview["has_member"] is True
        models = _models_by_label(preview)
        assert "commissioning.Member" in models
        # The Member scrub list carries a known TOMBSTONE + a PII_IMMEDIATE.
        member_fields = {
            f["field"]: f["action"]
            for f in models["commissioning.Member"]["scrubbed_fields"]
        }
        assert member_fields.get("first_name") == "tombstone"
        assert member_fields.get("email") == "pii_immediate"

    def test_customer_preview_includes_reseller_model(self, tenant):
        user = JasminUserFactory(roles=["member"])
        ResellerFactory(linked_user=user)

        preview = GDPRService.preview_deletion(user)

        assert preview["persona"] == "customer"
        assert preview["has_reseller"] is True
        assert "commissioning.Reseller" in _models_by_label(preview)

    def test_side_channels_present(self, tenant):
        user = JasminUserFactory(roles=["office"])
        preview = GDPRService.preview_deletion(user)
        targets = {c["target"] for c in preview["side_channels"]}
        # auditlog + axes always; sepa/reseller only when the persona applies.
        assert {"auditlog", "axes"} <= targets
        assert "sepa_export" not in targets  # no member


@pytest.mark.django_db
class TestPreviewRetentionSurfacing:
    def test_open_coop_share_blocks_and_is_surfaced(self, tenant):
        user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)  # open share → retention block

        preview = GDPRService.preview_deletion(user)

        assert preview["can_anonymize_now"] is False
        assert preview["retention_blocks"], "expected a CoopShare retention block"
        assert any("CoopShare" in reason for reason in preview["retention_blocks"])


@pytest.mark.django_db
class TestPreviewWritesNothing:
    def test_preview_does_not_mutate_the_user_or_member(self, tenant):
        user = JasminUserFactory(roles=["member"], email="real@example.com")
        member = MemberFactory(user=user, first_name="Realname")

        GDPRService.preview_deletion(user)

        user.refresh_from_db()
        member.refresh_from_db()
        assert user.email == "real@example.com"
        assert member.first_name == "Realname"


@pytest.mark.django_db
class TestPreviewEndpoint:
    def _url(self, user_id: str) -> str:
        return reverse("gdpr-admin-preview-deletion", kwargs={"user_id": user_id})

    def test_admin_gets_preview(self, tenant):
        admin = JasminUserFactory(roles=["admin"])
        target = JasminUserFactory(roles=["member"])
        MemberFactory(user=target)

        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.get(self._url(str(target.id)))

        assert resp.status_code == 200
        assert resp.data["persona"] == "member"
        assert resp.data["user_id"] == str(target.id)
        assert "commissioning.Member" in {m["model"] for m in resp.data["models"]}
        assert "can_anonymize_now" in resp.data

    def test_non_admin_forbidden(self, tenant):
        member_user = JasminUserFactory(roles=["member"])
        target = JasminUserFactory(roles=["member"])

        client = APIClient()
        client.force_authenticate(user=member_user)
        resp = client.get(self._url(str(target.id)))

        assert resp.status_code == 403

    def test_unknown_user_id_404(self, tenant):
        admin = JasminUserFactory(roles=["admin"])
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.get(self._url("does-not-exist"))
        assert resp.status_code == 404
