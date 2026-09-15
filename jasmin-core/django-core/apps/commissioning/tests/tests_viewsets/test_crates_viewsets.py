"""Tests for crates_viewsets.py — CrateDeliveryNoteContent, CrateContentInvoice, CrateNetPrice.

These viewsets each override ``list`` / ``create`` / ``update`` / ``destroy``
with custom logic (aggregation, finalize-rejection, parent-id resolution).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateNetPrice,
)
from apps.commissioning.serializers import (
    CrateContentInvoiceResellerSerializer,
    CrateDeliveryNoteContentSerializer,
)
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
        # tax_rate is NOT NULL on CrateDeliveryNoteContent, so create() must
        # persist the resolved (crate-default) tax rate.
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
        # Mixed-price rows of one crate type must not collapse into a single row
        # (as a Max() over price/rabatt/tax would): the summary groups by
        # (price, rabatt, tax) with line_netto = sum of per-row nets, matching
        # the document footer.
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


# ---------------------------------------------------------------------------
# Crate lines on delivery notes and invoices — request validation
# ---------------------------------------------------------------------------


@pytest.fixture(params=["delivery_note", "invoice"])
def crate_document(request, tenant):
    """A draft delivery note or invoice plus a crate type, with what a test needs
    to write crate lines onto it through that document's crate endpoint."""
    crate = CrateFactory()
    if request.param == "delivery_note":
        return SimpleNamespace(
            url=URL_CRATE_DN_CONTENT,
            detail_url=reverse("crate_delivery_note_content-detail", args=[crate.id]),
            parent_key="delivery_note_id",
            parent_field="delivery_note",
            model=CrateDeliveryNoteContent,
            parent=DeliveryNoteResellerFactory(
                order=OrderFactory(reseller=ResellerFactory())
            ),
            crate=crate,
        )
    return SimpleNamespace(
        url=URL_CRATE_INV_CONTENT,
        detail_url=reverse("crate_invoice_content-detail", args=[crate.id]),
        parent_key="invoice_id",
        parent_field="invoice",
        model=CrateContentInvoiceReseller,
        parent=InvoiceResellerFactory(),
        crate=crate,
    )


def _crate_body(document, **fields):
    return {
        document.parent_key: str(document.parent.id),
        "crate_type": str(document.crate.id),
        **fields,
    }


def _stored_crate_line(document, **fields):
    return document.model.objects.create(
        **{document.parent_field: document.parent},
        crate_type=document.crate,
        **fields,
    )


def _crate_lines(document):
    return document.model.objects.filter(
        **{document.parent_field: document.parent}, crate_type=document.crate
    )


@pytest.mark.django_db
class TestCrateDocumentLineWriteValidation:
    def test_create_rejects_rabatt_over_100(self, api_client, crate_document):
        # A 150 % discount would give the line a negative net.
        resp = api_client.post(
            crate_document.url,
            _crate_body(crate_document, amount=2, price_per_unit="2.50", rabatt=150),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "rabatt"
        assert not _crate_lines(crate_document).exists()

    def test_create_rejects_blank_rabatt(self, api_client, crate_document):
        resp = api_client.post(
            crate_document.url,
            _crate_body(crate_document, amount=2, rabatt=""),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "rabatt"
        assert not _crate_lines(crate_document).exists()

    def test_create_rejects_note_longer_than_the_column(
        self, api_client, crate_document
    ):
        resp = api_client.post(
            crate_document.url,
            _crate_body(crate_document, amount=2, note="x" * 501),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "note"
        assert not _crate_lines(crate_document).exists()

    def test_create_valid_line_succeeds(self, api_client, crate_document):
        resp = api_client.post(
            crate_document.url,
            _crate_body(
                crate_document,
                amount=3,
                price_per_unit="2.50",
                rabatt=10,
                tax_rate="19.00",
                note="Deposit",
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        line = _crate_lines(crate_document).get()
        assert line.amount == 3
        assert line.price_per_unit == Decimal("2.50")
        assert line.rabatt == 10
        assert line.tax_rate == Decimal("19.00")
        assert line.note == "Deposit"

    def test_update_rejects_rabatt_over_100(self, api_client, crate_document):
        line = _stored_crate_line(
            crate_document,
            amount=3,
            price_per_unit=Decimal("2.50"),
            rabatt=10,
            tax_rate=Decimal("19.00"),
        )
        resp = api_client.patch(
            crate_document.detail_url,
            _crate_body(crate_document, amount=3, rabatt=150),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["field"] == "rabatt"
        line.refresh_from_db()
        assert line.rabatt == 10

    def test_update_blank_amount_is_amount_invalid(self, api_client, crate_document):
        # A blank amount is a 400, not an ``int("")`` error escaping update as a 500.
        _stored_crate_line(crate_document, amount=3, tax_rate=Decimal("19.00"))
        resp = api_client.patch(
            crate_document.detail_url,
            _crate_body(crate_document, amount=""),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "amount.invalid"
        assert resp.data["field"] == "amount"

    def test_patch_without_price_or_rabatt_keeps_stored_values(
        self, api_client, crate_document
    ):
        _stored_crate_line(
            crate_document,
            amount=3,
            price_per_unit=Decimal("2.50"),
            rabatt=10,
            tax_rate=Decimal("7.00"),
        )
        resp = api_client.patch(
            crate_document.detail_url,
            _crate_body(crate_document, amount=5),
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        lines = list(_crate_lines(crate_document))
        assert sum(line.amount for line in lines) == 5
        assert {
            (line.price_per_unit, line.rabatt, line.tax_rate) for line in lines
        } == {(Decimal("2.50"), 10, Decimal("7.00"))}

    def test_update_valid_frontend_row_succeeds(self, api_client, crate_document):
        # The crate tables PATCH the whole edited summary row: amount and rabatt
        # as form-input strings, the summary row's float tax_rate, and row keys
        # the endpoint ignores.
        _stored_crate_line(
            crate_document,
            amount=3,
            price_per_unit=Decimal("2.50"),
            rabatt=0,
            tax_rate=Decimal("19.00"),
        )
        resp = api_client.patch(
            crate_document.detail_url,
            _crate_body(
                crate_document,
                id=str(crate_document.crate.id),
                key=0,
                amount="4",
                price_per_unit="3.00",
                rabatt="5",
                tax_rate=19.0,
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["amount"] == 4
        lines = list(_crate_lines(crate_document))
        assert sum(line.amount for line in lines) == 4
        assert {
            (line.price_per_unit, line.rabatt, line.tax_rate) for line in lines
        } == {(Decimal("3.00"), 5, Decimal("19.00"))}


@pytest.mark.django_db
class TestCrateDocumentLineSerializerLocks:
    """A PATCH through the crate-line model serializers must not rewrite the GoBD
    source snapshot, re-point the line onto another document, or set the invoice
    line's delivery-note provenance."""

    def test_delivery_note_crate_line_locks_hold_on_patch(self, tenant):
        delivery_note = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=ResellerFactory())
        )
        other_delivery_note = DeliveryNoteResellerFactory(
            order=OrderFactory(reseller=ResellerFactory())
        )
        line = CrateDeliveryNoteContent.objects.create(
            delivery_note=delivery_note,
            crate_type=CrateFactory(),
            amount=3,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
            source_amount=Decimal("3"),
            source_price_per_unit=Decimal("2.50"),
            source_rabatt=0,
        )
        serializer = CrateDeliveryNoteContentSerializer(
            line,
            data={
                "delivery_note": str(other_delivery_note.id),
                "source_amount": "9",
                "source_price_per_unit": "9.99",
                "source_rabatt": 50,
                "note": "edited",
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        line.refresh_from_db()
        assert line.delivery_note_id == delivery_note.id
        assert line.source_amount == Decimal("3")
        assert line.source_price_per_unit == Decimal("2.50")
        assert line.source_rabatt == 0
        assert line.note == "edited"
        # A new line still names its delivery note.
        assert (
            CrateDeliveryNoteContentSerializer().fields["delivery_note"].read_only
            is False
        )

    def test_invoice_crate_line_locks_hold_on_patch(self, tenant):
        invoice = InvoiceResellerFactory()
        other_invoice = InvoiceResellerFactory()
        crate = CrateFactory()
        delivery_note_line = CrateDeliveryNoteContent.objects.create(
            delivery_note=DeliveryNoteResellerFactory(
                order=OrderFactory(reseller=ResellerFactory())
            ),
            crate_type=crate,
            amount=3,
            tax_rate=Decimal("19.00"),
        )
        line = CrateContentInvoiceReseller.objects.create(
            invoice=invoice,
            crate_type=crate,
            amount=3,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
            source_amount=Decimal("3"),
            source_rabatt=0,
        )
        serializer = CrateContentInvoiceResellerSerializer(
            line,
            data={
                "invoice": str(other_invoice.id),
                "source_amount": "9",
                "source_rabatt": 50,
                "crate_delivery_note_contents": [str(delivery_note_line.id)],
                "note": "edited",
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        line.refresh_from_db()
        assert line.invoice_id == invoice.id
        assert line.source_amount == Decimal("3")
        assert line.source_rabatt == 0
        assert not line.crate_delivery_note_contents.exists()
        assert line.note == "edited"
        # A new line still names its invoice.
        assert (
            CrateContentInvoiceResellerSerializer().fields["invoice"].read_only is False
        )


# ---------------------------------------------------------------------------
# CrateNetPriceViewSet — DELETE enforces can_be_deleted
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCrateNetPriceDestroyGuard:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        # "Active" is judged against today: pin it inside the factory's default
        # validity (from 2026-01-05) so the default price stays active.
        with time_machine.travel(datetime.datetime(2026, 6, 1, 12, 0), tick=False):
            yield

    @staticmethod
    def _url(price) -> str:
        return reverse("crate_net_prices-detail", args=[price.id])

    def test_active_price_of_crate_in_use_is_409_and_kept(self, api_client, tenant):
        crate = CrateFactory()
        price = CrateNetPriceFactory(crate=crate)
        ShareTypeVariationFactory(used_crate=crate)  # crate now in use (packing)

        resp = api_client.delete(self._url(price))

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "crate.net_price_in_use"
        assert CrateNetPrice.objects.filter(pk=price.pk).exists()

    def test_active_price_of_unused_crate_is_deleted(self, api_client, tenant):
        price = CrateNetPriceFactory(crate=CrateFactory())

        resp = api_client.delete(self._url(price))

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not CrateNetPrice.objects.filter(pk=price.pk).exists()
