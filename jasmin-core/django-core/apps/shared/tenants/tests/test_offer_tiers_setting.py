"""``used_tiers_for_offers`` is a list of quantity thresholds.

``update_current_settings`` setattr's raw values onto the new settings version,
so the model field validators are the only thing standing between the payload
and the stored JSON. A string survives the client's "are tiers configured?"
test (it has a length) and then mis-prices every offer line, while a tier row
the office has added but not filled in yet is a legitimate ``null``.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework import status

from apps.shared.tenants.models import TenantSettings

INVALID_VALUE_CODE = "tenant_settings.invalid_value"


def _ensure_settings(tenant) -> TenantSettings:
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults={
            "tenant": tenant,
            "valid_from": timezone.now() - datetime.timedelta(days=365),
            "valid_until": None,
        },
    )
    return settings


def _put(api_client, tenant, tiers):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": {"used_tiers_for_offers": tiers}},
        format="json",
    )


def _current(tenant) -> TenantSettings:
    return TenantSettings.objects.get(tenant=tenant, valid_until=None)


@pytest.mark.django_db
class TestOfferTiersSetting:
    @pytest.mark.parametrize(
        "tiers",
        ["3", {"1": 3}, [0], [-2], ["3"], [True]],
        ids=["string", "object", "zero", "negative", "string-entry", "boolean-entry"],
    )
    def test_a_value_that_is_not_a_tier_list_is_refused(
        self, api_client, tenant, tiers
    ):
        _ensure_settings(tenant)

        response = _put(api_client, tenant, tiers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data["code"] == INVALID_VALUE_CODE
        assert response.data["field"] == "used_tiers_for_offers"
        assert _current(tenant).used_tiers_for_offers != tiers

    def test_a_refused_value_writes_no_new_version(self, api_client, tenant):
        _ensure_settings(tenant)
        before = _current(tenant).id

        _put(api_client, tenant, "3")

        assert _current(tenant).id == before

    @pytest.mark.parametrize(
        "tiers",
        [[], [1], [1, 3, 5], [1, None]],
        ids=["empty", "single", "three-tiers", "tier-added-not-yet-filled-in"],
    )
    def test_a_real_tier_list_is_accepted(self, api_client, tenant, tiers):
        """The tier editor appends a ``null`` row on "add tier" and saves
        immediately, so a half-filled list has to keep saving."""
        _ensure_settings(tenant)

        response = _put(api_client, tenant, tiers)

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _current(tenant).used_tiers_for_offers == tiers
