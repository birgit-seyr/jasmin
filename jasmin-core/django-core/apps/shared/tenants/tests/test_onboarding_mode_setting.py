"""``TenantSettings.onboarding_mode``: off by default, and turning it on or off
through ``update_current_settings`` needs a fresh step-up claim, because the mode
unlocks member-number edits and back-dated confirmations that send no email."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.commissioning.tests.conftest import make_step_up_token
from apps.shared.tenants.models import TenantSettings


def _update(api_client, tenant, **settings_kwargs):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_kwargs},
        format="json",
    )


def _current_onboarding_mode(tenant) -> bool:
    current = TenantSettings.get_current_settings(tenant=tenant)
    return current.onboarding_mode if current is not None else False


def _reset_onboarding_mode(tenant) -> None:
    current = TenantSettings.get_current_settings(tenant=tenant)
    if current is not None and current.onboarding_mode:
        current.onboarding_mode = False
        current.save(update_fields=["onboarding_mode"])


@pytest.mark.django_db
class TestOnboardingModeSetting:
    def test_defaults_off(self, tenant):
        settings = TenantSettings(tenant=tenant, valid_from=timezone.now())
        assert settings.onboarding_mode is False
        assert settings.to_dict()["onboarding_mode"] is False

    def test_is_step_up_sensitive(self):
        from apps.shared.tenants.viewsets import TenantSettingsViewSet

        assert "onboarding_mode" in TenantSettingsViewSet._STEP_UP_SENSITIVE_FIELDS

    def test_turning_on_without_step_up_is_refused(self, api_client, tenant):
        assert _current_onboarding_mode(tenant) is False
        resp = _update(api_client, tenant, onboarding_mode=True)
        assert resp.status_code == 403
        assert resp.data["code"] == "auth.step_up_required"
        assert _current_onboarding_mode(tenant) is False

    def test_turning_on_with_step_up_succeeds(self, api_client, user, tenant):
        api_client.force_authenticate(user=user, token=make_step_up_token(user))
        try:
            resp = _update(api_client, tenant, onboarding_mode=True)
            assert resp.status_code == 200
            assert resp.data["settings"]["onboarding_mode"] is True
            assert _current_onboarding_mode(tenant) is True
        finally:
            _reset_onboarding_mode(tenant)

    def test_echoing_the_current_value_skips_step_up(self, api_client, tenant):
        resp = _update(
            api_client, tenant, onboarding_mode=_current_onboarding_mode(tenant)
        )
        assert resp.status_code == 200
