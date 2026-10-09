"""Step-up gate on high-impact tenant-settings changes.

``TenantSettingsViewSet.update_current_settings`` lets any office user
rewrite tenant config. Changing the billing / SEPA / tax fields or the
onboarding mode is high-impact, so those specific fields demand a fresh
step-up claim — and only when the value actually changes (echoing the
current value is a no-op and must not prompt). A plain office session may
still change benign fields unprompted.
"""

from __future__ import annotations

import pytest

from apps.commissioning.tests.conftest import make_step_up_token
from apps.shared.tenants.models import TenantSettings


def _update(api_client, tenant, **settings_kwargs):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_kwargs},
        format="json",
    )


def _current_collection_day(tenant) -> int:
    current = TenantSettings.get_current_settings(tenant=tenant)
    if current is not None:
        return current.sepa_collection_day_of_month
    return TenantSettings._meta.get_field("sepa_collection_day_of_month").get_default()


@pytest.mark.django_db
class TestSensitiveSettingsStepUp:
    def test_change_sepa_collection_day_without_step_up_is_refused(
        self, api_client, tenant
    ):
        """Refused before any settings version is written."""
        new_day = 15 if _current_collection_day(tenant) != 15 else 16
        resp = _update(api_client, tenant, sepa_collection_day_of_month=new_day)
        assert resp.status_code == 403
        assert resp.data["code"] == "auth.step_up_required"

    def test_change_sepa_collection_day_with_step_up_succeeds(
        self, api_client, user, tenant
    ):
        previous_day = _current_collection_day(tenant)
        new_day = 15 if previous_day != 15 else 16
        api_client.force_authenticate(user=user, token=make_step_up_token(user))
        try:
            resp = _update(api_client, tenant, sepa_collection_day_of_month=new_day)
            assert resp.status_code == 200
            assert resp.data["settings"]["sepa_collection_day_of_month"] == new_day
        finally:
            # The test_pytest tenant is session-scoped and these writes persist
            # across tests; put the previous day back.
            current = TenantSettings.get_current_settings(tenant=tenant)
            if current is not None:
                current.sepa_collection_day_of_month = previous_day
                current.save(update_fields=["sepa_collection_day_of_month"])

    def test_non_sensitive_change_skips_step_up(self, api_client, tenant):
        # ``payment_terms_reseller_in_days`` is not step-up-sensitive, so a
        # plain office session (no step-up claim) changes it unprompted.
        resp = _update(api_client, tenant, payment_terms_reseller_in_days=30)
        assert resp.status_code == 200

    def test_echoing_unchanged_sensitive_value_skips_step_up(self, api_client, tenant):
        # Resending the CURRENT collection day is a no-op — the step-up gate
        # fires only on an actual change, so this passes without a step-up
        # claim.
        resp = _update(
            api_client,
            tenant,
            sepa_collection_day_of_month=_current_collection_day(tenant),
        )
        assert resp.status_code == 200
