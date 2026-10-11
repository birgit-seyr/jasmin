"""Billing a delivery note again once its invoice is cancelled.

A delivery note is billed while an invoice that isn't cancelled holds it. A
storno frees the note: a new invoice — single or summary — may bill it again,
while the cancelled invoice keeps its links. Every lookup then shows the new
invoice. An invoice that isn't cancelled still blocks a second one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db.models import Exists
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import CrateOrderContent, Reseller
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.tests.factories import (
    CrateFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.commissioning.views.reseller_views import CombinedOrderOverviewView
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


def _finalize_and_cancel(invoice):
    InvoiceService.finalize_invoice(invoice)
    invoice.refresh_from_db()
    InvoiceService.create_storno(invoice, reason="wrong amounts")
    invoice.refresh_from_db()
    assert invoice.cancelled_by_invoice_id is not None


def _has_uninvoiced_orders(reseller) -> bool:
    return (
        Reseller.objects.annotate(open=Exists(uninvoiced_orders_of_outer_reseller()))
        .get(pk=reseller.pk)
        .open
    )


def _assert_every_lookup_shows(delivery_note, invoice):
    assert InvoiceService.get_invoice_for_delivery_note(delivery_note) == invoice
    assert InvoiceService.get_invoices_for_delivery_notes([delivery_note.pk]) == {
        delivery_note.pk: invoice
    }
    assert CombinedOrderOverviewView._invoices_by_delivery_note([delivery_note.pk]) == {
        delivery_note.pk: invoice
    }
    order = delivery_note.order
    shown = OrderContentService.get_offers_and_order_content(
        order.reseller_id, order.year, order.delivery_week, order.day_number
    )
    assert shown["order"]["invoice_id"] == invoice.id
    assert all(item["invoice_id"] == invoice.id for item in shown["items"])


class TestSingleInvoice:
    @LINE_KINDS
    def test_a_cancelled_invoice_frees_the_note(self, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        cancelled = InvoiceService.create_from_delivery_note(delivery_note)
        _finalize_and_cancel(cancelled)
        assert _has_uninvoiced_orders(delivery_note.order.reseller)

        new = InvoiceService.create_from_delivery_note(delivery_note)

        assert new.pk != cancelled.pk
        lines = new.items if kind == "article" else new.crate_items
        assert lines.count() == 1
        # The cancelled invoice keeps its links to the note.
        cancelled_lines = (
            cancelled.items if kind == "article" else cancelled.crate_items
        )
        assert cancelled_lines.count() == 1
        _assert_every_lookup_shows(delivery_note, new)
        assert not _has_uninvoiced_orders(delivery_note.order.reseller)

    @LINE_KINDS
    def test_an_invoice_that_is_not_cancelled_still_blocks(self, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        InvoiceService.create_from_delivery_note(delivery_note)

        with pytest.raises(JasminError, match="already exists"):
            InvoiceService.create_from_delivery_note(delivery_note)

    @LINE_KINDS
    def test_the_new_invoice_blocks_a_third(self, tenant, kind):
        delivery_note = _finalized_delivery_note(kind)
        _finalize_and_cancel(InvoiceService.create_from_delivery_note(delivery_note))
        InvoiceService.create_from_delivery_note(delivery_note)

        with pytest.raises(JasminError, match="already exists"):
            InvoiceService.create_from_delivery_note(delivery_note)


class TestSummaryInvoice:
    @LINE_KINDS
    def test_a_cancelled_summary_frees_its_notes(self, tenant, kind):
        reseller = ResellerFactory()
        delivery_notes = [
            _finalized_delivery_note(kind, reseller=reseller, week=week)
            for week in (15, 16)
        ]
        cancelled = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes
        )
        _finalize_and_cancel(cancelled)

        new = InvoiceService.create_summary_invoice_from_delivery_notes(delivery_notes)

        assert new.pk != cancelled.pk
        for delivery_note in delivery_notes:
            _assert_every_lookup_shows(delivery_note, new)

    @LINE_KINDS
    def test_a_note_freed_by_a_single_storno_joins_a_summary(self, tenant, kind):
        reseller = ResellerFactory()
        cancelled_note = _finalized_delivery_note(kind, reseller=reseller, week=15)
        fresh_note = _finalized_delivery_note(kind, reseller=reseller, week=16)
        _finalize_and_cancel(InvoiceService.create_from_delivery_note(cancelled_note))

        summary = InvoiceService.create_summary_invoice_from_delivery_notes(
            [cancelled_note, fresh_note]
        )

        _assert_every_lookup_shows(cancelled_note, summary)
        _assert_every_lookup_shows(fresh_note, summary)

    @LINE_KINDS
    def test_an_invoice_that_is_not_cancelled_still_blocks(self, tenant, kind):
        reseller = ResellerFactory()
        delivery_notes = [
            _finalized_delivery_note(kind, reseller=reseller, week=week)
            for week in (15, 16)
        ]
        InvoiceService.create_from_delivery_note(delivery_notes[0])

        with pytest.raises(JasminError, match="already invoiced"):
            InvoiceService.create_summary_invoice_from_delivery_notes(delivery_notes)


class TestSummaryInvoiceView:
    @LINE_KINDS
    def test_a_cancelled_invoice_frees_the_note_for_the_view(
        self, api_client, tenant, kind
    ):
        delivery_note = _finalized_delivery_note(kind)
        _finalize_and_cancel(InvoiceService.create_from_delivery_note(delivery_note))

        response = api_client.post(
            reverse("bulk_create_summary_invoice_from_orders"),
            {"ids": [str(delivery_note.order.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        new = InvoiceService.get_invoice_for_delivery_note(delivery_note)
        assert new.id == response.data["invoice_id"]
        assert new.cancelled_by_invoice_id is None

    @LINE_KINDS
    def test_an_invoice_that_is_not_cancelled_still_blocks_the_view(
        self, api_client, tenant, kind
    ):
        delivery_note = _finalized_delivery_note(kind)
        InvoiceService.create_from_delivery_note(delivery_note)

        response = api_client.post(
            reverse("bulk_create_summary_invoice_from_orders"),
            {"ids": [str(delivery_note.order.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "summary_invoice.no_valid_dns"
