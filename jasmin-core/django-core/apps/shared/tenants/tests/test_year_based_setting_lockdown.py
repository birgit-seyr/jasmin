"""Tests for year-based numbering setting lock-down validation.

Once documents of a given type exist, the corresponding
``*_numbers_start_new_at_year_change`` setting must be immutable to prevent
number collisions.
"""

from __future__ import annotations

import datetime

import pytest
from rest_framework import status

from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderFactory,
    ResellerFactory,
)
from apps.shared.tenants.models import TenantSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_settings(tenant, **overrides):
    from django.utils import timezone

    defaults = dict(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(days=365),
        valid_until=None,
    )
    defaults.update(overrides)
    settings, _ = TenantSettings.objects.get_or_create(
        tenant=tenant, valid_until=None, defaults=defaults
    )
    for k, v in overrides.items():
        setattr(settings, k, v)
    settings.save()
    return settings


def _update_settings(api_client, tenant, **settings_kwargs):
    return api_client.put(
        f"/api/tenants/settings/update_current_settings/?tenant_id={tenant.id}",
        {"settings": settings_kwargs},
        format="json",
    )


# ===================================================================
# Year-based setting lock-down
# ===================================================================
@pytest.mark.django_db
class TestYearBasedSettingLockDown:
    """Changing year-based numbering settings is blocked once documents exist."""

    # ---- Orders -------------------------------------------------------
    def test_order_setting_blocked_when_orders_exist(self, api_client, tenant):
        _ensure_settings(tenant, order_numbers_start_new_at_year_change=False)
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller)

        resp = _update_settings(
            api_client, tenant, order_numbers_start_new_at_year_change=True
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "order_numbers_start_new_at_year_change" in resp.data["message"]

    def test_order_setting_allowed_when_no_orders(self, api_client, tenant):
        _ensure_settings(tenant, order_numbers_start_new_at_year_change=False)

        resp = _update_settings(
            api_client, tenant, order_numbers_start_new_at_year_change=True
        )
        assert resp.status_code == status.HTTP_200_OK

    # ---- Delivery notes -----------------------------------------------
    def test_dn_setting_blocked_when_dns_exist(self, api_client, tenant):
        _ensure_settings(tenant, delivery_note_numbers_start_new_at_year_change=False)
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        DeliveryNoteResellerFactory(order=order)

        resp = _update_settings(
            api_client,
            tenant,
            delivery_note_numbers_start_new_at_year_change=True,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "delivery_note_numbers_start_new_at_year_change" in resp.data["message"]

    def test_dn_setting_allowed_when_no_dns(self, api_client, tenant):
        _ensure_settings(tenant, delivery_note_numbers_start_new_at_year_change=False)

        resp = _update_settings(
            api_client,
            tenant,
            delivery_note_numbers_start_new_at_year_change=True,
        )
        assert resp.status_code == status.HTTP_200_OK

    # ---- Invoices -----------------------------------------------------
    def test_invoice_setting_blocked_when_invoices_exist(self, api_client, tenant):
        _ensure_settings(tenant, invoice_numbers_start_new_at_year_change=False)
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        _dn = DeliveryNoteResellerFactory(order=order)
        InvoiceResellerFactory(reseller=reseller)

        resp = _update_settings(
            api_client, tenant, invoice_numbers_start_new_at_year_change=True
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "invoice_numbers_start_new_at_year_change" in resp.data["message"]

    def test_invoice_setting_allowed_when_no_invoices(self, api_client, tenant):
        _ensure_settings(tenant, invoice_numbers_start_new_at_year_change=False)

        resp = _update_settings(
            api_client, tenant, invoice_numbers_start_new_at_year_change=True
        )
        assert resp.status_code == status.HTTP_200_OK

    # ---- Same value (no-op) -------------------------------------------
    def test_same_value_allowed_even_with_documents(self, api_client, tenant):
        """Re-submitting the same value is not a 'change' — should be allowed."""
        _ensure_settings(tenant, order_numbers_start_new_at_year_change=False)
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller)

        resp = _update_settings(
            api_client, tenant, order_numbers_start_new_at_year_change=False
        )
        assert resp.status_code == status.HTTP_200_OK

    # ---- Non-numbering settings pass through --------------------------
    def test_other_settings_unaffected(self, api_client, tenant):
        """Changing unrelated settings should work even if documents exist."""
        _ensure_settings(tenant)
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller)

        resp = _update_settings(api_client, tenant, payment_terms_reseller_in_days=30)
        assert resp.status_code == status.HTTP_200_OK

    # ---- Toggle OFF→ON→OFF blocked both ways -------------------------
    def test_toggle_off_to_on_blocked(self, api_client, tenant):
        _ensure_settings(tenant, order_numbers_start_new_at_year_change=False)
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller)

        resp = _update_settings(
            api_client, tenant, order_numbers_start_new_at_year_change=True
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_toggle_on_to_off_blocked(self, api_client, tenant):
        _ensure_settings(tenant, order_numbers_start_new_at_year_change=True)
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller)

        resp = _update_settings(
            api_client, tenant, order_numbers_start_new_at_year_change=False
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ===================================================================
# locked_settings endpoint
# ===================================================================
def _get_locked_settings(api_client, tenant):
    return api_client.get(
        f"/api/tenants/settings/locked_settings/?tenant_id={tenant.id}",
    )


@pytest.mark.django_db
class TestLockedSettingsEndpoint:
    """The locked_settings endpoint reports which year-based settings are immutable."""

    def test_no_documents_returns_empty(self, api_client, tenant):
        resp = _get_locked_settings(api_client, tenant)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["locked_settings"] == []

    def test_orders_exist_locks_order_setting(self, api_client, tenant):
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller)

        resp = _get_locked_settings(api_client, tenant)
        assert resp.status_code == status.HTTP_200_OK
        assert "order_numbers_start_new_at_year_change" in resp.data["locked_settings"]
        assert (
            "delivery_note_numbers_start_new_at_year_change"
            not in resp.data["locked_settings"]
        )
        assert (
            "invoice_numbers_start_new_at_year_change"
            not in resp.data["locked_settings"]
        )

    def test_all_document_types_locks_all(self, api_client, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        DeliveryNoteResellerFactory(order=order)
        InvoiceResellerFactory(reseller=reseller)

        resp = _get_locked_settings(api_client, tenant)
        assert resp.status_code == status.HTTP_200_OK
        locked = resp.data["locked_settings"]
        assert "order_numbers_start_new_at_year_change" in locked
        assert "delivery_note_numbers_start_new_at_year_change" in locked
        assert "invoice_numbers_start_new_at_year_change" in locked


# ===================================================================
# DOC-1 / DOC-3: numbering prefixes are legal-document labels — none of the
# four may be blanked via update_current_settings.
# ===================================================================
@pytest.mark.django_db
class TestPrefixBlankGuard:
    @pytest.mark.parametrize(
        "field",
        [
            "invoice_number_prefix",
            "correction_invoice_number_prefix",
            "order_number_prefix",
            "delivery_note_number_prefix",
        ],
    )
    def test_blank_prefix_rejected(self, api_client, tenant, field):
        _ensure_settings(tenant)
        resp = _update_settings(api_client, tenant, **{field: ""})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "tenant_settings.empty_numbering_prefix"

    def test_nonblank_prefix_allowed(self, api_client, tenant):
        _ensure_settings(tenant)
        resp = _update_settings(api_client, tenant, order_number_prefix="BX")
        assert resp.status_code == status.HTTP_200_OK


# ===================================================================
# Settings field validation (TEN-1)
# ===================================================================
@pytest.mark.django_db
class TestSettingsFieldValidation:
    """``update_current_settings`` is the ONLY TenantSettings write path and
    reads ``request.data["settings"]`` raw (no input serializer), so it must run
    ``full_clean`` — otherwise out-of-range day/week values persist and later
    crash charge-schedule generation. The billing/SEPA day fields are step-up
    gated, so these tests carry a fresh step-up claim to reach the validation."""

    @pytest.mark.parametrize(
        "field, bad_value",
        [
            ("billing_due_day_of_month", 0),  # below MinValue(1)
            ("billing_due_day_of_month", 99),  # above MaxValue(28)
            ("sepa_collection_day_of_month", 0),
        ],
    )
    def test_out_of_range_value_rejected(
        self, api_client, user, tenant, field, bad_value
    ):
        api_client.force_authenticate(user=user, token=make_step_up_token(user))
        _ensure_settings(tenant)
        resp = _update_settings(api_client, tenant, **{field: bad_value})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "tenant_settings.invalid_value"
        # The bad value never reached the DB.
        current = TenantSettings.objects.get(tenant=tenant, valid_until=None)
        assert getattr(current, field) != bad_value

    def test_in_range_value_is_accepted(self, api_client, user, tenant):
        api_client.force_authenticate(user=user, token=make_step_up_token(user))
        _ensure_settings(tenant)
        resp = _update_settings(api_client, tenant, billing_due_day_of_month=14)
        assert resp.status_code == status.HTTP_200_OK
