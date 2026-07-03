"""Step-up gate on high-impact tenant-settings changes.

``TenantSettingsViewSet.update_current_settings`` lets any office user
rewrite tenant config. Flipping the GDPR self-service-deletion gate, or
the billing / SEPA / tax fields, is high-impact, so those specific fields
demand a fresh step-up claim — and only when the value actually changes
(echoing the current value is a no-op and must not prompt). A plain office
session may still change benign fields unprompted.
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


@pytest.mark.django_db
class TestSensitiveSettingsStepUp:
    def test_flip_gdpr_gate_without_step_up_is_refused(self, api_client, tenant):
        """Turning the deletion safety-gate OFF without a fresh step-up claim
        is refused before any settings version is written."""
        resp = _update(
            api_client, tenant, require_admin_approval_for_gdpr_deletion=False
        )
        assert resp.status_code == 403
        assert resp.data["code"] == "auth.step_up_required"

    def test_change_sepa_collection_day_without_step_up_is_refused(
        self, api_client, tenant
    ):
        resp = _update(api_client, tenant, sepa_collection_day_of_month=15)
        assert resp.status_code == 403
        assert resp.data["code"] == "auth.step_up_required"

    def test_flip_gdpr_gate_with_step_up_succeeds(self, api_client, user, tenant):
        api_client.force_authenticate(user=user, token=make_step_up_token(user))
        try:
            resp = _update(
                api_client, tenant, require_admin_approval_for_gdpr_deletion=False
            )
            assert resp.status_code == 200
            assert (
                resp.data["settings"]["require_admin_approval_for_gdpr_deletion"]
                is False
            )
        finally:
            # The test_pytest tenant is session-scoped and these writes persist
            # across tests; restore the safe default so the GDPR tests aren't
            # affected by a left-over open gate.
            current = TenantSettings.get_current_settings(tenant=tenant)
            if current is not None:
                current.require_admin_approval_for_gdpr_deletion = True
                current.save(update_fields=["require_admin_approval_for_gdpr_deletion"])

    def test_non_sensitive_change_skips_step_up(self, api_client, tenant):
        # ``payment_terms_reseller_in_days`` is not step-up-sensitive, so a
        # plain office session (no step-up claim) changes it unprompted.
        resp = _update(api_client, tenant, payment_terms_reseller_in_days=30)
        assert resp.status_code == 200

    def test_echoing_unchanged_sensitive_value_skips_step_up(self, api_client, tenant):
        # Resending the CURRENT gate value is a no-op — the step-up gate fires
        # only on an actual change, so this passes without a step-up claim.
        current = TenantSettings.get_current_settings(tenant=tenant)
        gate = (
            current.require_admin_approval_for_gdpr_deletion
            if current is not None
            else True
        )
        resp = _update(
            api_client, tenant, require_admin_approval_for_gdpr_deletion=gate
        )
        assert resp.status_code == 200
