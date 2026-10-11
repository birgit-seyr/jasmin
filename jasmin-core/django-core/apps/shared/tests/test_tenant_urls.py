"""The frontend base URL that tenant emails build their links on."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django_tenants.utils import schema_context

from apps.commissioning.tasks import _office_review_url
from apps.shared.tenant_urls import frontend_base_url
from apps.shared.tenants.models import Domain

pytestmark = pytest.mark.django_db


def _selects(queries: CaptureQueriesContext) -> int:
    # django-tenants issues a ``SET search_path`` before the first query of a
    # schema switch; only the lookups themselves count.
    return sum(1 for query in queries if query["sql"].startswith("SELECT"))


@pytest.fixture(autouse=True)
def _link_settings(settings):
    settings.DEBUG = False
    settings.FRONTEND_BASE_URL = "https://farm.example"


def test_frontend_base_url_setting_is_defined():
    assert settings.FRONTEND_BASE_URL


class TestFrontendBaseUrl:
    def test_request_tenant_links_to_its_primary_domain(self, tenant):
        # The ``tenant`` fixture sets the real Tenant row, as the middleware
        # does in a request; ``testserver`` is its primary domain.
        assert frontend_base_url() == "https://testserver"

    def test_schema_context_links_to_the_tenants_own_domain(self, tenant):
        # Under ``schema_context`` the connection's tenant is a FakeTenant with
        # only a schema name — the same as a Huey worker or a command.
        with schema_context(tenant.schema_name):
            assert frontend_base_url() == "https://testserver"

    def test_schema_context_prefers_the_primary_domain(self, tenant):
        Domain.objects.filter(tenant=tenant).update(is_primary=False)
        Domain.objects.filter(tenant=tenant, domain="pytest.localhost").update(
            is_primary=True
        )
        with schema_context(tenant.schema_name):
            assert frontend_base_url() == "https://pytest.localhost"

    def test_schema_context_without_primary_takes_any_domain(self, tenant):
        Domain.objects.filter(tenant=tenant).exclude(domain="testserver").delete()
        Domain.objects.filter(tenant=tenant).update(is_primary=False)
        with schema_context(tenant.schema_name):
            assert frontend_base_url() == "https://testserver"

    def test_tenant_without_domain_links_to_the_configured_base(self, tenant):
        Domain.objects.filter(tenant=tenant).delete()
        with schema_context(tenant.schema_name):
            assert frontend_base_url() == "https://farm.example"

    def test_schema_context_lookup_is_one_select(self, tenant):
        with schema_context(tenant.schema_name):
            with CaptureQueriesContext(connection) as queries:
                frontend_base_url()
        assert _selects(queries) == 1

    def test_request_tenant_lookup_is_one_select(self, tenant):
        with CaptureQueriesContext(connection) as queries:
            frontend_base_url()
        assert _selects(queries) == 1

    def test_debug_links_over_http(self, tenant, settings):
        settings.DEBUG = True
        with schema_context(tenant.schema_name):
            assert frontend_base_url() == "http://testserver"


class TestOfficeReviewUrl:
    def test_renewal_digest_links_to_the_tenants_domain(self, tenant):
        assert (
            _office_review_url(tenant, "/abos/abos") == "https://testserver/abos/abos"
        )

    def test_renewal_digest_link_without_domain_uses_the_configured_base(self):
        tenant_without_domain = SimpleNamespace(domains=Domain.objects.none())

        assert (
            _office_review_url(tenant_without_domain, "/abos")
            == "https://farm.example/abos"
        )
