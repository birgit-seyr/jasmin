"""``update_current_settings`` writes model fields, not arbitrary attributes.

The endpoint reads ``request.data["settings"]`` raw — no input serializer — so
only concrete editable model fields may be assigned. An ``hasattr`` test would
also pass for the FK attname (``tenant_id``), which repoints the row at another
tenant, and for every method on the model (``save``, ``copy``, ``full_clean``),
where a payload value shadowing the method turns the write into a TypeError —
a 500 for what is really bad input. A payload that is not an object at all
fails the same way, one step earlier.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework import status

from apps.shared.tenants.models import TenantSettings

_PAYLOAD_CODE = "tenant_settings.invalid_payload"


def _ensure_settings(tenant, **overrides):
    defaults = dict(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(days=365),
        valid_until=None,
    )
    defaults.update(overrides)
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant, valid_until=None, defaults=defaults
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    settings.save()
    return settings


def _put(api_client, tenant, payload):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        payload,
        format="json",
    )


def _current(tenant) -> TenantSettings:
    return TenantSettings.objects.get(tenant=tenant, valid_until=None)


@pytest.mark.django_db
class TestSettingsPayloadShape:
    @pytest.mark.parametrize(
        "settings_value",
        ["not-an-object", ["a", "b"], 5, True],
        ids=["string", "list", "number", "boolean"],
    )
    def test_non_object_settings_is_rejected(self, api_client, tenant, settings_value):
        _ensure_settings(tenant)
        resp = _put(api_client, tenant, {"settings": settings_value})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert resp.data["code"] == _PAYLOAD_CODE
        assert resp.data["field"] == "settings"

    def test_no_new_version_is_written_for_a_bad_payload(self, api_client, tenant):
        _ensure_settings(tenant)
        before = _current(tenant).id

        _put(api_client, tenant, {"settings": "not-an-object"})

        assert _current(tenant).id == before


@pytest.mark.django_db
class TestSettingsWriteAllowlist:
    def test_tenant_id_is_not_writable(self, api_client, tenant):
        _ensure_settings(tenant)

        resp = _put(api_client, tenant, {"settings": {"tenant_id": "someone-else"}})

        assert resp.status_code == status.HTTP_200_OK, resp.data
        # Exactly one open version, still owned by the calling tenant.
        assert (
            TenantSettings.objects.filter(
                tenant=tenant, valid_until__isnull=True
            ).count()
            == 1
        )
        assert _current(tenant).tenant_id == tenant.id

    @pytest.mark.parametrize("method_name", ["save", "copy", "full_clean"])
    def test_a_model_method_name_is_not_writable(self, api_client, tenant, method_name):
        _ensure_settings(tenant)

        resp = _put(api_client, tenant, {"settings": {method_name: "clobbered"}})

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert method_name not in resp.data["settings"]
        assert callable(getattr(_current(tenant), method_name))

    def test_an_unknown_key_is_ignored_and_real_fields_still_apply(
        self, api_client, tenant
    ):
        _ensure_settings(tenant, payment_terms_reseller_in_days=14)

        resp = _put(
            api_client,
            tenant,
            {
                "settings": {
                    "not_a_setting_at_all": "whatever",
                    "payment_terms_reseller_in_days": 21,
                }
            },
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["settings"]["payment_terms_reseller_in_days"] == 21
        assert "not_a_setting_at_all" not in resp.data["settings"]
        assert _current(tenant).payment_terms_reseller_in_days == 21
