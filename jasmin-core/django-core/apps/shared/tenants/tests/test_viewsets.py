"""``update_current_settings`` validates the values a request CHANGES.

The configuration pages autosave by echoing the whole fetched settings row
back, so every setting is present in every payload. Validation therefore keys
on the value differing from the locked current version: a stored value that
fails a validator must not block the unrelated setting the caller is editing,
while a value the request actually alters is still checked — including the
blank spellings (``""``, ``{}``) that Django's ``clean_fields`` skips.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework import status

from apps.shared.tenants.models import TenantSettings

INVALID_VALUE_CODE = "tenant_settings.invalid_value"


def _ensure_settings(tenant, **overrides) -> TenantSettings:
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
    # save() runs no validators, which is how a row that predates a stricter
    # rule exists in the first place.
    settings.save()
    return settings


def _put(api_client, tenant, settings_payload):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_payload},
        format="json",
    )


def _current(tenant) -> TenantSettings:
    return TenantSettings.objects.get(tenant=tenant, valid_until=None)


@pytest.mark.django_db
class TestSettingsEchoedValuesAreNotRevalidated:
    def test_an_unrelated_setting_still_saves_with_a_stored_tier_list_that_fails(
        self, api_client, tenant
    ):
        _ensure_settings(
            tenant,
            used_tiers_for_offers=[1, 0],
            payment_terms_reseller_in_days=14,
        )

        response = _put(
            api_client,
            tenant,
            {
                "used_tiers_for_offers": [1, 0],
                "payment_terms_reseller_in_days": 21,
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        current = _current(tenant)
        assert current.payment_terms_reseller_in_days == 21
        # The echoed value is carried forward untouched, not repaired.
        assert current.used_tiers_for_offers == [1, 0]

    def test_a_changed_tier_list_is_still_refused(self, api_client, tenant):
        _ensure_settings(tenant, used_tiers_for_offers=[1, 3])

        response = _put(api_client, tenant, {"used_tiers_for_offers": [1, 0]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data["code"] == INVALID_VALUE_CODE
        assert response.data["field"] == "used_tiers_for_offers"
        assert _current(tenant).used_tiers_for_offers == [1, 3]


@pytest.mark.django_db
class TestOfferTiersBlankSpellings:
    @pytest.mark.parametrize("tiers", [{}, ""], ids=["empty-mapping", "empty-string"])
    def test_a_blank_non_list_is_refused(self, api_client, tenant, tiers):
        _ensure_settings(tenant, used_tiers_for_offers=[1, 3])

        response = _put(api_client, tenant, {"used_tiers_for_offers": tiers})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data["code"] == INVALID_VALUE_CODE
        assert response.data["field"] == "used_tiers_for_offers"
        assert _current(tenant).used_tiers_for_offers == [1, 3]

    @pytest.mark.parametrize("tiers", [[], None], ids=["empty-list", "null"])
    def test_an_empty_tier_list_is_accepted(self, api_client, tenant, tiers):
        """``[]`` and ``null`` are how "no tiers configured" is spelled."""
        _ensure_settings(tenant, used_tiers_for_offers=[1, 3])

        response = _put(api_client, tenant, {"used_tiers_for_offers": tiers})

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _current(tenant).used_tiers_for_offers == tiers
