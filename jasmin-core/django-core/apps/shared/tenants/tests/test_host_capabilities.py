"""What a deployment offers, and the tenant payloads that report it.

``JASMIN_HOST`` names the application jasmin runs inside, if any. The frontend
never sees the name, only the capabilities derived from it, so every tenant
payload it reads — the anonymous one before login and both role-routed ones
after — has to carry them. Inside Tapir the operating mode and the modules are
fixed as well: the demand always comes from imported amounts, and commissioning
is the only module.
"""

from __future__ import annotations

import pytest
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.host_capabilities import (
    check_jasmin_host,
    host_capabilities,
    navigation_in_effect,
    share_demand_is_imported,
)
from apps.shared.tenants.models import TenantSettings

CAPABILITIES = (
    "support_tickets",
    "gdpr",
    "user_accounts",
    "operating_mode_choice",
    "legal_notice",
    "web_app",
    "manual_share_import",
    "delivery_stations",
    "about",
    "module_choice",
    "share_types",
)
EVERYTHING_OFFERED = dict.fromkeys(CAPABILITIES, True)
NOTHING_OFFERED = dict.fromkeys(CAPABILITIES, False)


class TestHostCapabilities:
    def test_settings_that_name_no_host_offer_everything(self, settings):
        # A host's own settings don't load jasmin's, so the name can be missing.
        del settings.JASMIN_HOST
        assert host_capabilities() == EVERYTHING_OFFERED

    def test_a_standalone_deployment_offers_everything(self, settings):
        settings.JASMIN_HOST = "standalone"
        assert host_capabilities() == EVERYTHING_OFFERED

    def test_tapir_stands_in_for_all_of_them(self, settings):
        settings.JASMIN_HOST = "tapir"
        assert host_capabilities() == NOTHING_OFFERED

    def test_without_a_setting_the_environment_can_name_the_host(
        self, settings, monkeypatch
    ):
        # A dev stack previews Tapir mode this way.
        del settings.JASMIN_HOST
        monkeypatch.setenv("JASMIN_HOST", "tapir")
        assert host_capabilities() == NOTHING_OFFERED

    def test_the_setting_wins_over_the_environment(self, settings, monkeypatch):
        settings.JASMIN_HOST = "standalone"
        monkeypatch.setenv("JASMIN_HOST", "tapir")
        assert host_capabilities() == EVERYTHING_OFFERED

    def test_an_unknown_host_is_refused_rather_than_offering_everything(self, settings):
        settings.JASMIN_HOST = "Tapir"
        with pytest.raises(ImproperlyConfigured, match="JASMIN_HOST"):
            host_capabilities()


class TestJasminHostSystemCheck:
    @pytest.mark.parametrize("host", ["standalone", "tapir"])
    def test_a_known_host_passes(self, settings, host):
        settings.JASMIN_HOST = host
        assert check_jasmin_host() == []

    def test_a_missing_setting_passes(self, settings):
        del settings.JASMIN_HOST
        assert check_jasmin_host() == []

    def test_an_unknown_host_fails_the_check(self, settings):
        settings.JASMIN_HOST = "Tapir"
        [error] = check_jasmin_host()
        assert error.id == "jasmin.E001"
        assert "'Tapir'" in error.msg

    def test_django_runs_it_with_its_own_checks(self, settings):
        # Registered by ``apps.shared.tenants``, so ``migrate`` and
        # ``runserver`` stop on it.
        settings.JASMIN_HOST = "Tapir"
        assert "jasmin.E001" in {message.id for message in run_checks()}


class TestImportedShareDemand:
    def test_standalone_follows_the_tenant_setting(self):
        assert share_demand_is_imported(True) is True
        assert share_demand_is_imported(False) is False

    def test_tapir_always_imports_the_demand(self, settings):
        settings.JASMIN_HOST = "tapir"
        assert share_demand_is_imported(False) is True


@pytest.mark.django_db
class TestTenantPayloadsReportTheCapabilities:
    def test_the_anonymous_payload_carries_them_before_login(
        self, tenant, tenant_host, settings
    ):
        settings.JASMIN_HOST = "tapir"
        response = APIClient(HTTP_HOST=tenant_host).get("/api/tenants/current/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["capabilities"] == NOTHING_OFFERED

    @pytest.mark.parametrize("roles", [["office"], ["member"]])
    def test_the_payload_after_login_carries_them_for_every_role(
        self, tenant, tenant_host, settings, roles
    ):
        settings.JASMIN_HOST = "tapir"
        client = APIClient(HTTP_HOST=tenant_host)
        client.force_authenticate(user=JasminUserFactory(roles=roles))
        response = client.get(f"/api/tenants/tenants/{tenant.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["capabilities"] == NOTHING_OFFERED

    def test_a_standalone_payload_offers_everything(self, tenant, tenant_host):
        response = APIClient(HTTP_HOST=tenant_host).get("/api/tenants/current/")
        assert response.data["capabilities"] == EVERYTHING_OFFERED


@pytest.mark.django_db
class TestOperatingModeInsideTapir:
    @pytest.fixture()
    def stored_mode_off(self, tenant):
        """The tenant's row says subscriptions; put the stored value back after,
        since the tenant outlives the test."""
        current = TenantSettings.get_current_settings(tenant)
        if current is None:
            yield
            return
        stored = current.uploads_weekly_share_amount
        current.uploads_weekly_share_amount = False
        current.save(update_fields=["uploads_weekly_share_amount"])
        yield
        current.uploads_weekly_share_amount = stored
        current.save(update_fields=["uploads_weekly_share_amount"])

    def _settings_after_login(self, tenant, tenant_host) -> dict:
        client = APIClient(HTTP_HOST=tenant_host)
        client.force_authenticate(user=JasminUserFactory(roles=["office"]))
        response = client.get(f"/api/tenants/tenants/{tenant.id}/")
        assert response.status_code == status.HTTP_200_OK
        return response.data["settings"]

    def test_standalone_reports_the_stored_mode(
        self, tenant, tenant_host, stored_mode_off
    ):
        settings_payload = self._settings_after_login(tenant, tenant_host)
        assert settings_payload["uploads_weekly_share_amount"] is False

    def test_tapir_reports_the_import_mode_whatever_the_row_stores(
        self, tenant, tenant_host, settings, stored_mode_off
    ):
        settings.JASMIN_HOST = "tapir"
        settings_payload = self._settings_after_login(tenant, tenant_host)
        assert settings_payload["uploads_weekly_share_amount"] is True


# Staff and a switch outside the modules on, commissioning off.
STORED_MODULES = {
    "show_staff": True,
    "show_commissioning": False,
    "show_exports": True,
}


class TestModulesInEffect:
    def test_standalone_follows_the_stored_switches(self):
        assert navigation_in_effect(STORED_MODULES) == STORED_MODULES

    def test_tapir_keeps_only_commissioning_whatever_is_stored(self, settings):
        settings.JASMIN_HOST = "tapir"
        assert navigation_in_effect(STORED_MODULES) == {
            "show_members": False,
            "show_abos": False,
            "show_commissioning": True,
            "show_staff": False,
            "show_warehouse": False,
            "show_economics": False,
            "show_cultivation": False,
            "show_exports": True,
        }


@pytest.mark.django_db
class TestModulesInsideTapir:
    @pytest.fixture()
    def stored_modules(self, tenant):
        """The tenant's row stores ``STORED_MODULES``; put the stored value back
        after, since the tenant outlives the test."""
        stored = tenant.navigation
        tenant.navigation = STORED_MODULES
        tenant.save(update_fields=["navigation"])
        yield
        tenant.navigation = stored
        tenant.save(update_fields=["navigation"])

    def _payload_after_login(self, tenant, tenant_host) -> dict:
        client = APIClient(HTTP_HOST=tenant_host)
        client.force_authenticate(user=JasminUserFactory(roles=["office"]))
        response = client.get(f"/api/tenants/tenants/{tenant.id}/")
        assert response.status_code == status.HTTP_200_OK
        return response.data

    def test_standalone_reports_the_stored_modules(
        self, tenant, tenant_host, stored_modules
    ):
        payload = self._payload_after_login(tenant, tenant_host)
        assert payload["settings"]["navigation"] == STORED_MODULES

    def test_tapir_reports_commissioning_alone_and_keeps_the_stored_choice(
        self, tenant, tenant_host, settings, stored_modules
    ):
        settings.JASMIN_HOST = "tapir"
        payload = self._payload_after_login(tenant, tenant_host)
        assert payload["settings"]["navigation"]["show_commissioning"] is True
        assert payload["settings"]["navigation"]["show_staff"] is False
        # The row's own field, which the settings page saves back, is untouched.
        assert payload["navigation"] == STORED_MODULES
