"""Snapshot-based diff field tests for reseller content serializers.

Verifies that ``DifferenceTrackingMixin`` (powered by ``SourceSnapshotMixin``)
correctly reports ``*_differs`` and ``original_*`` for both line items and
crate items, on both the delivery note and the invoice side.

Contract under test:

* Snapshot columns (``source_amount``, ``source_price_per_unit``,
  ``source_rabatt``, ``source_unit``, ``source_size``) are populated by
  ``DeliveryNoteService.create_from_order`` and
  ``InvoiceService.create_from_delivery_note``.
* ``<field>_differs`` is False when local equals snapshot, True when the
  local field has been edited away from the snapshot.
* ``original_<field>`` returns the snapshot value when there is a diff,
  ``None`` otherwise.
* When the snapshot is ``NULL`` (summary invoices, manual rows), no diff
  is reported and no ``original_*`` is returned.
* When the parent invoice is a storno or correction, the diff is fully
  disabled (negated/adjusted amounts make the comparison meaningless).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.commissioning.models import (
    CrateOrderContent,
    InvoiceReseller,
)
from apps.commissioning.serializers.resellers_serializer import (
    CrateContentInvoiceResellerSerializer,
    CrateDeliveryNoteContentSerializer,
    DeliveryNoteResellerContentSerializer,
    InvoiceResellerContentSerializer,
)
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
)
from apps.shared.tenants.models import TenantSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_settings(tenant):
    TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults=dict(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(days=365),
            valid_until=None,
        ),
    )


def _make_order(reseller=None):
    """Order with one share-article line + one crate row.

    Returns ``(order, order_content, crate_order_content)``.
    """
    order = OrderFactory(reseller=reseller or ResellerFactory())
    oc = OrderContentFactory(
        order=order,
        amount=Decimal("10.000"),
        price_per_unit=Decimal("2.50"),
        rabatt=5,
        unit="KG",
        size="M",
    )
    coc = CrateOrderContent.objects.create(
        order=order,
        crate_type=CrateFactory(),
        amount=4,
        price_per_unit=Decimal("1.50"),
        rabatt=0,
        tax_rate=Decimal("19.00"),
    )
    return order, oc, coc


def _make_dn_with_invoice(tenant):
    """Create order → DN → invoice and return all three."""
    _ensure_settings(connection.tenant)
    order, oc, coc = _make_order()
    dn = DeliveryNoteService.create_from_order(order=order)
    invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
    return order, oc, coc, dn, invoice


# ===================================================================
# Snapshot population
# ===================================================================
@pytest.mark.django_db
class TestSnapshotPopulation:
    def test_delivery_note_line_item_snapshots_populated_from_order(self, tenant):
        _ensure_settings(connection.tenant)
        order, oc, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        line = dn.items.get()
        assert line.source_amount == oc.amount
        assert line.source_price_per_unit == oc.price_per_unit
        assert line.source_rabatt == oc.rabatt
        assert line.source_unit == oc.unit
        assert line.source_size == oc.size

    def test_delivery_note_crate_item_snapshots_populated(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, coc = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        crate = dn.crate_items.get()
        # source_amount stored as Decimal even for integer crate amounts.
        assert crate.source_amount == Decimal(coc.amount)
        assert crate.source_price_per_unit == coc.price_per_unit
        assert crate.source_rabatt == coc.rabatt
        # unit/size do not apply to crates → NULL.
        assert crate.source_unit is None
        assert crate.source_size is None

    def test_invoice_line_item_snapshots_populated_from_dn(self, tenant):
        order, oc, _, dn, invoice = _make_dn_with_invoice(tenant)
        dn_line = dn.items.get()
        inv_line = invoice.items.get()
        assert inv_line.source_amount == dn_line.amount
        assert inv_line.source_price_per_unit == dn_line.price_per_unit
        assert inv_line.source_rabatt == dn_line.rabatt
        assert inv_line.source_unit == dn_line.unit
        assert inv_line.source_size == dn_line.size

    def test_invoice_crate_item_snapshots_populated(self, tenant):
        order, _, _, dn, invoice = _make_dn_with_invoice(tenant)
        dn_crate = dn.crate_items.get()
        inv_crate = invoice.crate_items.get()
        assert inv_crate.source_amount == Decimal(dn_crate.amount)
        assert inv_crate.source_price_per_unit == dn_crate.price_per_unit
        assert inv_crate.source_rabatt == dn_crate.rabatt


# ===================================================================
# Delivery note serializers
# ===================================================================
@pytest.mark.django_db
class TestDeliveryNoteDiffs:
    def test_no_diff_when_local_matches_snapshot(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        line = dn.items.get()
        crate = dn.crate_items.get()

        line_data = DeliveryNoteResellerContentSerializer(line).data
        crate_data = CrateDeliveryNoteContentSerializer(crate).data

        for f in (
            "amount_differs",
            "price_per_unit_differs",
            "rabatt_differs",
            "unit_differs",
            "size_differs",
        ):
            assert line_data[f] is False, f
        for f in ("amount_differs", "price_per_unit_differs", "rabatt_differs"):
            assert crate_data[f] is False, f

    def test_diff_flips_on_local_edit(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        line = dn.items.get()

        line.amount = Decimal("99.000")
        line.price_per_unit = Decimal("9.99")
        line.rabatt = 50
        line.unit = "PC"
        line.size = "S"
        line.save()

        data = DeliveryNoteResellerContentSerializer(line).data
        assert data["amount_differs"] is True
        assert data["price_per_unit_differs"] is True
        assert data["rabatt_differs"] is True
        assert data["unit_differs"] is True
        assert data["size_differs"] is True
        # original_* exposes the snapshot.
        assert Decimal(data["original_amount"]) == Decimal("10.000")
        assert Decimal(data["original_price_per_unit"]) == Decimal("2.50")
        assert data["original_rabatt"] == 5
        assert data["original_unit"] == "KG"
        assert data["original_size"] == "M"

    def test_crate_diff_flips_on_local_edit(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        crate = dn.crate_items.get()

        crate.amount = 99
        crate.price_per_unit = Decimal("9.99")
        crate.rabatt = 50
        crate.save()

        data = CrateDeliveryNoteContentSerializer(crate).data
        assert data["amount_differs"] is True
        assert data["price_per_unit_differs"] is True
        assert data["rabatt_differs"] is True
        assert Decimal(data["original_amount"]) == Decimal("4")
        assert Decimal(data["original_price_per_unit"]) == Decimal("1.50")
        assert data["original_rabatt"] == 0

    def test_null_snapshot_yields_no_diff(self, tenant):
        """Lines without an upstream source (manual / backfilled) never
        report a diff, regardless of local values."""
        _ensure_settings(connection.tenant)
        order, _, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        line = dn.items.get()
        line.source_amount = None
        line.source_price_per_unit = None
        line.source_rabatt = None
        line.source_unit = None
        line.source_size = None
        line.amount = Decimal("99.000")
        line.unit = "WHATEVER"
        line.save()

        data = DeliveryNoteResellerContentSerializer(line).data
        for f in (
            "amount_differs",
            "price_per_unit_differs",
            "rabatt_differs",
            "unit_differs",
            "size_differs",
        ):
            assert data[f] is False, f
        assert data["original_amount"] is None
        assert data["original_unit"] is None


# ===================================================================
# Invoice serializers
# ===================================================================
@pytest.mark.django_db
class TestInvoiceDiffs:
    def test_no_diff_when_local_matches_snapshot(self, tenant):
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        line = invoice.items.get()
        crate = invoice.crate_items.get()

        line_data = InvoiceResellerContentSerializer(line).data
        crate_data = CrateContentInvoiceResellerSerializer(crate).data

        for f in (
            "amount_differs",
            "price_per_unit_differs",
            "rabatt_differs",
            "unit_differs",
            "size_differs",
        ):
            assert line_data[f] is False, f
        for f in ("amount_differs", "price_per_unit_differs", "rabatt_differs"):
            assert crate_data[f] is False, f

    def test_invoice_line_diff_flips_on_local_edit(self, tenant):
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        line = invoice.items.get()

        original_amount = line.source_amount
        original_price = line.source_price_per_unit
        original_rabatt = line.source_rabatt

        line.amount = Decimal("77.000")
        line.price_per_unit = Decimal("8.88")
        line.rabatt = (original_rabatt or 0) + 7
        line.unit = "PC"
        line.size = "S"
        line.save()

        data = InvoiceResellerContentSerializer(line).data
        assert data["amount_differs"] is True
        assert data["price_per_unit_differs"] is True
        assert data["rabatt_differs"] is True
        assert data["unit_differs"] is True
        assert data["size_differs"] is True
        assert Decimal(data["original_amount"]) == original_amount
        assert Decimal(data["original_price_per_unit"]) == original_price
        assert data["original_rabatt"] == original_rabatt

    def test_storno_disables_all_diffs(self, tenant):
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        # Bypass ``full_clean`` (a storno without ``cancels_invoice`` is
        # invalid). We only need the document_type flag for the diff guard.
        InvoiceReseller.objects.filter(pk=invoice.pk).update(document_type="storno")
        line = invoice.items.get()

        # Force a delta locally — the storno guard must still suppress it.
        line.amount = -line.amount
        line.price_per_unit = Decimal("0.01")
        line.unit = "WHATEVER"
        line.save()

        # Refresh the cached invoice on the line so the serializer sees storno.
        line.refresh_from_db()
        line.invoice.refresh_from_db()

        data = InvoiceResellerContentSerializer(line).data
        for f in (
            "amount_differs",
            "price_per_unit_differs",
            "rabatt_differs",
            "unit_differs",
            "size_differs",
        ):
            assert data[f] is False, f
        assert data["original_amount"] is None
        assert data["original_price_per_unit"] is None
        assert data["original_unit"] is None

    def test_correction_disables_all_diffs(self, tenant):
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        InvoiceReseller.objects.filter(pk=invoice.pk).update(document_type="correction")
        line = invoice.items.get()
        line.amount = Decimal("999.999")
        line.save()
        line.refresh_from_db()
        line.invoice.refresh_from_db()

        data = InvoiceResellerContentSerializer(line).data
        assert data["amount_differs"] is False
        assert data["original_amount"] is None

    def test_null_snapshot_yields_no_diff(self, tenant):
        """Summary invoices aggregate multiple DN lines → snapshot is NULL."""
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        line = invoice.items.get()
        line.source_amount = None
        line.source_price_per_unit = None
        line.source_rabatt = None
        line.source_unit = None
        line.source_size = None
        line.amount = Decimal("99.000")
        line.unit = "WHATEVER"
        line.save()

        data = InvoiceResellerContentSerializer(line).data
        for f in (
            "amount_differs",
            "price_per_unit_differs",
            "rabatt_differs",
            "unit_differs",
            "size_differs",
        ):
            assert data[f] is False, f
        assert data["original_amount"] is None
        assert data["original_unit"] is None


# ===================================================================
# Sanity: api shape
# ===================================================================
@pytest.mark.django_db
class TestSerializerShape:
    """The frontend depends on these exact field names being present."""

    EXPECTED_LINE_FIELDS = {
        "amount_differs",
        "original_amount",
        "price_per_unit_differs",
        "original_price_per_unit",
        "rabatt_differs",
        "original_rabatt",
        "unit_differs",
        "original_unit",
        "size_differs",
        "original_size",
    }
    EXPECTED_CRATE_FIELDS = {
        "amount_differs",
        "original_amount",
        "price_per_unit_differs",
        "original_price_per_unit",
        "rabatt_differs",
        "original_rabatt",
    }

    def test_invoice_line_serializer_exposes_diff_fields(self, tenant):
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        data = InvoiceResellerContentSerializer(invoice.items.get()).data
        assert self.EXPECTED_LINE_FIELDS.issubset(data.keys())

    def test_invoice_crate_serializer_exposes_diff_fields(self, tenant):
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        data = CrateContentInvoiceResellerSerializer(invoice.crate_items.get()).data
        assert self.EXPECTED_CRATE_FIELDS.issubset(data.keys())

    def test_delivery_note_line_serializer_exposes_diff_fields(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        data = DeliveryNoteResellerContentSerializer(dn.items.get()).data
        assert self.EXPECTED_LINE_FIELDS.issubset(data.keys())

    def test_delivery_note_crate_serializer_exposes_diff_fields(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _make_order()
        dn = DeliveryNoteService.create_from_order(order=order)
        data = CrateDeliveryNoteContentSerializer(dn.crate_items.get()).data
        assert self.EXPECTED_CRATE_FIELDS.issubset(data.keys())

    def test_no_dead_article_diff_field(self, tenant):
        """``article_differs`` / ``original_share_article_name`` were
        removed when the FK snapshots were dropped — make sure they do
        not reappear."""
        _, _, _, _, invoice = _make_dn_with_invoice(tenant)
        data = InvoiceResellerContentSerializer(invoice.items.get()).data
        assert "article_differs" not in data
        assert "original_share_article_name" not in data
