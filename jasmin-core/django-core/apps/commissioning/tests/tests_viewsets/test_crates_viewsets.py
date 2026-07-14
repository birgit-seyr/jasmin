"""Tests for crates_viewsets.py — CrateDeliveryNoteContent, CrateContentInvoice, CrateNetPrice.

These viewsets each override ``list`` / ``create`` / ``update`` / ``destroy``
with custom logic (aggregation, finalize-rejection, parent-id resolution).
Existing coverage was 38% — the list/create error paths and CrateNetPrice
CRUD are the easiest wins.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import CrateNetPrice
from apps.commissioning.tests.factories import (
    CrateFactory,
    CrateNetPriceFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderFactory,
    ResellerFactory,
    ShareTypeVariationFactory,
)

# ---------------------------------------------------------------------------
# CrateDeliveryNoteContentViewSet — list / create
# ---------------------------------------------------------------------------
URL_CRATE_DN_CONTENT = reverse("crate_delivery_note_content-list")


@pytest.mark.django_db
class TestCrateDeliveryNoteContentViewSet:
    def test_list_unknown_delivery_note_returns_404(self, api_client, tenant):
        resp = api_client.get(
            URL_CRATE_DN_CONTENT,
            {"delivery_note_id": "nonexistent-id"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_returns_empty_summary_for_dn_with_no_crates(self, api_client, tenant):
        order = OrderFactory(reseller=ResellerFactory())
        dn = DeliveryNoteResellerFactory(order=order)
        resp = api_client.get(URL_CRATE_DN_CONTENT, {"delivery_note_id": str(dn.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_create_missing_delivery_note_returns_404(self, api_client, tenant):
        crate = CrateFactory()
        resp = api_client.post(
            URL_CRATE_DN_CONTENT,
            {
                "delivery_note_id": "nonexistent",
                "crate_type": str(crate.id),
                "amount": 2,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_create_rejects_finalized_delivery_note(self, api_client, tenant):
        """Finalized DN → ``FinalizedError`` → 409 Conflict (state conflict,
        not bad input)."""
        order = OrderFactory(reseller=ResellerFactory())
        dn = DeliveryNoteResellerFactory(order=order, is_finalized=True)
        crate = CrateFactory()
        resp = api_client.post(
            URL_CRATE_DN_CONTENT,
            {
                "delivery_note_id": str(dn.id),
                "crate_type": str(crate.id),
                "amount": 2,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_create_valid_crate_persists_resolved_tax_rate(self, api_client, tenant):
        # Regression: tax_rate is NOT NULL on CrateDeliveryNoteContent but
        # create() never set it, so adding a crate to a delivery note 500'd on
        # an IntegrityError. It must now succeed and persist the resolved
        # (crate-default) tax rate.
        from apps.commissioning.models import CrateDeliveryNoteContent

        order = OrderFactory(reseller=ResellerFactory())
        dn = DeliveryNoteResellerFactory(order=order)
        crate = CrateFactory()
        resp = api_client.post(
            URL_CRATE_DN_CONTENT,
            {
                "delivery_note_id": str(dn.id),
                "crate_type": str(crate.id),
                "amount": 3,
                "price_per_unit": "2.50",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        row = CrateDeliveryNoteContent.objects.get(delivery_note=dn, crate_type=crate)
        assert row.tax_rate is not None

    def test_summary_groups_mixed_price_rows_not_max(self, api_client, tenant):
        # Regression (BL-7): the summary aggregated price/rabatt/tax with Max()
        # over the summed amount, collapsing mixed-price rows of one crate type
        # into a single wrong row. They must now group by (price, rabatt, tax)
        # with line_netto = sum of per-row nets, matching the document footer.
        from apps.commissioning.models import CrateDeliveryNoteContent

        order = OrderFactory(reseller=ResellerFactory())
        dn = DeliveryNoteResellerFactory(order=order)
        crate = CrateFactory()
        CrateDeliveryNoteContent.objects.create(
            delivery_note=dn,
            crate_type=crate,
            amount=5,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
        )
        CrateDeliveryNoteContent.objects.create(
            delivery_note=dn,
            crate_type=crate,
            amount=4,
            price_per_unit=Decimal("3.00"),
            tax_rate=Decimal("19.00"),
        )

        resp = api_client.get(URL_CRATE_DN_CONTENT, {"delivery_note_id": str(dn.id)})
        assert resp.status_code == status.HTTP_200_OK
        # Two distinct price groups, not one max-collapsed row.
        assert sorted(row["price_per_unit"] for row in resp.data) == ["2.50", "3.00"]
        # Nets sum to the true 24.50 (5*2.50 + 4*3.00), never max-inflated 27.00.
        total = sum(Decimal(row["line_netto"]) for row in resp.data)
        assert total == Decimal("24.50")


# ---------------------------------------------------------------------------
# CrateContentInvoiceResellerViewSet — list / create error paths
# ---------------------------------------------------------------------------
URL_CRATE_INV_CONTENT = reverse("crate_invoice_content-list")


@pytest.mark.django_db
class TestCrateContentInvoiceResellerViewSet:
    def test_list_unknown_invoice_returns_404(self, api_client, tenant):
        resp = api_client.get(URL_CRATE_INV_CONTENT, {"invoice_id": "bogus"})
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_returns_empty_summary_for_invoice_with_no_crates(
        self, api_client, tenant
    ):
        invoice = InvoiceResellerFactory()
        resp = api_client.get(URL_CRATE_INV_CONTENT, {"invoice_id": str(invoice.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_create_rejects_finalized_invoice(self, api_client, tenant):
        """Same as above — ``FinalizedError`` → 409 Conflict."""
        invoice = InvoiceResellerFactory(is_finalized=True)
        crate = CrateFactory()
        resp = api_client.post(
            URL_CRATE_INV_CONTENT,
            {
                "invoice_id": str(invoice.id),
                "crate_type": str(crate.id),
                "amount": 1,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT


# ---------------------------------------------------------------------------
# CrateNetPriceViewSet — CRUD + filtering
# ---------------------------------------------------------------------------
URL_CRATE_NET_PRICE = reverse("crate_net_prices-list")


@pytest.mark.django_db
class TestCrateNetPriceViewSet:
    def test_list_empty(self, api_client, tenant):
        CrateNetPrice.objects.all().delete()
        resp = api_client.get(URL_CRATE_NET_PRICE)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_prices_with_crate_name(self, api_client, tenant):
        """Serializer exposes the crate's name via ``source="crate.name"``
        as the ``name`` field — that's what the modal's name column reads."""
        crate = CrateFactory(name="EuroBox")
        CrateNetPriceFactory(crate=crate, price=Decimal("5.00"))
        resp = api_client.get(URL_CRATE_NET_PRICE)
        assert resp.status_code == status.HTTP_200_OK
        names = [row.get("name") for row in resp.data]
        assert "EuroBox" in names

    def test_active_price_not_deletable_when_crate_in_use(self, api_client, tenant):
        # Nothing FK-references the price row, but an ACTIVE CrateNetPrice must
        # become non-deletable once its Crate is in use (here: a variation's
        # packing crate). The frontend hides the delete icon on can_be_deleted.
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate)  # active
        params = {"crate": str(crate.id)}

        resp = api_client.get(URL_CRATE_NET_PRICE, params)
        assert resp.data[0]["can_be_deleted"] is True

        ShareTypeVariationFactory(used_crate=crate)
        resp = api_client.get(URL_CRATE_NET_PRICE, params)
        assert resp.data[0]["can_be_deleted"] is False

    @time_machine.travel(datetime.date(2026, 6, 1), tick=False)
    def test_future_price_deletable_even_when_crate_in_use(self, api_client, tenant):
        # Future (and past) prices stay deletable regardless of crate usage.
        crate = CrateFactory()
        ShareTypeVariationFactory(used_crate=crate)  # crate in use
        future = CrateNetPriceFactory(
            crate=crate,
            valid_from=datetime.date(2027, 1, 4),  # Monday, future
            valid_until=None,
        )
        resp = api_client.get(URL_CRATE_NET_PRICE, {"crate": str(crate.id)})
        row = next(r for r in resp.data if r["id"] == str(future.id))
        assert row["can_be_deleted"] is True

    def test_filter_by_crate(self, api_client, tenant):
        c1 = CrateFactory()
        c2 = CrateFactory()
        CrateNetPriceFactory(crate=c1)
        CrateNetPriceFactory(crate=c2)
        resp = api_client.get(URL_CRATE_NET_PRICE, {"crate": str(c1.id)})
        assert resp.status_code == status.HTTP_200_OK
        # All returned rows must be for c1 only.
        assert all(row.get("crate") == str(c1.id) for row in resp.data)

    def test_filter_current_returns_only_open_ended_rows(self, api_client, tenant):
        """``?current=true`` filters to rows with ``valid_until IS NULL`` —
        the current-price-per-crate view in the modal relies on this.

        ``valid_from`` MUST be a Monday (per CLAUDE.md / TimeBoundMixin
        ``clean()``), so the dates below are picked to satisfy that.
        """
        crate = CrateFactory()
        CrateNetPriceFactory(
            crate=crate,
            valid_from=datetime.date(2026, 1, 5),  # Mon
            valid_until=datetime.date(2026, 6, 28),
            price=Decimal("4.00"),
        )
        CrateNetPriceFactory(
            crate=crate,
            valid_from=datetime.date(2026, 7, 6),  # Mon
            valid_until=None,
            price=Decimal("5.00"),
        )
        resp = api_client.get(
            URL_CRATE_NET_PRICE, {"crate": str(crate.id), "current": "true"}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["valid_until"] is None
