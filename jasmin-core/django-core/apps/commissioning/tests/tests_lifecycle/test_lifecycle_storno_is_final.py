"""A cancelled invoice still holds its delivery notes.

A storno is final: the cancelled invoice keeps its provenance links, so every
billing path — single invoice, summary invoice, the summary view's pre-check,
the bulk create endpoint — refuses the note as already invoiced, and the
invoices page counts its order as invoiced. The order overview keeps showing
the cancelled invoice with its storno.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db.models import Exists
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import CrateOrderContent, InvoiceReseller, Reseller
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.commissioning.viewsets.resellers_viewsets import (
    uninvoiced_orders_of_outer_reseller,
)
from core.errors import JasminError

pytestmark = pytest.mark.django_db

LINE_KINDS = pytest.mark.parametrize("kind", ["article", "crate"])


def _finalized_delivery_note(kind, reseller=None, week=15):
    """A finalized delivery note with only article or only crate lines."""
    order = OrderFactory(
        reseller=reseller or ResellerFactory(),
        year=2026,
        delivery_week=week,
        day_number=2,
    )
    if kind == "article":
        OrderContentFactory(
            order=order,
            share_article=ShareArticleFactory(),
            amount=Decimal("2"),
            price_per_unit=Decimal("3.00"),
            tax_rate=Decimal("7"),
            unit="KG",
            size="M",
        )
    else:
        CrateOrderContent.objects.create(
            order=order,
            crate_type=CrateFactory(),
            amount=2,
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("19"),
        )
    delivery_note = DeliveryNoteService.create_from_order(order=order)
    DeliveryNoteService.finalize_delivery_note(delivery_note)
    delivery_note.refresh_from_db()
    return delivery_note


def _cancelled_invoice(delivery_note):
    """Invoice *delivery_note*, finalize the invoice and cancel it."""
    invoice = InvoiceService.create_from_delivery_note(delivery_note)
    InvoiceService.finalize_invoice(invoice)
    invoice.refresh_from_db()
    InvoiceService.create_storno(invoice, reason="wrong amounts")
    invoice.refresh_from_db()
    assert invoice.cancelled_by_invoice_id is not None
    return invoice


def _has_uninvoiced_orders(reseller) -> bool:
    return (
        Reseller.objects.annotate(open=Exists(uninvoiced_orders_of_outer_reseller()))
        .get(pk=reseller.pk)
        .open
    )


class TestSingleInvoice:
    @LINE_KINDS
    def test_a_cancelled_invoice_blocks_a_new_one(self, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        cancelled = _cancelled_invoice(delivery_note)
        invoice_count = InvoiceReseller.objects.count()

        with pytest.raises(JasminError) as excinfo:
            InvoiceService.create_from_delivery_note(delivery_note)

        assert excinfo.value.code == "invoice.already_exists"
        assert InvoiceReseller.objects.count() == invoice_count
        assert InvoiceService.get_invoice_for_delivery_note(delivery_note) == cancelled

    @LINE_KINDS
    def test_an_invoice_that_is_not_cancelled_blocks_a_new_one(self, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        InvoiceService.create_from_delivery_note(delivery_note)

        with pytest.raises(JasminError) as excinfo:
            InvoiceService.create_from_delivery_note(delivery_note)

        assert excinfo.value.code == "invoice.already_exists"


class TestSummaryInvoice:
    @LINE_KINDS
    def test_a_cancelled_summary_blocks_its_notes(self, tenant, kind):
        reseller = ResellerFactory()
        delivery_notes = [
            _finalized_delivery_note(kind, reseller=reseller, week=week)
            for week in (15, 16)
        ]
        summary = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes
        )
        InvoiceService.finalize_invoice(summary)
        summary.refresh_from_db()
        InvoiceService.create_storno(summary, reason="wrong amounts")

        with pytest.raises(JasminError) as excinfo:
            InvoiceService.create_summary_invoice_from_delivery_notes(delivery_notes)

        assert excinfo.value.code == "invoice.already_exists"

    @LINE_KINDS
    def test_a_note_with_a_cancelled_invoice_blocks_the_summary(self, tenant, kind):
        reseller = ResellerFactory()
        cancelled_note = _finalized_delivery_note(kind, reseller=reseller, week=15)
        fresh_note = _finalized_delivery_note(kind, reseller=reseller, week=16)
        cancelled = _cancelled_invoice(cancelled_note)

        with pytest.raises(JasminError) as excinfo:
            InvoiceService.create_summary_invoice_from_delivery_notes(
                [cancelled_note, fresh_note]
            )

        assert excinfo.value.code == "invoice.already_exists"
        assert str(excinfo.value).endswith(f": {cancelled.number}")
        assert InvoiceService.get_invoice_for_delivery_note(fresh_note) is None


class TestSummaryInvoiceView:
    @LINE_KINDS
    def test_the_pre_check_refuses_a_note_with_a_cancelled_invoice(
        self, api_client, tenant, kind
    ):
        delivery_note = _finalized_delivery_note(kind)
        _cancelled_invoice(delivery_note)

        response = api_client.post(
            reverse("bulk_create_summary_invoice_from_orders"),
            {"ids": [str(delivery_note.order.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "summary_invoice.no_valid_dns"


class TestBulkCreateInvoice:
    @LINE_KINDS
    def test_a_cancelled_invoice_is_reported_as_existing(
        self, api_client, tenant, kind
    ):
        delivery_note = _finalized_delivery_note(kind)
        cancelled = _cancelled_invoice(delivery_note)

        response = api_client.post(
            reverse("bulk_create_documents_from_orders"),
            {"model": "invoice", "ids": [str(delivery_note.order.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_207_MULTI_STATUS
        assert response.data["successful"] == 0
        assert response.data["failed"] == 1
        (error,) = response.data["errors"]
        assert error["order_id"] == delivery_note.order.id
        assert "Invoice already exists" in error["error"]
        assert InvoiceService.get_invoice_for_delivery_note(delivery_note) == cancelled


class TestUninvoicedOrders:
    @LINE_KINDS
    def test_a_cancelled_invoice_counts_as_invoiced(self, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        reseller = delivery_note.order.reseller
        assert _has_uninvoiced_orders(reseller)

        _cancelled_invoice(delivery_note)

        assert not _has_uninvoiced_orders(reseller)


class TestOrderOverviewRow:
    @LINE_KINDS
    def test_a_cancelled_invoice_shows_with_its_storno(self, api_client, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        cancelled = _cancelled_invoice(delivery_note)
        storno = cancelled.cancelled_by_invoice

        response = api_client.get(reverse("orders_overview"), {"year": 2026})

        assert response.status_code == status.HTTP_200_OK
        (row,) = [
            row for row in response.data if row["delivery_note_id"] == delivery_note.pk
        ]
        assert row["has_invoice"] is True
        assert row["invoice_id"] == cancelled.pk
        assert row["invoice_number"] == cancelled.full_number
        assert row["invoice_cancelled_by"] == storno.pk
        assert row["invoice_storno_id"] == storno.pk
        assert row["invoice_storno_number"] == storno.full_number
