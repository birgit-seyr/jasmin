"""Which invoice the order view shows for a delivery note.

``OrderContentService.get_offers_and_order_content`` shows each delivery
note's invoice. The services bill a delivery note once — a storno carries no
provenance link, and a re-invoice is refused while any invoice holds the note —
so these tests link the lines directly to build the cases the rule must still
answer deterministically: the newest invoice that isn't cancelled, else the
newest overall, the same for article and crate lines, whatever order the rows
were written in. The lookup's query count must not grow with the invoice lines.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    InvoiceResellerContent,
)
from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderContentFactory,
    OrderFactory,
    ShareArticleFactory,
)

pytestmark = pytest.mark.django_db

OLDER = datetime.date(2026, 3, 2)
NEWER = datetime.date(2026, 3, 9)


def _order_with_delivery_note():
    order = OrderFactory()
    order_content = OrderContentFactory(order=order, offer=None)
    delivery_note = DeliveryNoteResellerFactory(order=order)
    delivery_note_line = DeliveryNoteContentFactory(
        delivery_note=delivery_note, share_article=order_content.share_article
    )
    crate = CrateFactory()
    crate_delivery_note_line = CrateDeliveryNoteContent.objects.create(
        delivery_note=delivery_note,
        crate_type=crate,
        amount=2,
        tax_rate=Decimal("19.00"),
    )
    return order, delivery_note_line, crate_delivery_note_line


def _article_line(invoice, delivery_note_line):
    line = InvoiceResellerContent.objects.create(
        invoice=invoice,
        share_article=delivery_note_line.share_article,
        amount=Decimal("10.000"),
        unit="KG",
        size="M",
        tax_rate=Decimal("7.00"),
    )
    line.delivery_note_contents.add(delivery_note_line)
    return line


def _crate_line(invoice, crate_delivery_note_line):
    line = CrateContentInvoiceReseller.objects.create(
        invoice=invoice,
        crate_type=crate_delivery_note_line.crate_type,
        amount=2,
        tax_rate=Decimal("19.00"),
    )
    line.crate_delivery_note_contents.add(crate_delivery_note_line)
    return line


def _cancel(invoice):
    storno = InvoiceResellerFactory(
        reseller=invoice.reseller,
        document_type="storno",
        cancels_invoice=invoice,
        date=invoice.date,
    )
    invoice.cancelled_by_invoice = storno
    invoice.save(update_fields=["cancelled_by_invoice"])


def _shown_invoice_ids(order):
    result = OrderContentService.get_offers_and_order_content(
        order.reseller_id, order.year, order.delivery_week, order.day_number
    )
    [row] = result["items"]
    return row["invoice_id"], result["order"]["invoice_id"]


def _link(kind, invoice, delivery_note_line, crate_delivery_note_line):
    if kind == "article":
        _article_line(invoice, delivery_note_line)
    else:
        _crate_line(invoice, crate_delivery_note_line)


LINE_KINDS = pytest.mark.parametrize("kind", ["article", "crate"])
CREATION_ORDERS = pytest.mark.parametrize(
    "older_first", [True, False], ids=["older-first", "newer-first"]
)


class TestCurrentInvoiceIsShown:
    @LINE_KINDS
    @CREATION_ORDERS
    def test_cancelled_and_new_invoice_shows_the_new_one(
        self, tenant, kind, older_first
    ):
        order, delivery_note_line, crate_delivery_note_line = (
            _order_with_delivery_note()
        )
        specs = [("cancelled", OLDER), ("current", NEWER)]
        if not older_first:
            specs.reverse()
        invoices = {}
        for name, date in specs:
            invoice = InvoiceResellerFactory(reseller=order.reseller, date=date)
            _link(kind, invoice, delivery_note_line, crate_delivery_note_line)
            invoices[name] = invoice
        _cancel(invoices["cancelled"])

        assert _shown_invoice_ids(order) == (
            invoices["current"].id,
            invoices["current"].id,
        )

    @LINE_KINDS
    @CREATION_ORDERS
    def test_a_cancelled_newer_invoice_loses_to_an_older_current_one(
        self, tenant, kind, older_first
    ):
        order, delivery_note_line, crate_delivery_note_line = (
            _order_with_delivery_note()
        )
        specs = [("current", OLDER), ("cancelled", NEWER)]
        if not older_first:
            specs.reverse()
        invoices = {}
        for name, date in specs:
            invoice = InvoiceResellerFactory(reseller=order.reseller, date=date)
            _link(kind, invoice, delivery_note_line, crate_delivery_note_line)
            invoices[name] = invoice
        _cancel(invoices["cancelled"])

        assert _shown_invoice_ids(order) == (
            invoices["current"].id,
            invoices["current"].id,
        )

    @LINE_KINDS
    @CREATION_ORDERS
    def test_two_current_invoices_show_the_newest(self, tenant, kind, older_first):
        order, delivery_note_line, crate_delivery_note_line = (
            _order_with_delivery_note()
        )
        dates = [OLDER, NEWER] if older_first else [NEWER, OLDER]
        invoices = {}
        for date in dates:
            invoice = InvoiceResellerFactory(reseller=order.reseller, date=date)
            _link(kind, invoice, delivery_note_line, crate_delivery_note_line)
            invoices[date] = invoice

        assert _shown_invoice_ids(order) == (invoices[NEWER].id, invoices[NEWER].id)

    @LINE_KINDS
    @CREATION_ORDERS
    def test_all_cancelled_shows_the_newest(self, tenant, kind, older_first):
        order, delivery_note_line, crate_delivery_note_line = (
            _order_with_delivery_note()
        )
        dates = [OLDER, NEWER] if older_first else [NEWER, OLDER]
        invoices = {}
        for date in dates:
            invoice = InvoiceResellerFactory(reseller=order.reseller, date=date)
            _link(kind, invoice, delivery_note_line, crate_delivery_note_line)
            invoices[date] = invoice
        for invoice in invoices.values():
            _cancel(invoice)

        assert _shown_invoice_ids(order) == (invoices[NEWER].id, invoices[NEWER].id)

    @CREATION_ORDERS
    def test_one_rule_across_article_and_crate_lines(self, tenant, older_first):
        """A current invoice reached only through a crate line beats a
        cancelled one reached through an article line."""
        order, delivery_note_line, crate_delivery_note_line = (
            _order_with_delivery_note()
        )
        cancelled = InvoiceResellerFactory(reseller=order.reseller, date=NEWER)
        current = InvoiceResellerFactory(reseller=order.reseller, date=OLDER)
        links = [
            lambda: _article_line(cancelled, delivery_note_line),
            lambda: _crate_line(current, crate_delivery_note_line),
        ]
        for link in links if older_first else reversed(links):
            link()
        _cancel(cancelled)

        assert _shown_invoice_ids(order) == (current.id, current.id)

    def test_same_date_falls_back_to_creation_time(self, tenant):
        order, delivery_note_line, _ = _order_with_delivery_note()
        first = InvoiceResellerFactory(
            reseller=order.reseller,
            date=OLDER,
            created_at=datetime.datetime(2026, 3, 2, 9, tzinfo=datetime.UTC),
        )
        second = InvoiceResellerFactory(
            reseller=order.reseller,
            date=OLDER,
            created_at=datetime.datetime(2026, 3, 2, 10, tzinfo=datetime.UTC),
        )
        for invoice in (second, first):
            _article_line(invoice, delivery_note_line)

        assert _shown_invoice_ids(order) == (second.id, second.id)

    def test_summary_invoice_of_another_note_does_not_leak_in(self, tenant):
        """A summary invoice's line links several notes; only this order's
        note counts."""
        order, delivery_note_line, _ = _order_with_delivery_note()
        _, other_delivery_note_line, _ = _order_with_delivery_note()
        own = InvoiceResellerFactory(reseller=order.reseller, date=OLDER)
        _article_line(own, delivery_note_line)
        other = InvoiceResellerFactory(reseller=order.reseller, date=NEWER)
        _article_line(other, other_delivery_note_line)

        assert _shown_invoice_ids(order) == (own.id, own.id)


class TestQueryCount:
    def _count_queries(self, line_count: int) -> int:
        order, delivery_note_line, crate_delivery_note_line = (
            _order_with_delivery_note()
        )
        share_article = ShareArticleFactory()
        for _ in range(line_count):
            invoice = InvoiceResellerFactory(reseller=order.reseller, date=OLDER)
            line = InvoiceResellerContent.objects.create(
                invoice=invoice,
                share_article=share_article,
                amount=Decimal("1.000"),
                unit="KG",
                size="M",
                tax_rate=Decimal("7.00"),
            )
            line.delivery_note_contents.add(delivery_note_line)
            _crate_line(invoice, crate_delivery_note_line)
        with CaptureQueriesContext(connection) as queries:
            OrderContentService.get_offers_and_order_content(
                order.reseller_id, order.year, order.delivery_week, order.day_number
            )
        return len(queries.captured_queries)

    def test_query_count_does_not_grow_with_invoice_lines(self, tenant):
        assert self._count_queries(1) == self._count_queries(6)
