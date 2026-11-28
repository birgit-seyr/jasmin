"""``TenantSettings.uses_organic_documentation``: whether the farm documents
its organic certification. It is on unless the office switches it off; while
it is off, the anonymous tenant payload behind the public Impressum names no
organic control number, and the office's own payload keeps the stored one so
it stays editable.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.shared.tenants.models import TenantSettings

CONTROL_NUMBER = "AT-BIO-301"


def _update(api_client, tenant, **settings_kwargs):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_kwargs},
        format="json",
    )


@pytest.fixture
def anon_client(tenant_host):
    return APIClient(HTTP_HOST=tenant_host)


@pytest.fixture
def certified_farm(tenant):
    # The tenant is session-scoped, so its row and settings persist across
    # tests; put the previous values back.
    previous_number = tenant.organic_control_number
    current = TenantSettings.get_current_settings(tenant=tenant)
    previous_switch = current.uses_organic_documentation if current else True
    tenant.organic_control_number = CONTROL_NUMBER
    tenant.save(update_fields=["organic_control_number"])
    yield tenant
    tenant.organic_control_number = previous_number
    tenant.save(update_fields=["organic_control_number"])
    current = TenantSettings.get_current_settings(tenant=tenant)
    if current is not None:
        current.uses_organic_documentation = previous_switch
        current.save(update_fields=["uses_organic_documentation"])


@pytest.mark.django_db
class TestOrganicDocumentation:
    def test_is_on_by_default(self):
        assert TenantSettings().uses_organic_documentation is True

    def test_the_public_payload_names_the_control_number_while_it_is_on(
        self, api_client, anon_client, certified_farm
    ):
        resp = _update(api_client, certified_farm, uses_organic_documentation=True)
        assert resp.status_code == 200, resp.data

        public = anon_client.get("/api/tenants/current/")

        assert public.status_code == 200
        assert public.data["organic_control_number"] == CONTROL_NUMBER

    def test_the_public_payload_names_none_while_it_is_off(
        self, api_client, anon_client, certified_farm
    ):
        resp = _update(api_client, certified_farm, uses_organic_documentation=False)
        assert resp.status_code == 200, resp.data
        assert resp.data["settings"]["uses_organic_documentation"] is False

        public = anon_client.get("/api/tenants/current/")

        assert public.data["organic_control_number"] is None
        office = api_client.get(f"/api/tenants/tenants/{certified_farm.id}/")
        assert office.data["organic_control_number"] == CONTROL_NUMBER
