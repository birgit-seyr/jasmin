"""Tests for ``GET /api/gdpr/processing-activities/`` — the Art. 30
Record-of-Processing-Activities export endpoint.

Contract:

  * IsAdmin-gated (matches the rest of the office-facing GDPR
    endpoints).
  * Returns a stable payload shape: ``schema_version``,
    ``doc_reference``, ``generated_at``, ``controller``,
    ``processors``, ``activities``, ``technical_organisational_measures``.
  * The ``controller`` block is populated from the live ``Tenant``
    row — name, address (joined), email, phone are filled in;
    fields the platform doesn't store (legal_form, DPO,
    supervisory_authority) come back as empty strings rather than
    being omitted, so the auditor sees the gap explicitly.
  * Every activity in ``vvt.ACTIVITIES`` appears in the response,
    keyed by ``key`` (== string), with every field a non-empty
    string. ``code_locations`` is a non-empty list of paths.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.gdpr.vvt import ACTIVITIES, CONTROLLER_FIELDS, PROCESSORS, TOMS


def _admin_client() -> tuple[APIClient, object]:
    admin = JasminUserFactory(roles=["admin"])
    client = APIClient()
    client.force_authenticate(user=admin)
    return client, admin


URL = reverse("gdpr-processing-activities")


@pytest.mark.django_db
class TestProcessingActivitiesView:
    def test_requires_admin(self, tenant):
        """The endpoint is IsAdmin-gated. A member-role user
        authenticated session must get 403 — confirms the operational
        Art. 30 export doesn't leak the activity list to every
        logged-in user."""
        member = JasminUserFactory(roles=["member"])
        client = APIClient()
        client.force_authenticate(user=member)
        resp = client.get(URL)
        assert resp.status_code == 403

    def test_response_shape_is_complete(self, tenant):
        """Top-level keys must all be present so an auditor or the
        office UI consumer can rely on the schema without per-key
        defaults."""
        client, _ = _admin_client()
        resp = client.get(URL)
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "schema_version",
            "doc_reference",
            "generated_at",
            "controller",
            "processors",
            "activities",
            "technical_organisational_measures",
        ):
            assert key in body, f"missing top-level key {key!r}"
        # The prose source must be cited so a reader knows where to
        # find narrative context.
        assert body["doc_reference"] == "docs/gdpr/processing-activities.md"

    def test_controller_block_pulls_from_tenant(self, tenant):
        """Address join + email + phone come from the live ``Tenant``
        row. Test sets the fields explicitly then asserts the
        endpoint surfaces them in the controller block."""
        from django.db import connection

        live_tenant = getattr(connection, "tenant", None)
        assert live_tenant is not None
        live_tenant.name = "Beispiel-Solawi"
        live_tenant.address = "Hauptstraße 1"
        live_tenant.zip_code = "12345"
        live_tenant.city = "Berlin"
        live_tenant.country = "Germany"
        live_tenant.email = "info@example.org"
        live_tenant.phone_number = "+49 30 12345678"
        live_tenant.save()

        client, _ = _admin_client()
        body = client.get(URL).json()

        controller = body["controller"]
        # Every CONTROLLER_FIELDS key is present (no auditor-facing
        # gap goes unflagged).
        for key in CONTROLLER_FIELDS:
            assert key in controller, f"missing controller key {key!r}"
        assert controller["organisation_name"] == "Beispiel-Solawi"
        assert "Hauptstraße 1" in controller["registered_address"]
        assert "12345" in controller["registered_address"]
        assert "Berlin" in controller["registered_address"]
        assert "Germany" in controller["registered_address"]
        assert controller["contact_email"] == "info@example.org"
        assert controller["contact_phone"] == "+49 30 12345678"
        # Platform doesn't store these fields → empty strings, NOT
        # missing keys.
        assert controller["legal_form"] == ""
        assert controller["dpo"] == ""
        assert controller["supervisory_authority"] == ""

    def test_activities_match_vvt_constants(self, tenant):
        """The endpoint serialises ``vvt.ACTIVITIES`` faithfully —
        catching a future refactor that accidentally drops or
        re-orders a record."""
        client, _ = _admin_client()
        body = client.get(URL).json()
        activities = body["activities"]
        assert len(activities) == len(ACTIVITIES)
        for shipped, source in zip(activities, ACTIVITIES, strict=True):
            assert shipped["key"] == source.key
            assert shipped["label"] == source.label
            # Spot-check the load-bearing fields the auditor cites
            # straight from the GDPR text.
            for field in (
                "purpose",
                "legal_basis",
                "data_subjects",
                "personal_data",
                "retention",
                "security_measures",
            ):
                assert shipped[field]
                assert isinstance(shipped[field], str)
            assert isinstance(shipped["code_locations"], list)
            assert shipped["code_locations"]

    def test_processors_and_toms_are_present(self, tenant):
        """``PROCESSORS`` and ``TOMS`` are static codebase facts —
        the endpoint surfaces them so the auditor doesn't have to
        cross-reference the prose doc."""
        client, _ = _admin_client()
        body = client.get(URL).json()
        assert len(body["processors"]) == len(PROCESSORS)
        assert len(body["technical_organisational_measures"]) == len(TOMS)
