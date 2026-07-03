"""BL-12: ``update_current_settings`` must reject an inverted coop-share
window (``min_number_coop_shares > max_number_coop_shares``) — an
unsatisfiable range that would soft-brick coop-share saves + admin
confirmation for the tenant."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework import status

from apps.shared.tenants.models import TenantSettings

_CODE = "tenant_settings.coop_shares_bounds_inverted"


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
    for k, v in overrides.items():
        setattr(settings, k, v)
    settings.save()
    return settings


def _update_settings(api_client, tenant, **settings_kwargs):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_kwargs},
        format="json",
    )


@pytest.mark.django_db
class TestCoopShareBoundsSetting:
    def test_inverted_min_max_rejected(self, api_client, tenant):
        _ensure_settings(tenant, min_number_coop_shares=3, max_number_coop_shares=100)
        resp = _update_settings(
            api_client, tenant, min_number_coop_shares=50, max_number_coop_shares=10
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == _CODE

    def test_valid_min_max_allowed(self, api_client, tenant):
        _ensure_settings(tenant, min_number_coop_shares=3, max_number_coop_shares=100)
        resp = _update_settings(
            api_client, tenant, min_number_coop_shares=5, max_number_coop_shares=20
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_equal_min_max_allowed(self, api_client, tenant):
        _ensure_settings(tenant, min_number_coop_shares=3, max_number_coop_shares=100)
        resp = _update_settings(
            api_client, tenant, min_number_coop_shares=5, max_number_coop_shares=5
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_lowering_max_below_existing_min_rejected(self, api_client, tenant):
        # Update only max, against an existing higher min — the effective
        # window is still inverted and must be rejected.
        _ensure_settings(tenant, min_number_coop_shares=20, max_number_coop_shares=100)
        resp = _update_settings(api_client, tenant, max_number_coop_shares=10)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == _CODE
