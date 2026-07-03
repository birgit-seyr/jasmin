"""``TenantViewSet.get_serializer_class`` routes by role.

Contract:

  * Staff callers (office / staff / admin) get ``TenantSerializer`` —
    the full payload with banking (``iban``, ``sepa_*``), VAT
    identifier (``uid``), internal email (``email_for_orders``), and
    the bio-control number. Their UI consumes those fields
    (ConfigurationGeneral, reseller PDF generation, packing-list
    headers).
  * Non-staff callers (member / customer) get
    ``TenantNonStaffReadSerializer`` — branding + locale + GDPR
    impressum + settings overlay only. The omitted fields aren't
    consumed by any member/customer page (confirmed by grep across
    ``src/pages/customer/``, ``src/pages/abos/``, and
    ``src/components/layout/`` during the 2026-06-08 audit follow-up),
    so shipping them to those roles is over-exposure with no UI
    behind it.
  * Both roles see the settings overlay (``settings`` /
    ``current_settings``) and the GDPR impressum fields (the public
    privacy-policy template depends on those).

These assertions are field-key-presence checks; the values themselves
(empty strings on a fresh fixture tenant) are not the point. We
deliberately verify presence on the staff path too so a future
``__all__`` removal on ``TenantSerializer`` can't silently degrade
the office UI without tripping this test.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory

OFFICE_ONLY_FIELDS = (
    "iban",
    "sepa_creditor_id",
    "sepa_creditor_name",
    "sepa_creditor_bic",
    "uid",
    "email_for_orders",
    "organic_control_number",
    "days_until_payment_due",
)

SHARED_FIELDS = (
    # Identity + branding
    "id",
    "schema_name",
    "name",
    "logo",
    "bio_logo",
    "is_active",
    # Locale / formatting
    "tenant_language",
    "currency",
    "timezone",
    "date_format",
    # GDPR impressum (rendered by the public privacy-policy template
    # for non-staff and staff alike)
    "address",
    "email",
    "phone_number",
    # Settings overlay
    "settings",
    "current_settings",
)


def _detail_url(tenant) -> str:
    return f"/api/tenants/tenants/{tenant.id}/"


def _as_client(user) -> APIClient:
    client = APIClient(HTTP_HOST="tenants-pytest.localhost")
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestTenantSerializerRoleRouting:
    def test_member_does_not_receive_office_only_fields(self, tenant):
        member = JasminUserFactory(roles=["member"])
        client = _as_client(member)

        response = client.get(_detail_url(tenant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in OFFICE_ONLY_FIELDS:
            assert field not in body, (
                f"Member-role caller received office-only field {field!r}: "
                f"TenantViewSet.get_serializer_class is not routing to "
                f"TenantNonStaffReadSerializer for non-staff."
            )

    def test_customer_does_not_receive_office_only_fields(self, tenant):
        """Customer is the other non-staff role — same expectation."""
        customer = JasminUserFactory(roles=["customer"])
        client = _as_client(customer)

        response = client.get(_detail_url(tenant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in OFFICE_ONLY_FIELDS:
            assert field not in body, (
                f"Customer-role caller received office-only field " f"{field!r}."
            )

    def test_office_receives_office_only_fields(self, tenant):
        office = JasminUserFactory(roles=["office"])
        client = _as_client(office)

        response = client.get(_detail_url(tenant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in OFFICE_ONLY_FIELDS:
            assert field in body, (
                f"Office-role caller did NOT receive office field {field!r}: "
                f"the office UI (ConfigurationGeneral, reseller PDFs) needs "
                f"it. TenantViewSet.get_serializer_class regression."
            )

    def test_staff_receives_office_only_fields(self, tenant):
        """``staff`` is in IsStaff alongside office/admin — they generate
        reseller PDFs that bake ``iban`` / ``sepa_*`` / ``uid`` into the
        header, so they also need the full payload."""
        staff = JasminUserFactory(roles=["staff"])
        client = _as_client(staff)

        response = client.get(_detail_url(tenant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in OFFICE_ONLY_FIELDS:
            assert (
                field in body
            ), f"Staff-role caller did NOT receive office field {field!r}."

    def test_admin_receives_office_only_fields(self, tenant):
        """Admin is the role gated by ``write_permission`` — they patch
        these fields via ConfigurationGeneral and must also be able to
        read them back to populate the form."""
        admin = JasminUserFactory(roles=["admin"])
        client = _as_client(admin)

        response = client.get(_detail_url(tenant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in OFFICE_ONLY_FIELDS:
            assert (
                field in body
            ), f"Admin-role caller did NOT receive office field {field!r}."

    @pytest.mark.parametrize("roles", [["member"], ["office"]])
    def test_shared_fields_present_for_every_role(self, tenant, roles):
        """Settings overlay + branding + GDPR impressum must come back
        for staff and non-staff alike — the post-login
        ``useTenant().getSetting(...)`` flow on members and the
        ConfigurationGeneral form on admins both depend on it."""
        caller = JasminUserFactory(roles=roles)
        client = _as_client(caller)

        response = client.get(_detail_url(tenant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for field in SHARED_FIELDS:
            assert field in body, (
                f"{roles} caller missing shared field {field!r}: "
                f"both serializers should expose it."
            )
