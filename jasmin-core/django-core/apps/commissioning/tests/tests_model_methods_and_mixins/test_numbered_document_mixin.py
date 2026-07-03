"""Tests for NumberedDocumentMixin."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.utils import timezone

from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderFactory,
)
from apps.shared.tenants.models import TenantSettings


def _ensure_settings(tenant, **overrides):
    """Create TenantSettings for the current tenant if not present."""
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


# ---------------------------------------------------------------------------
# _get_tenant_settings_fields
# ---------------------------------------------------------------------------
class TestGetTenantSettingsFields:
    def test_order_type(self):
        o = OrderFactory.build()
        year_field, prefix_field = o._get_tenant_settings_fields()
        assert year_field == "order_numbers_start_new_at_year_change"
        assert prefix_field == "order_number_prefix"

    def test_delivery_note_type(self):
        dn = DeliveryNoteResellerFactory.build()
        year_field, prefix_field = dn._get_tenant_settings_fields()
        assert year_field == "delivery_note_numbers_start_new_at_year_change"
        assert prefix_field == "delivery_note_number_prefix"

    def test_invoice_type(self):
        inv = InvoiceResellerFactory.build()
        year_field, prefix_field = inv._get_tenant_settings_fields()
        assert year_field == "invoice_numbers_start_new_at_year_change"
        assert prefix_field == "invoice_number_prefix"

    def test_unknown_type_raises(self):
        o = OrderFactory.build()
        o.DOCUMENT_TYPE = "receipt"
        with pytest.raises(ValueError, match="Unknown DOCUMENT_TYPE"):
            o._get_tenant_settings_fields()


# ---------------------------------------------------------------------------
# generate_number  — sequential numbering, prefix, year-based
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGenerateNumber:
    def test_first_number_is_1(self, tenant):
        _ts = _ensure_settings(connection.tenant)
        order = OrderFactory(number=None)
        order.generate_number()
        assert order.number == 1

    def test_sequential_numbering(self, tenant):
        _ts = _ensure_settings(connection.tenant)
        o1 = OrderFactory(number=None)
        o1.generate_number()
        o1.save()

        o2 = OrderFactory(number=None)
        o2.generate_number()
        assert o2.number == 2

    def test_does_not_overwrite_existing_number(self, tenant):
        _ts = _ensure_settings(connection.tenant)
        order = OrderFactory(number=42)
        order.generate_number()
        assert order.number == 42

    def test_applies_prefix_from_settings(self, tenant):
        _ensure_settings(connection.tenant, order_number_prefix="ORD")
        order = OrderFactory(number=None, prefix=None)
        order.generate_number()
        assert order.prefix == "ORD"
        assert order.number == 1

    def test_year_based_numbering_resets_per_year(self, tenant):
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
        )
        o1 = OrderFactory(year=2025, number=None)
        o1.generate_number()
        o1.save()

        o2 = OrderFactory(year=2026, number=None)
        o2.generate_number()
        # new year → number resets to 1
        assert o2.number == 1

    def test_no_settings_still_numbers(self, tenant):
        # No TenantSettings exist → fallback path
        TenantSettings.objects.filter(tenant=connection.tenant).delete()
        order = OrderFactory(number=None)
        order.generate_number()
        assert order.number == 1

    def test_delivery_note_numbering(self, tenant):
        _ensure_settings(
            connection.tenant,
            delivery_note_number_prefix="LS",
        )
        dn = DeliveryNoteResellerFactory(number=None, prefix=None)
        dn.generate_number()
        assert dn.number == 1
        assert dn.prefix == "LS"

    def test_invoice_numbering(self, tenant):
        _ensure_settings(
            connection.tenant,
            invoice_number_prefix="RE",
        )
        inv = InvoiceResellerFactory(number=None, prefix=None)
        inv.generate_number()
        assert inv.number == 1
        assert inv.prefix == "RE"


# ---------------------------------------------------------------------------
# Year-based prefix — year is baked into prefix when setting is ON
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestYearBasedPrefix:
    """When *_start_new_at_year_change is True, prefix should include the year."""

    # --- Order ---

    def test_order_prefix_includes_year_when_year_based(self, tenant):
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="BE",
        )
        order = OrderFactory(year=2026, number=None, prefix=None)
        order.generate_number()
        assert order.prefix == "BE-2026"
        assert order.number == 1

    def test_order_prefix_no_year_when_global(self, tenant):
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=False,
            order_number_prefix="BE",
        )
        order = OrderFactory(year=2026, number=None, prefix=None)
        order.generate_number()
        assert order.prefix == "BE"

    def test_order_year_based_different_years_get_different_prefixes(self, tenant):
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="BE",
        )
        o1 = OrderFactory(year=2025, number=None, prefix=None)
        o1.generate_number()
        o1.save()

        o2 = OrderFactory(year=2026, number=None, prefix=None)
        o2.generate_number()

        assert o1.prefix == "BE-2025"
        assert o2.prefix == "BE-2026"
        assert o1.number == 1
        assert o2.number == 1  # reset per year

    def test_order_year_based_same_year_sequential(self, tenant):
        _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="BE",
        )
        o1 = OrderFactory(year=2026, number=None, prefix=None)
        o1.generate_number()
        o1.save()

        o2 = OrderFactory(year=2026, number=None, prefix=None)
        o2.generate_number()

        assert o1.prefix == "BE-2026"
        assert o2.prefix == "BE-2026"
        assert o1.number == 1
        assert o2.number == 2

    # --- Delivery Note ---

    def test_dn_prefix_includes_year_when_year_based(self, tenant):
        _ensure_settings(
            connection.tenant,
            delivery_note_numbers_start_new_at_year_change=True,
            delivery_note_number_prefix="LS",
        )
        dn = DeliveryNoteResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2026, 4, 13),
        )
        dn.generate_number()
        assert dn.prefix == "LS-2026"
        assert dn.number == 1

    def test_dn_prefix_no_year_when_global(self, tenant):
        _ensure_settings(
            connection.tenant,
            delivery_note_numbers_start_new_at_year_change=False,
            delivery_note_number_prefix="LS",
        )
        dn = DeliveryNoteResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2026, 4, 13),
        )
        dn.generate_number()
        assert dn.prefix == "LS"

    def test_dn_year_based_different_years_reset(self, tenant):
        _ensure_settings(
            connection.tenant,
            delivery_note_numbers_start_new_at_year_change=True,
            delivery_note_number_prefix="LS",
        )
        dn1 = DeliveryNoteResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2025, 12, 15),
        )
        dn1.generate_number()
        dn1.save()

        dn2 = DeliveryNoteResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2026, 1, 5),
        )
        dn2.generate_number()

        assert dn1.prefix == "LS-2025"
        assert dn2.prefix == "LS-2026"
        assert dn1.number == 1
        assert dn2.number == 1

    # --- Invoice ---

    def test_invoice_prefix_includes_year_when_year_based(self, tenant):
        _ensure_settings(
            connection.tenant,
            invoice_numbers_start_new_at_year_change=True,
            invoice_number_prefix="RE",
        )
        inv = InvoiceResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2026, 4, 13),
        )
        inv.generate_number()
        assert inv.prefix == "RE-2026"
        assert inv.number == 1

    def test_invoice_prefix_no_year_when_global(self, tenant):
        _ensure_settings(
            connection.tenant,
            invoice_numbers_start_new_at_year_change=False,
            invoice_number_prefix="RE",
        )
        inv = InvoiceResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2026, 4, 13),
        )
        inv.generate_number()
        assert inv.prefix == "RE"

    def test_invoice_year_based_different_years_reset(self, tenant):
        _ensure_settings(
            connection.tenant,
            invoice_numbers_start_new_at_year_change=True,
            invoice_number_prefix="RE",
        )
        inv1 = InvoiceResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2025, 11, 1),
        )
        inv1.generate_number()
        inv1.save()

        inv2 = InvoiceResellerFactory(
            number=None,
            prefix=None,
            date=datetime.date(2026, 2, 1),
        )
        inv2.generate_number()

        assert inv1.prefix == "RE-2025"
        assert inv2.prefix == "RE-2026"
        assert inv1.number == 1
        assert inv2.number == 1

    # --- Mid-year toggle ---

    def test_mid_year_toggle_on_existing_docs_keep_old_prefix(self, tenant):
        """Turning on year-based mid-year: existing docs keep their prefix,
        new docs get year-based prefix."""
        ts = _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=False,
            order_number_prefix="BE",
        )
        o1 = OrderFactory(year=2026, number=None, prefix=None)
        o1.generate_number()
        o1.save()
        assert o1.prefix == "BE"
        assert o1.number == 1

        # Toggle setting ON mid-year
        ts.order_numbers_start_new_at_year_change = True
        ts.save()

        o2 = OrderFactory(year=2026, number=None, prefix=None)
        o2.generate_number()
        o2.save()

        # Old doc unchanged
        o1.refresh_from_db()
        assert o1.prefix == "BE"
        assert o1.number == 1

        # New doc gets year-based prefix; number continues from existing 2026 docs
        assert o2.prefix == "BE-2026"
        assert o2.number == 2

    def test_mid_year_toggle_off_existing_docs_keep_year_prefix(self, tenant):
        """Turning off year-based mid-year: existing docs keep year prefix,
        new docs get plain prefix."""
        ts = _ensure_settings(
            connection.tenant,
            order_numbers_start_new_at_year_change=True,
            order_number_prefix="BE",
        )
        o1 = OrderFactory(year=2026, number=None, prefix=None)
        o1.generate_number()
        o1.save()
        assert o1.prefix == "BE-2026"
        assert o1.number == 1

        # Toggle setting OFF mid-year
        ts.order_numbers_start_new_at_year_change = False
        ts.save()

        o2 = OrderFactory(year=2026, number=None, prefix=None)
        o2.generate_number()

        # Old doc unchanged
        o1.refresh_from_db()
        assert o1.prefix == "BE-2026"
        assert o1.number == 1

        # New doc gets plain prefix; number is global max + 1
        assert o2.prefix == "BE"
        assert o2.number == 2
