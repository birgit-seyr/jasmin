"""Perf-lock + required-param tests for the reseller *content* list endpoints.

Covers PERF-7: ``InvoiceResellerContentViewSet`` and
``DeliveryNoteResellerContentViewSet`` must

1. be **scale-invariant** in the number of content rows for a given document
   (the serializer's ``ShareArticleResolutionMixin`` reads
   ``obj.share_article`` and ``obj.offer.share_article`` per row — without a
   ``select_related`` that is ~2N queries), and
2. **require** the document-id filter (``invoice_id`` / ``delivery_note_id``)
   — a bare GET must 400, not dump every content row in the tenant.

These don't measure wall-clock time: they run the same endpoint with N=small
and N=larger rows on the SAME document and assert the query count barely
moves. A regression here means someone dropped the ``select_related`` on the
content queryset.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.models import (
    DeliveryNoteContent,
    InvoiceResellerContent,
)
from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OfferFactory,
    OrderFactory,
    ResellerFactory,
)

pytestmark = pytest.mark.django_db

# Generous absolute ceiling that still catches obvious regressions.
HARD_CEILING = 40


def _count_queries_on(client: APIClient, url: str, params: dict) -> int:
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url, params)
    assert resp.status_code == status.HTTP_200_OK, (
        f"{url} returned {resp.status_code}; perf-lock test cannot validate "
        f"a failing endpoint. Body: {resp.content[:200]!r}"
    )
    return len(ctx.captured_queries)


def _add_invoice_lines(invoice, count: int) -> None:
    """Add ``count`` content rows whose article resolves through ``offer``
    (the heavier of the two N+1 paths — ``offer__share_article``)."""
    for _ in range(count):
        InvoiceResellerContent.objects.create(
            invoice=invoice,
            offer=OfferFactory(),
            amount=Decimal("10.000"),
            price_per_unit=Decimal("1.50"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )


def _add_delivery_note_lines(delivery_note, count: int) -> None:
    for _ in range(count):
        DeliveryNoteContent.objects.create(
            delivery_note=delivery_note,
            offer=OfferFactory(),
            amount=Decimal("10.000"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )


# --------------------------------------------------------------------------- #
# InvoiceResellerContentViewSet                                               #
# --------------------------------------------------------------------------- #
class TestInvoiceResellerContentQueryCount:
    URL = reverse("invoice_contents-list")

    def test_list_is_scale_invariant(self, api_client, tenant):
        invoice = InvoiceResellerFactory(reseller=ResellerFactory())

        _add_invoice_lines(invoice, 2)
        small = _count_queries_on(api_client, self.URL, {"invoice_id": invoice.pk})

        _add_invoice_lines(invoice, 6)
        large = _count_queries_on(api_client, self.URL, {"invoice_id": invoice.pk})

        assert large - small <= 2, (
            f"invoice_contents/ N+1 suspected: 2 rows -> {small} queries, "
            f"8 rows -> {large} queries (delta {large - small})."
        )
        assert (
            large <= HARD_CEILING
        ), f"invoice_contents/ exceeded hard ceiling: {large}"

    def test_missing_invoice_id_is_rejected(self, api_client, tenant):
        # Seed content the bare GET must NOT return.
        invoice = InvoiceResellerFactory(reseller=ResellerFactory())
        _add_invoice_lines(invoice, 3)

        resp = api_client.get(self.URL)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content


# --------------------------------------------------------------------------- #
# DeliveryNoteResellerContentViewSet                                          #
# --------------------------------------------------------------------------- #
class TestDeliveryNoteResellerContentQueryCount:
    URL = reverse("delivery_note_contents-list")

    def test_list_is_scale_invariant(self, api_client, tenant):
        order = OrderFactory(reseller=ResellerFactory())
        delivery_note = DeliveryNoteResellerFactory(order=order)

        _add_delivery_note_lines(delivery_note, 2)
        small = _count_queries_on(
            api_client, self.URL, {"delivery_note_id": delivery_note.pk}
        )

        _add_delivery_note_lines(delivery_note, 6)
        large = _count_queries_on(
            api_client, self.URL, {"delivery_note_id": delivery_note.pk}
        )

        assert large - small <= 2, (
            f"delivery_note_contents/ N+1 suspected: 2 rows -> {small} queries, "
            f"8 rows -> {large} queries (delta {large - small})."
        )
        assert (
            large <= HARD_CEILING
        ), f"delivery_note_contents/ exceeded hard ceiling: {large}"

    def test_missing_delivery_note_id_is_rejected(self, api_client, tenant):
        order = OrderFactory(reseller=ResellerFactory())
        delivery_note = DeliveryNoteResellerFactory(order=order)
        _add_delivery_note_lines(delivery_note, 3)

        resp = api_client.get(self.URL)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
