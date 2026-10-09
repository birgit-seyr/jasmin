"""Retired tenant settings: gone from the API, accepted and ignored on write.

``require_admin_approval_for_gdpr_deletion`` (every deletion request waits for
an admin's approval anyway) and ``uses_pledge_round`` (nothing reads it) are no
longer model fields, but their columns stay with a database default so that a
kept release which still reads and writes them keeps working. A frontend built
before the retirement echoes them back on every autosave, so a write carrying
them must still save what else it changes.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.utils import timezone

from apps.shared.tenants.models import TenantSettings

RETIRED = ("require_admin_approval_for_gdpr_deletion", "uses_pledge_round")


def _ensure_settings(tenant) -> TenantSettings:
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults={"valid_from": timezone.now() - datetime.timedelta(days=365)},
    )
    return settings


def _put(api_client, tenant, settings_payload):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_payload},
        format="json",
    )


def _stored_retired_values(settings_id: str) -> tuple[bool, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT require_admin_approval_for_gdpr_deletion, uses_pledge_round "
            "FROM tenants_tenantsettings WHERE id = %s",
            [settings_id],
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def test_retired_settings_are_not_model_fields():
    field_names = {field.name for field in TenantSettings._meta.fields}
    assert field_names.isdisjoint(RETIRED)


@pytest.mark.django_db
class TestRetiredSettingsOnWrite:
    def test_write_carrying_retired_keys_saves_the_other_changes(
        self, api_client, tenant
    ):
        current = _ensure_settings(tenant)
        new_terms = 21 if current.payment_terms_reseller_in_days != 21 else 22

        resp = _put(
            api_client,
            tenant,
            {
                "payment_terms_reseller_in_days": new_terms,
                "require_admin_approval_for_gdpr_deletion": False,
                "uses_pledge_round": True,
            },
        )

        assert resp.status_code == 200, resp.data
        assert resp.data["settings"]["payment_terms_reseller_in_days"] == new_terms
        for key in RETIRED:
            assert key not in resp.data["settings"]

    def test_new_version_keeps_the_old_defaults_in_the_retired_columns(
        self, api_client, tenant
    ):
        _ensure_settings(tenant)

        resp = _put(
            api_client,
            tenant,
            {
                "require_admin_approval_for_gdpr_deletion": False,
                "uses_pledge_round": True,
            },
        )

        assert resp.status_code == 200, resp.data
        new_version = TenantSettings.objects.get(tenant=tenant, valid_until=None)
        assert _stored_retired_values(new_version.id) == (True, False)


@pytest.mark.django_db
def test_settings_list_leaves_the_retired_settings_out(api_client, tenant):
    _ensure_settings(tenant)

    resp = api_client.get("/api/tenants/settings/")

    assert resp.status_code == 200
    assert resp.data
    for key in RETIRED:
        assert key not in resp.data[0]
