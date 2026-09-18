"""``tenant_language`` accepts only a language the platform can render.

``LanguageChoices`` is the single source of truth for which languages have UI
strings and email templates. The column behind this field is a plain
8-character ``CharField``, so the tenant-admin PATCH endpoint has to constrain
it explicitly: an unconstrained write stores a locale nothing can render, and
every reader downstream then falls back silently instead of the value being
refused at the point it was set.

Blank is a distinct, legitimate value — ``apps.shared.invitations`` and
``tenants.email_service`` treat ``""`` as "no tenant preference" — so it must
stay accepted, and an omitted key must leave the stored language untouched.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory


def _detail_url(tenant) -> str:
    return f"/api/tenants/tenants/{tenant.id}/"


@pytest.fixture()
def admin_client(tenant, tenant_host) -> APIClient:
    """Writes on the tenant row are gated by ``write_permission = IsAdmin``."""
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=JasminUserFactory(roles=["admin"]))
    return client


@pytest.fixture(autouse=True)
def _restore_tenant_language(tenant):
    """The tenant row outlives a single test (the schema is session-scoped),
    so put the language back instead of leaking it into the next test."""
    original = tenant.tenant_language
    yield
    tenant.tenant_language = original
    tenant.save(update_fields=["tenant_language"])


@pytest.fixture()
def tenant_speaking_german(tenant):
    """A known starting language, so a refused write can be shown to have
    changed nothing rather than merely returning 400."""
    tenant.tenant_language = "de"
    tenant.save(update_fields=["tenant_language"])
    return tenant


@pytest.mark.django_db
class TestTenantLanguageChoice:
    @pytest.mark.parametrize("code", ["en", "de"])
    def test_a_supported_language_is_stored(self, admin_client, tenant, code):
        response = admin_client.patch(
            _detail_url(tenant), {"tenant_language": code}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        tenant.refresh_from_db()
        assert tenant.tenant_language == code

    @pytest.mark.parametrize("code", ["fr", "it", "xx", "de-DE"])
    def test_an_unsupported_language_is_refused(
        self, admin_client, tenant_speaking_german, code
    ):
        response = admin_client.patch(
            _detail_url(tenant_speaking_german),
            {"tenant_language": code},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        tenant_speaking_german.refresh_from_db()
        assert tenant_speaking_german.tenant_language == "de"

    def test_an_omitted_language_leaves_the_stored_value_alone(
        self, admin_client, tenant_speaking_german
    ):
        """The configuration page PATCHes whole field groups; a request that
        does not mention the language must not reset it."""
        response = admin_client.patch(
            _detail_url(tenant_speaking_german), {"city": "Vienna"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        tenant_speaking_german.refresh_from_db()
        assert tenant_speaking_german.tenant_language == "de"

    def test_a_blank_language_stays_accepted(
        self, admin_client, tenant_speaking_german
    ):
        """``""`` means "no tenant preference" to the invitation and email
        readers, which fall back to their own default."""
        response = admin_client.patch(
            _detail_url(tenant_speaking_german),
            {"tenant_language": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tenant_speaking_german.refresh_from_db()
        assert tenant_speaking_german.tenant_language == ""
