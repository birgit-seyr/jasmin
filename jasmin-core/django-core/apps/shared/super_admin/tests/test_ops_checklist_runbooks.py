"""The ops-checklist rows the migrations seed in the public schema."""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context

from apps.shared.super_admin.models import OpsChecklistItem


@pytest.mark.django_db
class TestSeededRunbooks:
    def test_every_rotation_has_a_checklist_item(self, _tenant_schema):
        rotations = {
            kind
            for kind, _label in OpsChecklistItem.KIND_CHOICES
            if kind.startswith("rotate_")
        }
        with schema_context("public"):
            seeded = set(OpsChecklistItem.objects.values_list("kind", flat=True))

        assert rotations <= seeded

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("restore_drill", "./scripts/restore_drill.sh"),
            ("csp_audit", "nginx/security_headers.conf"),
            ("rotate_django_secret", "DJANGO_SECRET_KEY_FALLBACK"),
            ("rotate_db_password", "docker compose exec postgres"),
            ("rotate_db_password", "APP_DB_PASSWORD"),
            ("rotate_backup_encryption_key", "old key"),
            ("rotate_bunny_token", "BUNNY_ORIGIN_SECRET_NEXT"),
            ("rotate_bunny_token", "./scripts/validate_gateway_config.sh"),
        ],
    )
    def test_runbook_names_the_current_procedure(self, _tenant_schema, kind, expected):
        with schema_context("public"):
            descriptions = list(
                OpsChecklistItem.objects.filter(kind=kind).values_list(
                    "description", flat=True
                )
            )

        assert any(expected in description for description in descriptions)
