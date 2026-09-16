"""Step-up gate on the tenant's own SEPA creditor identity.

``TenantViewSet`` lets a tenant admin PATCH the tenant row. The IBAN and the
SEPA creditor id / name / BIC decide where SEPA collections are paid, so
changing any of them demands a fresh step-up claim, and only when a value
actually changes: the configuration autosave echoes the stored values next to
every unrelated edit, and that must not prompt.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.tenants.models import Tenant

STORED_CREDITOR = {
    "iban": "CH9300762011623852957",
    "sepa_creditor_id": "CH51ZZZ12345678901",
    "sepa_creditor_name": "Stored Creditor",
    "sepa_creditor_bic": "POFICHBEXXX",
}

CHANGED_CREDITOR = {
    "iban": "DE89370400440532013000",
    "sepa_creditor_id": "DE98ZZZ09999999999",
    "sepa_creditor_name": "Other Creditor",
    "sepa_creditor_bic": "COBADEFFXXX",
}


def _detail_url(tenant) -> str:
    return f"/api/tenants/tenants/{tenant.id}/"


@pytest.fixture()
def admin(tenant):
    return JasminUserFactory(roles=["admin"])


@pytest.fixture()
def admin_client(admin, tenant_host):
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=admin)
    return client


@pytest.fixture()
def admin_step_up_client(admin, tenant_host):
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=admin, token=make_step_up_token(admin))
    return client


@pytest.fixture()
def stored_creditor(tenant):
    """Give the shared test tenant a known creditor identity, then put the
    original values back so no other test sees these."""
    fields = [*STORED_CREDITOR, "phone_number"]
    original = Tenant.objects.filter(pk=tenant.pk).values(*fields).get()
    Tenant.objects.filter(pk=tenant.pk).update(**STORED_CREDITOR)
    yield
    Tenant.objects.filter(pk=tenant.pk).update(**original)


def _stored(tenant, field: str):
    return Tenant.objects.values_list(field, flat=True).get(pk=tenant.pk)


@pytest.mark.django_db
@pytest.mark.usefixtures("stored_creditor")
class TestTenantCreditorStepUp:
    @pytest.mark.parametrize("field", sorted(CHANGED_CREDITOR))
    def test_changing_a_creditor_field_without_step_up_is_refused(
        self, admin_client, tenant, field
    ):
        resp = admin_client.patch(
            _detail_url(tenant), {field: CHANGED_CREDITOR[field]}, format="json"
        )
        assert resp.status_code == 403, resp.content
        assert resp.data["code"] == "auth.step_up_required"
        assert _stored(tenant, field) == STORED_CREDITOR[field]

    def test_changing_the_iban_with_step_up_succeeds(
        self, admin_step_up_client, tenant
    ):
        resp = admin_step_up_client.patch(
            _detail_url(tenant), {"iban": CHANGED_CREDITOR["iban"]}, format="json"
        )
        assert resp.status_code == 200, resp.content
        assert _stored(tenant, "iban") == CHANGED_CREDITOR["iban"]

    def test_non_bank_change_skips_step_up(self, admin_client, tenant):
        resp = admin_client.patch(
            _detail_url(tenant), {"phone_number": "+41 44 000 00 00"}, format="json"
        )
        assert resp.status_code == 200, resp.content
        assert _stored(tenant, "phone_number") == "+41 44 000 00 00"

    def test_echoing_unchanged_creditor_values_skips_step_up(
        self, admin_client, tenant
    ):
        # The autosave shape: the whole form, bank fields unchanged, one
        # unrelated field edited.
        resp = admin_client.patch(
            _detail_url(tenant),
            {**STORED_CREDITOR, "phone_number": "+41 44 111 11 11"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert _stored(tenant, "phone_number") == "+41 44 111 11 11"
        assert _stored(tenant, "iban") == STORED_CREDITOR["iban"]
