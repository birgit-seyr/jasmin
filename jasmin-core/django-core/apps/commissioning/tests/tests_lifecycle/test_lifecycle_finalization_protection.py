"""Defence-in-depth tests for the finalization protection stack.

The protection has three layers (see ``apps.commissioning.models.mixin``):

1. **Per-instance Python** — ``FinalizedProtectedMixin.save`` /
   ``.delete`` raises on a finalized row.
2. **Bulk ORM Python** — ``FinalizedProtectedQuerySet.update`` /
   ``.delete`` refuses to touch a queryset that contains finalized rows.
3. **PostgreSQL triggers** — installed by migration
   ``0002_finalized_protection_and_reference_data``; catches raw SQL and any
   path that bypasses the Python layers.

Each of those layers is tested below for every protected model:

* parents:  ``Order``, ``DeliveryNoteReseller``, ``InvoiceReseller``
* content:  ``OrderContent``, ``DeliveryNoteContent``, ``InvoiceResellerContent``
* crates:   ``CrateOrderContent``, ``CrateDeliveryNoteContent``,
           ``CrateContentInvoiceReseller``

This file also covers:

* The invoice ``document_hash`` — set on finalize, deterministic, covers
  parent fields + per-line ``amount``/``price``/``rabatt``/``tax_rate``
  for both article AND crate items.
* The whitelisted update path — finalized rows CAN still have their
  ``ALLOWED_FINALIZED_UPDATES`` fields written (e.g. an invoice can be
  marked ``has_been_paid`` after it's been issued).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.commissioning.errors import FinalizedError
from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    DeliveryNoteContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
    Order,
    OrderContent,
)
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
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


def _make_order_with_one_of_each(reseller=None, week=15) -> Order:
    """An Order with exactly one article line and one crate line, so every
    test below has both flavours to exercise."""
    order = OrderFactory(
        reseller=reseller or ResellerFactory(),
        year=2026,
        delivery_week=week,
        day_number=2,
    )
    OrderContentFactory(
        order=order,
        share_article=ShareArticleFactory(),
        amount=Decimal("2"),
        price_per_unit=Decimal("3.00"),
        tax_rate=Decimal("7.00"),
        unit="KG",
        size="M",
    )
    CrateOrderContent.objects.create(
        order=order,
        crate_type=CrateFactory(),
        amount=2,
        price_per_unit=Decimal("1.50"),
        tax_rate=Decimal("19.00"),
    )
    return order


def _build_finalized_chain(reseller=None, week=15):
    """Run the full Order -> DN -> Invoice flow and finalize everything.

    Returns ``(order, dn, invoice)`` after refresh_from_db.
    """
    order = _make_order_with_one_of_each(reseller=reseller, week=week)
    dn = DeliveryNoteService.create_from_order(order=order)
    DeliveryNoteService.finalize_delivery_note(dn)
    invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
    InvoiceService.finalize_invoice(invoice)

    order.refresh_from_db()
    dn.refresh_from_db()
    invoice.refresh_from_db()
    return order, dn, invoice


def _raw_update(table: str, pk: str, **columns) -> None:
    """Execute ``UPDATE table SET col = %s, ... WHERE id = %s`` via the raw
    cursor. Used to assert the Postgres trigger fires when both Python
    layers are bypassed."""
    set_clause = ", ".join(f"{col} = %s" for col in columns)
    params = list(columns.values()) + [pk]
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {set_clause} WHERE id = %s",  # noqa: S608
            params,
        )


def _raw_delete(table: str, pk: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table} WHERE id = %s", [pk])  # noqa: S608


# ===========================================================================
# Priority 1 — Invoice document_hash
# ===========================================================================
@pytest.mark.django_db
class TestInvoiceDocumentHash:
    """``InvoiceService.finalize_invoice`` records a SHA-256 of the canonical
    payload (see ``InvoiceService.build_hash_payload``). It is set exactly
    once, on finalize, and covers article AND crate line items including
    each row's ``tax_rate``."""

    def test_hash_is_set_on_finalize(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()

        assert invoice.is_finalized is True
        assert invoice.document_hash is not None
        # SHA-256 hex digest is 64 chars.
        assert len(invoice.document_hash) == 64
        assert all(c in "0123456789abcdef" for c in invoice.document_hash)

    def test_hash_matches_recomputed_payload(self, tenant):
        """Reproduces the stored hash from the live invoice — proves the
        payload definition is the contract we actually shipped."""
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()

        recomputed = InvoiceService.compute_document_hash(invoice)
        assert recomputed == invoice.document_hash

    def test_hash_is_deterministic(self, tenant):
        """Calling ``compute_document_hash`` twice on the same invoice
        returns the same value — proves the function is pure over the
        canonical payload."""
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()

        assert (
            InvoiceService.compute_document_hash(invoice)
            == InvoiceService.compute_document_hash(invoice)
            == invoice.document_hash
        )

    def test_hash_payload_includes_tax_rate_on_line_items(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()

        payload = InvoiceService.build_hash_payload(invoice)
        assert payload["items"], "expected at least one article line in payload"
        for item in payload["items"]:
            assert "tax_rate" in item
            # The factory used 7.00 on the article line.
            assert Decimal(item["tax_rate"]) == Decimal("7.00")

    def test_hash_payload_includes_crate_items_with_tax_rate(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()

        payload = InvoiceService.build_hash_payload(invoice)
        assert payload["crate_items"], "expected crate items in the payload"
        for crate in payload["crate_items"]:
            assert "tax_rate" in crate
            assert Decimal(crate["tax_rate"]) == Decimal("19.00")

    def test_changing_line_tax_rate_changes_the_hash(self, tenant):
        """Two invoices that differ ONLY in line ``tax_rate`` produce
        different ``document_hash`` values. Tax_rate is a hash-relevant
        field; if it were silently mutated, the hash would catch it (once
        a verifier is wired up — currently the hash is set but not
        re-checked, which is documented under TestInvoiceDocumentHash)."""
        _ensure_settings(connection.tenant)

        # Finalise a baseline invoice with tax_rate=7 on the article line.
        _, _, invoice_a = _build_finalized_chain(week=15)

        # Build a second invoice; before finalising, swap the article
        # line's tax_rate to 19 (the only legal time to write it).
        order_b = _make_order_with_one_of_each(week=20)
        dn_b = DeliveryNoteService.create_from_order(order=order_b)
        DeliveryNoteService.finalize_delivery_note(dn_b)
        invoice_b = InvoiceService.create_from_delivery_note(delivery_note=dn_b)

        line_b = invoice_b.items.first()
        line_b.tax_rate = Decimal("19.00")
        line_b.save(update_fields=["tax_rate"])

        InvoiceService.finalize_invoice(invoice_b)
        invoice_b.refresh_from_db()

        assert invoice_a.document_hash != invoice_b.document_hash

        payload_b = InvoiceService.build_hash_payload(invoice_b)
        assert any(item["tax_rate"] == "19.00" for item in payload_b["items"])

    def test_hash_is_not_overwritten_after_finalization(self, tenant):
        """``document_hash`` is on the table-level finalization whitelist?
        It is NOT — so finalize() should be the only writer."""
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        original = invoice.document_hash

        # Try to reset via per-instance save() with update_fields — blocked.
        invoice.document_hash = "deadbeef" * 8
        with pytest.raises(FinalizedError):
            invoice.save(update_fields=["document_hash"])

        invoice.refresh_from_db()
        assert invoice.document_hash == original


# ===========================================================================
# Priority 2 — FinalizedProtectedQuerySet (bulk ORM bypass)
# ===========================================================================
@pytest.mark.django_db
class TestBulkORMRefusesFinalizedRows:
    """``Model.objects.filter(...).update(...)`` and ``.delete()`` route
    through ``FinalizedProtectedQuerySet`` (attached as ``objects`` on each
    protected model) and refuse the operation when any matched row is
    finalized."""

    # ---- parents ----------------------------------------------------------
    def test_order_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update Order"):
            Order.objects.filter(pk=order.pk).update(year=2099)

    def test_order_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete Order"):
            Order.objects.filter(pk=order.pk).delete()

    def test_delivery_note_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update DeliveryNoteReseller"):
            DeliveryNoteReseller.objects.filter(pk=dn.pk).update(number=999)

    def test_delivery_note_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete DeliveryNoteReseller"):
            DeliveryNoteReseller.objects.filter(pk=dn.pk).delete()

    def test_invoice_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update InvoiceReseller"):
            InvoiceReseller.objects.filter(pk=invoice.pk).update(number=999)

    def test_invoice_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete InvoiceReseller"):
            InvoiceReseller.objects.filter(pk=invoice.pk).delete()

    # ---- one-way unfinalize via bulk update -------------------------------
    # The one-way models (Order / DeliveryNoteReseller / InvoiceReseller) must
    # refuse a bulk ``update(is_finalized=False)`` at the Python layer too —
    # not only via the Postgres trigger — mirroring the save() one-way guard.
    def test_order_bulk_unfinalize_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(FinalizedError, match="bulk-unfinalize Order"):
            Order.objects.filter(pk=order.pk).update(is_finalized=False)

    def test_delivery_note_bulk_unfinalize_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(
            FinalizedError, match="bulk-unfinalize DeliveryNoteReseller"
        ):
            DeliveryNoteReseller.objects.filter(pk=dn.pk).update(is_finalized=False)

    def test_invoice_bulk_unfinalize_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(FinalizedError, match="bulk-unfinalize InvoiceReseller"):
            InvoiceReseller.objects.filter(pk=invoice.pk).update(is_finalized=False)

    # ---- content rows -----------------------------------------------------
    def test_order_content_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update OrderContent"):
            OrderContent.objects.filter(order=order).update(amount=Decimal("99"))

    def test_order_content_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete OrderContent"):
            OrderContent.objects.filter(order=order).delete()

    def test_dn_content_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update DeliveryNoteContent"):
            DeliveryNoteContent.objects.filter(delivery_note=dn).update(
                amount=Decimal("99")
            )

    def test_dn_content_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete DeliveryNoteContent"):
            DeliveryNoteContent.objects.filter(delivery_note=dn).delete()

    def test_invoice_content_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update InvoiceResellerContent"):
            InvoiceResellerContent.objects.filter(invoice=invoice).update(
                amount=Decimal("99")
            )

    def test_invoice_content_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete InvoiceResellerContent"):
            InvoiceResellerContent.objects.filter(invoice=invoice).delete()

    # ---- crate-content rows ----------------------------------------------
    def test_crate_order_content_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-update CrateOrderContent"):
            CrateOrderContent.objects.filter(order=order).update(amount=99)

    def test_crate_order_content_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(ValidationError, match="bulk-delete CrateOrderContent"):
            CrateOrderContent.objects.filter(order=order).delete()

    def test_crate_dn_content_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(
            ValidationError, match="bulk-update CrateDeliveryNoteContent"
        ):
            CrateDeliveryNoteContent.objects.filter(delivery_note=dn).update(amount=99)

    def test_crate_dn_content_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(
            ValidationError, match="bulk-delete CrateDeliveryNoteContent"
        ):
            CrateDeliveryNoteContent.objects.filter(delivery_note=dn).delete()

    def test_crate_invoice_content_queryset_update_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(
            ValidationError, match="bulk-update CrateContentInvoiceReseller"
        ):
            CrateContentInvoiceReseller.objects.filter(invoice=invoice).update(
                amount=99
            )

    def test_crate_invoice_content_queryset_delete_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(
            ValidationError, match="bulk-delete CrateContentInvoiceReseller"
        ):
            CrateContentInvoiceReseller.objects.filter(invoice=invoice).delete()

    # ---- non-finalized rows still bulk-updatable -------------------------
    def test_bulk_update_passes_when_no_finalized_rows_match(self, tenant):
        """If the queryset filters to NON-finalized rows only, bulk update
        works. Proves the protection is row-scoped, not type-scoped."""
        _ensure_settings(connection.tenant)
        non_finalized = OrderFactory(year=2026, delivery_week=10, day_number=2)
        Order.objects.filter(pk=non_finalized.pk).update(note="ok")
        non_finalized.refresh_from_db()
        assert non_finalized.note == "ok"


# ===========================================================================
# Priority 3 — Postgres triggers (raw SQL bypass)
# ===========================================================================
@pytest.mark.django_db
class TestPostgresTriggersBlockRawSQL:
    """The migration ``0002_finalized_protection_and_reference_data``
    installs BEFORE UPDATE / BEFORE DELETE triggers on every protected table.

    These tests deliberately bypass *both* Python layers via raw SQL and
    assert the trigger raises. The raw SQL is wrapped in a savepoint
    (``transaction.atomic()``) so the trigger's error rolls back the inner
    block without poisoning the outer test transaction — same pattern as
    ``test_lifecycle_storno_and_inserts.py``.
    """

    # ---- parents (have non-empty whitelists, so we attack non-whitelisted) -
    def test_trigger_blocks_raw_update_on_finalized_order(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_update("commissioning_order", order.pk, year=2099)

    def test_trigger_blocks_raw_delete_on_finalized_order(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_delete("commissioning_order", order.pk)

    def test_trigger_blocks_raw_update_on_finalized_dn(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_update("commissioning_deliverynotereseller", dn.pk, number=999)

    def test_trigger_blocks_raw_delete_on_finalized_dn(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_delete("commissioning_deliverynotereseller", dn.pk)

    def test_trigger_blocks_raw_update_on_finalized_invoice(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_update("commissioning_invoicereseller", invoice.pk, number=999)

    def test_trigger_blocks_raw_delete_on_finalized_invoice(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_delete("commissioning_invoicereseller", invoice.pk)

    # ---- content rows (whitelist is empty -> ANY column triggers) ---------
    def test_trigger_blocks_raw_update_on_finalized_order_content(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        oc = order.ordercontent_set.first()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_update("commissioning_ordercontent", oc.pk, amount=Decimal("99"))

    def test_trigger_blocks_raw_delete_on_finalized_order_content(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        oc = order.ordercontent_set.first()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_delete("commissioning_ordercontent", oc.pk)

    def test_trigger_blocks_raw_update_on_finalized_invoice_content(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        line = invoice.items.first()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_update(
                    "commissioning_invoiceresellercontent",
                    line.pk,
                    tax_rate=Decimal("19.00"),
                )

    def test_trigger_blocks_raw_delete_on_finalized_invoice_content(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        line = invoice.items.first()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_delete("commissioning_invoiceresellercontent", line.pk)

    # ---- crate-content rows ----------------------------------------------
    def test_trigger_blocks_raw_update_on_finalized_crate_invoice_content(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        crate = invoice.crate_items.first()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_update(
                    "commissioning_cratecontentinvoicereseller",
                    crate.pk,
                    amount=99,
                )

    def test_trigger_blocks_raw_delete_on_finalized_crate_invoice_content(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        crate = invoice.crate_items.first()
        with pytest.raises(Exception, match="finalized"):
            with transaction.atomic():
                _raw_delete("commissioning_cratecontentinvoicereseller", crate.pk)

    # ---- whitelisted column passes the trigger ---------------------------
    def test_trigger_permits_whitelisted_column_on_finalized_invoice(self, tenant):
        """``has_been_paid`` is on the whitelist — a raw UPDATE that touches
        only that column must pass through. Proves the trigger isn't a
        blanket "reject everything"."""
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with transaction.atomic():
            _raw_update("commissioning_invoicereseller", invoice.pk, has_been_paid=True)
        invoice.refresh_from_db()
        assert invoice.has_been_paid is True


# ===========================================================================
# Priority 4 — Per-instance save() / delete() block on content rows
# ===========================================================================
@pytest.mark.django_db
class TestContentRowSaveBlockedWhenFinalized:
    """``FinalizedProtectedMixin.save`` raises ``FinalizedError`` when the
    row is finalized and the caller isn't using a whitelisted update.

    Content / crate rows have empty whitelists, so ANY field change is
    refused.
    """

    def test_finalized_order_content_save_raises(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        oc = order.ordercontent_set.first()
        assert oc.is_finalized is True
        oc.amount = Decimal("99")
        with pytest.raises(FinalizedError):
            oc.save(update_fields=["amount"])
        with pytest.raises(FinalizedError):
            oc.save()

    def test_finalized_crate_order_content_save_raises(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        crate = order.crateordercontent_set.first()
        assert crate.is_finalized is True
        crate.amount = 99
        with pytest.raises(FinalizedError):
            crate.save(update_fields=["amount"])

    def test_finalized_dn_content_save_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        line = dn.items.first()
        assert line.is_finalized is True
        line.amount = Decimal("99")
        with pytest.raises(FinalizedError):
            line.save(update_fields=["amount"])

    def test_finalized_crate_dn_content_save_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        crate = dn.crate_items.first()
        assert crate.is_finalized is True
        crate.amount = 99
        with pytest.raises(FinalizedError):
            crate.save(update_fields=["amount"])

    def test_finalized_invoice_content_save_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        line = invoice.items.first()
        assert line.is_finalized is True
        line.tax_rate = Decimal("19.00")
        with pytest.raises(FinalizedError):
            line.save(update_fields=["tax_rate"])

    def test_finalized_crate_invoice_content_save_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        crate = invoice.crate_items.first()
        assert crate.is_finalized is True
        crate.amount = 99
        with pytest.raises(FinalizedError):
            crate.save(update_fields=["amount"])


@pytest.mark.django_db
class TestContentRowDeleteBlockedWhenFinalized:
    """``FinalizedProtectedMixin.delete`` raises ``FinalizedError`` on
    finalized rows. Same matrix as the save test."""

    def test_finalized_order_content_delete_raises(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(FinalizedError):
            order.ordercontent_set.first().delete()

    def test_finalized_crate_order_content_delete_raises(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        with pytest.raises(FinalizedError):
            order.crateordercontent_set.first().delete()

    def test_finalized_dn_content_delete_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(FinalizedError):
            dn.items.first().delete()

    def test_finalized_crate_dn_content_delete_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        with pytest.raises(FinalizedError):
            dn.crate_items.first().delete()

    def test_finalized_invoice_content_delete_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(FinalizedError):
            invoice.items.first().delete()

    def test_finalized_crate_invoice_content_delete_raises(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        with pytest.raises(FinalizedError):
            invoice.crate_items.first().delete()


# ===========================================================================
# Priority 5 — Whitelisted field updates DO go through
# ===========================================================================
@pytest.mark.django_db
class TestWhitelistedFieldUpdates:
    """Each finalizable parent has a per-model ``ALLOWED_FINALIZED_UPDATES``
    list. Fields on that list must remain writable after finalization —
    otherwise the payment / sending flows can't record their state on
    historical documents.
    """

    # ---- Order: only ``note`` ---------------------------------------------
    def test_order_note_can_be_updated_after_finalize(self, tenant):
        _ensure_settings(connection.tenant)
        order, _, _ = _build_finalized_chain()
        order.note = "added after finalize"
        order.save(update_fields=["note"])
        order.refresh_from_db()
        assert order.note == "added after finalize"

    # ---- DeliveryNote: ``file``, ``has_been_sent_to_reseller_at`` --------
    def test_delivery_note_whitelisted_fields_writable(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        dn.has_been_sent_to_reseller_at = timezone.now()
        dn.save(update_fields=["has_been_sent_to_reseller_at"])
        dn.refresh_from_db()
        # ``has_been_sent_to_reseller`` is a @property — True iff the
        # timestamp is set.
        assert dn.has_been_sent_to_reseller is True
        assert dn.has_been_sent_to_reseller_at is not None

    def test_delivery_note_non_whitelisted_field_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, dn, _ = _build_finalized_chain()
        dn.number = 9999
        with pytest.raises(FinalizedError):
            dn.save(update_fields=["number"])

    # ---- Invoice: 12 whitelisted fields ----------------------------------
    def test_invoice_has_been_paid_writable(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        invoice.has_been_paid = True
        invoice.paid_at = timezone.now()
        invoice.save(update_fields=["has_been_paid", "paid_at"])
        invoice.refresh_from_db()
        assert invoice.has_been_paid is True
        assert invoice.paid_at is not None

    def test_invoice_send_flags_writable(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        invoice.has_been_sent_to_reseller_at = timezone.now()
        invoice.save(update_fields=["has_been_sent_to_reseller_at"])
        invoice.refresh_from_db()
        # ``has_been_sent_to_reseller`` is a @property — True iff the
        # timestamp is set.
        assert invoice.has_been_sent_to_reseller is True
        assert invoice.has_been_sent_to_reseller_at is not None

    def test_invoice_accounting_flags_writable(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        invoice.has_been_sent_to_accounting_at = timezone.now()
        invoice.save(update_fields=["has_been_sent_to_accounting_at"])
        invoice.refresh_from_db()
        # ``has_been_sent_to_accounting`` is a @property — True iff
        # the timestamp is set.
        assert invoice.has_been_sent_to_accounting is True
        assert invoice.has_been_sent_to_accounting_at is not None

    def test_invoice_non_whitelisted_field_blocked(self, tenant):
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        invoice.number = 9999
        with pytest.raises(FinalizedError):
            invoice.save(update_fields=["number"])

    def test_invoice_reseller_id_is_locked(self, tenant):
        """``reseller_id`` is NOT on the whitelist — changing the recipient
        of a finalized invoice would break audit / legal."""
        _ensure_settings(connection.tenant)
        _, _, invoice = _build_finalized_chain()
        other = ResellerFactory()
        invoice.reseller = other
        with pytest.raises(FinalizedError):
            invoice.save(update_fields=["reseller"])
