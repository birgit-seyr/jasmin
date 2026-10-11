"""Which invoice ``InvoiceService`` resolves for a delivery note.

``get_invoice_for_delivery_note`` and its batch form
``get_invoices_for_delivery_notes`` answer with the current invoice: the newest
that isn't cancelled, else the newest overall, over article and crate lines
alike and whatever order the rows were written in. The lines are linked
directly, as the services refuse to bill a note twice.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import InvoiceResellerFactory
from apps.commissioning.tests.tests_services.test_order_view_invoice_lookup import (
    NEWER,
    OLDER,
    _article_line,
    _cancel,
    _crate_line,
    _link,
    _order_with_delivery_note,
)

pytestmark = pytest.mark.django_db

LINE_KINDS = pytest.mark.parametrize("kind", ["article", "crate"])
CREATION_ORDERS = pytest.mark.parametrize(
    "older_first", [True, False], ids=["older-first", "newer-first"]
)


def _single(delivery_note):
    invoice = InvoiceService.get_invoice_for_delivery_note(delivery_note)
    return invoice.id if invoice else None


def _batch(delivery_note):
    invoice = InvoiceService.get_invoices_for_delivery_notes([delivery_note.pk]).get(
        delivery_note.pk
    )
    return invoice.id if invoice else None


LOOKUPS = pytest.mark.parametrize("lookup", [_single, _batch], ids=["single", "batch"])


def _invoices_on_note(kind, older_first, cancelled_date, current_date):
    """A delivery note reaching a cancelled and a current invoice through
    ``kind`` lines, the lines written in the given order."""
    order, delivery_note_line, crate_delivery_note_line = _order_with_delivery_note()
    specs = [("cancelled", cancelled_date), ("current", current_date)]
    specs.sort(key=lambda spec: spec[1], reverse=not older_first)
    invoices = {}
    for name, date in specs:
        invoice = InvoiceResellerFactory(reseller=order.reseller, date=date)
        _link(kind, invoice, delivery_note_line, crate_delivery_note_line)
        invoices[name] = invoice
    _cancel(invoices["cancelled"])
    return delivery_note_line.delivery_note, invoices


class TestCurrentInvoiceIsResolved:
    @LOOKUPS
    @LINE_KINDS
    @CREATION_ORDERS
    def test_cancelled_and_new_invoice_resolves_the_new_one(
        self, tenant, lookup, kind, older_first
    ):
        delivery_note, invoices = _invoices_on_note(kind, older_first, OLDER, NEWER)

        assert lookup(delivery_note) == invoices["current"].id

    @LOOKUPS
    @LINE_KINDS
    @CREATION_ORDERS
    def test_a_cancelled_newer_invoice_loses_to_an_older_current_one(
        self, tenant, lookup, kind, older_first
    ):
        delivery_note, invoices = _invoices_on_note(kind, older_first, NEWER, OLDER)

        assert lookup(delivery_note) == invoices["current"].id

    @LOOKUPS
    @CREATION_ORDERS
    def test_one_rule_across_article_and_crate_lines(self, tenant, lookup, older_first):
        """A current invoice reached only through a crate line beats a
        cancelled one reached through an article line."""
        _, delivery_note_line, crate_delivery_note_line = _order_with_delivery_note()
        cancelled = InvoiceResellerFactory(
            reseller=delivery_note_line.delivery_note.order.reseller, date=NEWER
        )
        current = InvoiceResellerFactory(reseller=cancelled.reseller, date=OLDER)
        links = [
            lambda: _article_line(cancelled, delivery_note_line),
            lambda: _crate_line(current, crate_delivery_note_line),
        ]
        for link in links if older_first else reversed(links):
            link()
        _cancel(cancelled)

        assert lookup(delivery_note_line.delivery_note) == current.id

    @LOOKUPS
    def test_a_note_without_an_invoice_resolves_none(self, tenant, lookup):
        _, delivery_note_line, _ = _order_with_delivery_note()

        assert lookup(delivery_note_line.delivery_note) is None

    def test_no_delivery_note_resolves_none(self, tenant):
        assert InvoiceService.get_invoice_for_delivery_note(None) is None

    def test_batch_of_no_ids_is_empty(self, tenant):
        assert InvoiceService.get_invoices_for_delivery_notes([]) == {}

    def test_batch_maps_each_note_and_leaves_out_unbilled_ones(self, tenant):
        _, article_note_line, _ = _order_with_delivery_note()
        _, _, crate_note_line = _order_with_delivery_note()
        _, unbilled_note_line, _ = _order_with_delivery_note()
        article_invoice = InvoiceResellerFactory(date=OLDER)
        _article_line(article_invoice, article_note_line)
        crate_invoice = InvoiceResellerFactory(date=OLDER)
        _crate_line(crate_invoice, crate_note_line)

        resolved = InvoiceService.get_invoices_for_delivery_notes(
            [
                article_note_line.delivery_note_id,
                crate_note_line.delivery_note_id,
                unbilled_note_line.delivery_note_id,
            ]
        )

        assert {key: invoice.id for key, invoice in resolved.items()} == {
            article_note_line.delivery_note_id: article_invoice.id,
            crate_note_line.delivery_note_id: crate_invoice.id,
        }


class TestBatchQueryCount:
    def _count_queries(self, note_count: int) -> int:
        delivery_note_ids = []
        for _ in range(note_count):
            _, delivery_note_line, crate_delivery_note_line = (
                _order_with_delivery_note()
            )
            for date in (OLDER, NEWER):
                invoice = InvoiceResellerFactory(date=date)
                _article_line(invoice, delivery_note_line)
                _crate_line(invoice, crate_delivery_note_line)
            delivery_note_ids.append(delivery_note_line.delivery_note_id)
        with CaptureQueriesContext(connection) as queries:
            resolved = InvoiceService.get_invoices_for_delivery_notes(delivery_note_ids)
            for invoice in resolved.values():
                # The cancelling storno is loaded with the invoice.
                _ = invoice.cancelled_by_invoice
        assert len(resolved) == note_count
        # django-tenants resets the search path before each query; count the
        # reads only.
        return sum(
            query["sql"].startswith("SELECT") for query in queries.captured_queries
        )

    def test_query_count_does_not_grow_with_the_notes(self, tenant):
        assert self._count_queries(1) == self._count_queries(5) == 2
