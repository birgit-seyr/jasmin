"""Tests for resellers_viewsets.py — Reseller, Offer, OfferGroup, OrderContent,
Invoice, DeliveryNote, CommissioningList viewsets."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    InvoiceResellerContent,
    Order,
    OrganicCertificate,
)
from apps.commissioning.tests.factories import (
    CrateFactory,
    CrateNetPriceFactory,
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OfferFactory,
    OfferGroupFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)


# ---------------------------------------------------------------------------
# ResellerViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestResellerViewSet:
    URL = reverse("reseller-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_resellers(self, api_client, tenant):
        ResellerFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_is_reseller(self, api_client, tenant):
        ResellerFactory(is_reseller=True)
        ResellerFactory(is_reseller=False)
        resp = api_client.get(self.URL, {"is_reseller": "true"})
        for item in resp.data:
            assert item["is_reseller"] is True

    def test_filter_is_active_reseller(self, api_client, tenant):
        ResellerFactory(is_active_reseller=True)
        ResellerFactory(is_active_reseller=False)
        resp = api_client.get(self.URL, {"is_active_reseller": "true"})
        for item in resp.data:
            assert item["is_active_reseller"] is True

    def test_retrieve(self, api_client, tenant):
        r = ResellerFactory()
        url = reverse("reseller-detail", kwargs={"pk": r.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK

    def test_iban_never_returned_in_plaintext(self, api_client, tenant):
        # ContactEntity.iban is encrypted at rest; the reseller read
        # must NOT echo the decrypted value — only a masked view + a stored flag.
        from apps.commissioning.tests.factories import ContactEntityFactory

        iban = "DE89370400440532013000"
        reseller = ResellerFactory(contact=ContactEntityFactory(iban=iban))
        url = reverse("reseller-detail", kwargs={"pk": reseller.pk})

        resp = api_client.get(url)

        assert resp.status_code == status.HTTP_200_OK
        # Plaintext IBAN must not appear under any key.
        assert iban not in str(resp.data)
        assert resp.data.get("iban") in (None, "")
        assert resp.data["iban_stored"] is True
        assert resp.data["iban_masked"] and resp.data["iban_masked"] != iban

    def test_delete(self, api_client, tenant):
        r = ResellerFactory()
        url = reverse("reseller-detail", kwargs={"pk": r.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
class TestResellerHasOrdersWithoutInvoiceFilter:
    """The invoices page's reseller dropdown asks for the resellers that still
    have something to invoice."""

    URL = reverse("reseller-list")

    @staticmethod
    def _ids(resp) -> set[str]:
        rows = resp.json()
        if isinstance(rows, dict):
            rows = rows.get("results", [])
        return {row["id"] for row in rows}

    @staticmethod
    def _invoiced_order(reseller) -> Order:
        """An order carried all the way to an invoice: the invoice line keeps
        the provenance link back to the delivery-note line, which is how the
        backend recognises an order as invoiced."""
        order = OrderFactory(reseller=reseller)
        delivery_note_line = DeliveryNoteContentFactory(
            delivery_note=DeliveryNoteResellerFactory(order=order)
        )
        invoice_line = InvoiceResellerContent.objects.create(
            invoice=InvoiceResellerFactory(reseller=reseller),
            share_article=delivery_note_line.share_article,
            amount=delivery_note_line.amount,
            unit=delivery_note_line.unit,
            size=delivery_note_line.size,
            tax_rate=delivery_note_line.tax_rate,
        )
        invoice_line.delivery_note_contents.add(delivery_note_line)
        return order

    @staticmethod
    def _crate_delivery_note_line(order) -> CrateDeliveryNoteContent:
        """A crate-ONLY delivery note for ``order``: no article lines at all,
        so only the crate half of the predicate can see it."""
        return CrateDeliveryNoteContent.objects.create(
            delivery_note=DeliveryNoteResellerFactory(order=order),
            crate_type=CrateFactory(),
            amount=3,
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("19.00"),
        )

    @classmethod
    def _crate_invoiced_order(cls, reseller) -> Order:
        """A crate-only delivery note carried to an invoice, linked through
        ``CrateContentInvoiceReseller.crate_delivery_note_contents``."""
        order = OrderFactory(reseller=reseller)
        crate_delivery_note_line = cls._crate_delivery_note_line(order)
        crate_invoice_line = CrateContentInvoiceReseller.objects.create(
            invoice=InvoiceResellerFactory(reseller=reseller),
            crate_type=crate_delivery_note_line.crate_type,
            amount=crate_delivery_note_line.amount,
            price_per_unit=crate_delivery_note_line.price_per_unit,
            tax_rate=crate_delivery_note_line.tax_rate,
        )
        crate_invoice_line.crate_delivery_note_contents.add(crate_delivery_note_line)
        return order

    def test_true_keeps_only_resellers_with_an_uninvoiced_order(
        self, api_client, tenant
    ):
        waiting = ResellerFactory()
        OrderFactory(reseller=waiting)
        settled = ResellerFactory()
        self._invoiced_order(settled)
        without_orders = ResellerFactory()

        resp = api_client.get(self.URL, {"has_orders_without_invoice": "true"})

        assert resp.status_code == status.HTTP_200_OK
        ids = self._ids(resp)
        assert waiting.id in ids
        assert settled.id not in ids
        assert without_orders.id not in ids

    def test_an_order_whose_delivery_note_is_not_invoiced_still_counts(
        self, api_client, tenant
    ):
        """A delivery note is not an invoice — the present-delivery-note branch
        must not be mistaken for "already invoiced"."""
        waiting = ResellerFactory()
        DeliveryNoteResellerFactory(order=OrderFactory(reseller=waiting))

        resp = api_client.get(self.URL, {"has_orders_without_invoice": "true"})

        assert waiting.id in self._ids(resp)

    def test_false_keeps_only_resellers_with_nothing_left_to_invoice(
        self, api_client, tenant
    ):
        waiting = ResellerFactory()
        OrderFactory(reseller=waiting)
        settled = ResellerFactory()
        self._invoiced_order(settled)
        without_orders = ResellerFactory()

        resp = api_client.get(self.URL, {"has_orders_without_invoice": "false"})

        assert resp.status_code == status.HTTP_200_OK
        ids = self._ids(resp)
        assert settled.id in ids
        assert without_orders.id in ids
        assert waiting.id not in ids

    def test_absent_filter_returns_every_reseller(self, api_client, tenant):
        waiting = ResellerFactory()
        OrderFactory(reseller=waiting)
        settled = ResellerFactory()
        self._invoiced_order(settled)

        resp = api_client.get(self.URL)

        assert resp.status_code == status.HTTP_200_OK
        ids = self._ids(resp)
        assert {waiting.id, settled.id} <= ids

    def test_a_crate_only_invoice_settles_its_order(self, api_client, tenant):
        """A crate-only delivery note has no article lines, so the article
        provenance path can't see its invoice — the crate path is the only
        thing keeping the reseller out of the "still to invoice" list."""
        settled = ResellerFactory()
        self._crate_invoiced_order(settled)

        resp = api_client.get(self.URL, {"has_orders_without_invoice": "true"})

        assert resp.status_code == status.HTTP_200_OK
        assert settled.id not in self._ids(resp)

    def test_an_uninvoiced_crate_only_delivery_note_still_counts(
        self, api_client, tenant
    ):
        waiting = ResellerFactory()
        self._crate_delivery_note_line(OrderFactory(reseller=waiting))

        resp = api_client.get(self.URL, {"has_orders_without_invoice": "true"})

        assert waiting.id in self._ids(resp)

    def test_the_verdict_is_scoped_to_the_requested_year(self, api_client, tenant):
        """The page driving this filter shows one year of orders, so a
        reseller whose only open order is from another year has nothing to
        invoice there."""
        earlier_year_only = ResellerFactory()
        OrderFactory(reseller=earlier_year_only, year=2025)

        scoped = api_client.get(
            self.URL, {"has_orders_without_invoice": "true", "year": 2026}
        )
        unscoped = api_client.get(self.URL, {"has_orders_without_invoice": "true"})

        assert earlier_year_only.id not in self._ids(scoped)
        assert earlier_year_only.id in self._ids(unscoped)

    def test_non_boolean_value_returns_400(self, api_client, tenant):
        resp = api_client.get(self.URL, {"has_orders_without_invoice": "ture"})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# OfferGroupViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOfferGroupViewSet:
    URL = reverse("offer_group-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns(self, api_client, tenant):
        OfferGroupFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# OfferViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOfferViewSet:
    URL = reverse("offer-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns(self, api_client, tenant):
        OfferFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_by_year_and_week(self, api_client, tenant):
        OfferFactory(year=2026, delivery_week=10)
        OfferFactory(year=2026, delivery_week=20)
        resp = api_client.get(self.URL, {"year": 2026, "delivery_week": 10})
        for item in resp.data:
            assert item["delivery_week"] == 10


# ---------------------------------------------------------------------------
# OrderContentViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOrderContentViewSet:
    URL = reverse("order_contents-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_create_without_tax_rate_derives_it_from_offer(self, api_client, tenant):
        """The customer order page omits tax_rate (derivable from the
        offer/article pricing), so create must NOT require it — the service
        resolves it via the canonical chain."""
        from apps.commissioning.models import OrderContent

        reseller = ResellerFactory()
        offer = OfferFactory()
        resp = api_client.post(
            self.URL,
            {
                "offer": str(offer.id),
                "reseller": str(reseller.id),
                "year": 2026,
                "delivery_week": 15,
                "day_number": 0,
                "amount": "8.000",
                "price_per_unit": "4.5",
                "unit": "KG",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        order_content = OrderContent.objects.get(offer=offer)
        assert order_content.tax_rate is not None

    # The Orders page (``useOrdersData`` + ``useOrderColumns`` custom saves)
    # sends the whole edited row: EditableTable seeds the form with every key
    # of the record, then the save adds the order-level keys.
    ORDER_DAYS = {
        "harvesting_day": 1,
        "packing_day": 2,
        "washing_day": 1,
        "cleaning_day": 1,
    }

    def _detail_url(self, order_content):
        return reverse("order_contents-detail", kwargs={"pk": order_content.pk})

    def test_orders_page_offer_row_create_and_patch(self, api_client, tenant):
        from apps.commissioning.models import OrderContent

        reseller = ResellerFactory()
        offer = OfferFactory(amount=Decimal("100.000"), amount_per_pu=Decimal("2.000"))
        create_body = {
            "washing": False,
            "cleaning": False,
            "comes_from_long_term_storage": False,
            "offer": offer.id,
            "offer_available_amount": "100.000",
            "ordered_amount": 4,
            "amount": 8.0,
            "price_per_unit": 2.5,
            "rabatt": None,
            "tax_rate": None,
            "note": "",
            "unit": "KG",
            "size": "M",
            "sort": None,
            "is_placeholder": True,
            "year": 2026,
            "delivery_week": 15,
            "day_number": 2,
            "reseller": reseller.id,
            **self.ORDER_DAYS,
        }

        created = api_client.post(self.URL, create_body, format="json")

        assert created.status_code == status.HTTP_200_OK, created.data
        line = OrderContent.objects.get(offer=offer)
        assert line.amount == Decimal("8.000")
        offer.refresh_from_db()
        assert offer.amount == Decimal("96.000")

        patch_body = {
            **create_body,
            "id": line.id,
            "is_placeholder": False,
            "share_article": None,
            "is_finalized": False,
            "finalized_at": None,
            "finalized_by": None,
            "ordered_amount": 5,
            "amount": 10.0,
            "price_per_unit": 2.4,
            "rabatt": 10,
            "tax_rate": "7.00",
            "note": "wash please",
        }
        patched = api_client.patch(self._detail_url(line), patch_body, format="json")

        assert patched.status_code == status.HTTP_200_OK, patched.data
        line.refresh_from_db()
        assert line.offer_id == offer.id
        assert line.amount == Decimal("10.000")
        assert line.price_per_unit == Decimal("2.40")
        assert line.rabatt == 10
        assert line.tax_rate == Decimal("7.00")
        assert line.note == "wash please"
        offer.refresh_from_db()
        assert offer.amount == Decimal("95.000")

    def test_orders_page_article_row_create_and_patch(self, api_client, tenant):
        from apps.commissioning.models import OrderContent

        reseller = ResellerFactory()
        article = ShareArticleFactory()
        create_body = {
            "washing": False,
            "cleaning": False,
            "comes_from_long_term_storage": False,
            "share_article": article.id,
            "sort": "red",
            "amount": 6,
            "unit": "KG",
            "size": "M",
            "price_per_unit": 3.2,
            "rabatt": None,
            "tax_rate": "7.00",
            "note": "",
            "year": 2026,
            "delivery_week": 15,
            "day_number": 2,
            "reseller": reseller.id,
            **self.ORDER_DAYS,
        }

        created = api_client.post(self.URL, create_body, format="json")

        assert created.status_code == status.HTTP_200_OK, created.data
        line = OrderContent.objects.get(share_article=article)
        assert line.amount == Decimal("6.000")

        patch_body = {
            **create_body,
            "id": line.id,
            "offer": None,
            "is_finalized": False,
            "finalized_at": None,
            "finalized_by": None,
            "amount": 7.5,
            "sort": "yellow",
            "rabatt": 5,
            "note": "late delivery",
        }
        patched = api_client.patch(self._detail_url(line), patch_body, format="json")

        assert patched.status_code == status.HTTP_200_OK, patched.data
        line.refresh_from_db()
        assert line.share_article_id == article.id
        assert line.amount == Decimal("7.500")
        assert line.sort == "yellow"
        assert line.rabatt == 5
        assert line.note == "late delivery"

    def test_customer_page_payloads_via_staff_route(self, api_client, tenant):
        """``CustomerOrderPage`` is also mounted for staff at
        ``/commissioning/customer-orders/:resellerId``; its exact create and
        PATCH bodies (``useCustomerOrderMutations``) must keep working there."""
        from apps.commissioning.models import OrderContent

        reseller = ResellerFactory()
        offer = OfferFactory(amount=Decimal("100.000"), amount_per_pu=Decimal("2.000"))

        created = api_client.post(
            self.URL,
            {
                "offer": offer.id,
                "year": 2026,
                "delivery_week": 15,
                "day_number": 3,
                "reseller": reseller.id,
                "amount": "6.000",
                "price_per_unit": "1.2",
                "unit": "KG",
            },
            format="json",
        )
        assert created.status_code == status.HTTP_200_OK, created.data
        line = OrderContent.objects.get(offer=offer)

        patched = api_client.patch(
            self._detail_url(line),
            {"amount": "12.000", "price_per_unit": "1"},
            format="json",
        )

        assert patched.status_code == status.HTTP_200_OK, patched.data
        line.refresh_from_db()
        assert line.amount == Decimal("12.000")
        assert line.price_per_unit == Decimal("1.00")
        offer.refresh_from_db()
        assert offer.amount == Decimal("94.000")

    def test_patch_without_amount_keeps_amount_stock_and_crate_row(
        self, api_client, tenant
    ):
        from apps.commissioning.models import OrderContent

        reseller = ResellerFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("2.50"))
        offer = OfferFactory(amount=Decimal("100.000"), used_crate=crate)
        created = api_client.post(
            self.URL,
            {
                "offer": offer.id,
                "year": 2026,
                "delivery_week": 15,
                "day_number": 2,
                "reseller": reseller.id,
                "amount": "8.000",
                "price_per_unit": "4.50",
                "unit": "KG",
            },
            format="json",
        )
        assert created.status_code == status.HTTP_200_OK, created.data
        line = OrderContent.objects.get(offer=offer)
        crate_row = CrateOrderContent.objects.get(order_content=line)
        offer.refresh_from_db()
        assert offer.amount == Decimal("92.000")

        resp = api_client.patch(
            self._detail_url(line), {"note": "ring the bell"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "ring the bell"
        assert line.amount == Decimal("8.000")
        offer.refresh_from_db()
        assert offer.amount == Decimal("92.000")
        crate_rows = list(CrateOrderContent.objects.filter(order_content=line))
        assert [row.id for row in crate_rows] == [crate_row.id]
        assert crate_rows[0].amount == crate_row.amount


# ---------------------------------------------------------------------------
# InvoiceResellerViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInvoiceResellerViewSet:
    URL = reverse("invoices-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns(self, api_client, tenant):
        InvoiceResellerFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_upload_pdf_requires_finalized(self, api_client, tenant):
        inv = InvoiceResellerFactory(is_finalized=False)
        url = reverse("invoices-upload-pdf", kwargs={"pk": inv.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "document.not_finalized"
        assert "finalized" in resp.data["message"].lower()

    def test_create_storno_rejects_unfinalized_invoice(self, api_client, tenant):
        """``InvoiceReseller.can_be_cancelled()`` requires the invoice to be
        finalized (and not already cancelled). An unfinalized invoice → the
        service raises ``CommissioningError`` → 400."""
        inv = InvoiceResellerFactory(is_finalized=False)
        url = reverse("invoices-create-storno", kwargs={"pk": inv.pk})
        resp = api_client.post(url, {"reason": "tested"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_storno_requires_reason(self, api_client, tenant):
        """CreateStornoRequestSerializer requires ``reason``."""
        inv = InvoiceResellerFactory()
        url = reverse("invoices-create-storno", kwargs={"pk": inv.pk})
        resp = api_client.post(url, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_protected_fields_are_read_only_on_update(self, api_client, tenant):
        """The generic update verb must not let an office user forge the
        invoice's identity / finalization / hash. A PATCH that tries to set
        them is ignored (read_only), so a draft cannot be turned into a
        finalized, out-of-sequence, hash-spoofed document via the API.
        """
        inv = InvoiceResellerFactory(is_finalized=False)
        url = reverse("invoices-detail", kwargs={"pk": inv.pk})
        resp = api_client.patch(
            url,
            {
                "number": 99999,
                "prefix": "HACK",
                "is_finalized": True,
                "document_type": "storno",
                "document_hash": "deadbeef",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        inv.refresh_from_db()
        assert inv.is_finalized is False
        assert inv.number != 99999
        assert inv.prefix != "HACK"
        assert inv.document_type == "invoice"
        assert inv.document_hash != "deadbeef"


# ---------------------------------------------------------------------------
# DeliveryNoteResellerViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryNoteResellerViewSet:
    URL = reverse("delivery_notes-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns(self, api_client, tenant):
        DeliveryNoteResellerFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_upload_pdf_requires_finalized(self, api_client, tenant):
        dn = DeliveryNoteResellerFactory()
        url = reverse("delivery_notes-upload-pdf", kwargs={"pk": dn.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "document.not_finalized"
        assert "finalized" in resp.data["message"].lower()

    def test_send_to_reseller_requires_finalized(self, api_client, tenant):
        dn = DeliveryNoteResellerFactory()  # not finalized
        url = reverse("delivery_notes-send-to-reseller", kwargs={"pk": dn.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "document.not_finalized"

    def test_send_to_reseller_requires_pdf(self, api_client, tenant):
        from apps.commissioning.tests.factories import OrderFactory, ResellerFactory

        reseller = ResellerFactory(invoice_email="r@example.org")
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order, is_finalized=True)
        url = reverse("delivery_notes-send-to-reseller", kwargs={"pk": dn.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "document.pdf_missing"

    def test_send_to_reseller_requires_reseller_email(self, api_client, tenant):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.commissioning.tests.factories import OrderFactory, ResellerFactory

        reseller = ResellerFactory(invoice_email=None)
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order, is_finalized=True)
        dn.file = SimpleUploadedFile(
            "ls.pdf", b"%PDF-1.4 t", content_type="application/pdf"
        )
        dn.save(update_fields=["file"])

        url = reverse("delivery_notes-send-to-reseller", kwargs={"pk": dn.pk})
        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "reseller.email_missing"

    def test_send_to_reseller_happy_path(self, api_client, tenant):
        from unittest import mock

        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.commissioning.tests.factories import OrderFactory, ResellerFactory
        from apps.shared.tenants.email_service import EmailService

        reseller = ResellerFactory(invoice_email="r@example.org")
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order, is_finalized=True)
        dn.file = SimpleUploadedFile(
            "ls.pdf", b"%PDF-1.4 t", content_type="application/pdf"
        )
        dn.save(update_fields=["file"])

        url = reverse("delivery_notes-send-to-reseller", kwargs={"pk": dn.pk})
        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            resp = api_client.post(url)

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["sent"] is True
        assert resp.data["has_been_sent_to_reseller_at"] is not None
        # autospec keeps self positional → confirms instance call.
        assert isinstance(send_email.call_args.args[0], EmailService)


# ---------------------------------------------------------------------------
# CommissioningListResellersViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCommissioningListResellersViewSet:
    URL = reverse("commissioning_list_resellers-list")

    def test_requires_params(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_for_valid_params(self, api_client, tenant):
        order = OrderFactory(year=2026, delivery_week=20, day_number=3)
        OrderContentFactory(order=order)
        resp = api_client.get(
            self.URL, {"year": 2026, "delivery_week": 20, "day_number": 3}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# CrateOrderContentViewSet — write-body validation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCrateOrderContentViewSetCreateValidation:
    URL = reverse("crate_contents-list")

    def _payload(self, reseller, crate, **overrides):
        payload = {
            "crate_type": crate.id,
            "amount": 3,
            "year": 2026,
            "delivery_week": 15,
            "day_number": 2,
            "reseller": reseller.id,
        }
        payload.update(overrides)
        return payload

    def test_non_numeric_year_returns_400_not_500(self, api_client, tenant):
        reseller = ResellerFactory()
        crate = CrateFactory()
        resp = api_client.post(
            self.URL,
            self._payload(reseller, crate, year="abc"),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_amount_returns_400(self, api_client, tenant):
        reseller = ResellerFactory()
        crate = CrateFactory()
        payload = self._payload(reseller, crate)
        payload.pop("amount")
        resp = api_client.post(self.URL, payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_valid_payload_creates_order_and_crate(self, api_client, tenant):
        reseller = ResellerFactory()
        crate = CrateFactory()
        resp = api_client.post(self.URL, self._payload(reseller, crate), format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        # The service get-or-creates the Order and attaches the crate to it.
        assert Order.objects.filter(reseller=reseller, year=2026).count() == 1
        assert CrateOrderContent.objects.filter(crate_type=crate).count() == 1

    def test_partial_update_non_numeric_year_returns_400(self, api_client, tenant):
        reseller = ResellerFactory()
        crate = CrateFactory()
        url = reverse("crate_contents-detail", kwargs={"pk": crate.id})
        resp = api_client.patch(
            url,
            {
                "year": "abc",
                "delivery_week": 15,
                "day_number": 2,
                "reseller": reseller.id,
                "amount": 5,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# OrganicCertificateViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOrganicCertificateViewSet:
    URL = reverse("organic_certificates-list")

    def test_create_certificate(self, api_client, tenant):
        reseller = ResellerFactory()
        resp = api_client.post(
            self.URL,
            {
                "reseller": str(reseller.id),
                "valid_from": "2026-01-05",  # a Monday (TimeBoundMixin requires it)
                "certificate_number": "CERT-2026-001",
                "link": "https://example.org/cert.pdf",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["certificate_number"] == "CERT-2026-001"

    def test_list_filtered_by_reseller(self, api_client, tenant):
        reseller_a = ResellerFactory()
        reseller_b = ResellerFactory()
        OrganicCertificate.objects.create(
            reseller=reseller_a, valid_from=date(2026, 1, 5)
        )
        OrganicCertificate.objects.create(
            reseller=reseller_b, valid_from=date(2026, 1, 5)
        )
        resp = api_client.get(self.URL, {"reseller": str(reseller_a.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["reseller"] == str(reseller_a.id)

    def test_second_certificate_closes_predecessor(self, api_client, tenant):
        # TimeBoundMixin succession: opening a later certificate auto-closes the
        # currently-open one the day before the new valid_from.
        reseller = ResellerFactory()
        first = OrganicCertificate.objects.create(
            reseller=reseller, valid_from=date(2026, 1, 5)
        )
        OrganicCertificate.objects.create(
            reseller=reseller, valid_from=date(2026, 6, 1)
        )
        first.refresh_from_db()
        assert first.valid_until is not None


# ---------------------------------------------------------------------------
# PurchaseSerializer — organic-status certificate gating
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPurchaseOrganicValidation:
    """A purchase carrying ``organic`` / ``in_conversion`` is only accepted when
    the seller holds an OrganicCertificate valid for the purchase's delivery
    week (the Monday of the ISO year/week); ``conventional`` never needs one."""

    @staticmethod
    def _attrs(seller, organic_status):
        # Minimal attrs dict as it looks post-field-validation: ``seller`` is a
        # resolved Reseller instance, year/week are ints. Calls validate()
        # directly so the check is exercised without the full create payload.
        return {
            "seller": seller,
            "year": 2026,
            "delivery_week": 15,
            "organic_status": organic_status,
        }

    def test_conventional_needs_no_certificate(self, tenant):
        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        result = PurchaseSerializer().validate(self._attrs(seller, "conventional"))
        assert result["organic_status"] == "conventional"

    def test_organic_without_certificate_is_rejected(self, tenant):
        from apps.commissioning.errors import OrganicPurchaseCertificateRequired
        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        with pytest.raises(OrganicPurchaseCertificateRequired):
            PurchaseSerializer().validate(self._attrs(seller, "organic"))

    def test_in_conversion_without_certificate_is_rejected(self, tenant):
        from apps.commissioning.errors import OrganicPurchaseCertificateRequired
        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        with pytest.raises(OrganicPurchaseCertificateRequired):
            PurchaseSerializer().validate(self._attrs(seller, "in_conversion"))

    def test_organic_with_certificate_covering_week_is_valid(self, tenant):
        from isoweek import Week

        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        # Open-ended certificate from ISO week 1 Monday → covers week 15.
        OrganicCertificate.objects.create(
            reseller=seller, valid_from=Week(2026, 1).monday()
        )
        result = PurchaseSerializer().validate(self._attrs(seller, "organic"))
        assert result["organic_status"] == "organic"

    def test_organic_rejected_when_certificate_expired_before_week(self, tenant):
        from isoweek import Week

        from apps.commissioning.errors import OrganicPurchaseCertificateRequired
        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        # Certificate closed before week 15 (valid_until = week 10 Sunday).
        OrganicCertificate.objects.create(
            reseller=seller,
            valid_from=Week(2026, 1).monday(),
            valid_until=Week(2026, 10).sunday(),
        )
        with pytest.raises(OrganicPurchaseCertificateRequired):
            PurchaseSerializer().validate(self._attrs(seller, "organic"))

    # ── Tight boundary weeks (window pins to the delivery week's Monday) ──

    def test_certificate_starting_exactly_on_delivery_week_is_valid(self, tenant):
        """``valid_from`` == the delivery week's Monday is inclusive → covered."""
        from isoweek import Week

        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        OrganicCertificate.objects.create(
            reseller=seller, valid_from=Week(2026, 15).monday()
        )
        result = PurchaseSerializer().validate(self._attrs(seller, "organic"))
        assert result["organic_status"] == "organic"

    def test_certificate_starting_week_after_is_rejected(self, tenant):
        """``valid_from`` one week after the purchase → not yet active."""
        from isoweek import Week

        from apps.commissioning.errors import OrganicPurchaseCertificateRequired
        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        OrganicCertificate.objects.create(
            reseller=seller, valid_from=Week(2026, 16).monday()
        )
        with pytest.raises(OrganicPurchaseCertificateRequired):
            PurchaseSerializer().validate(self._attrs(seller, "organic"))

    def test_certificate_ending_on_delivery_week_sunday_is_valid(self, tenant):
        """``valid_until`` == the delivery week's Sunday is inclusive (the week's
        Monday still falls inside the window) → covered."""
        from isoweek import Week

        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        OrganicCertificate.objects.create(
            reseller=seller,
            valid_from=Week(2026, 1).monday(),
            valid_until=Week(2026, 15).sunday(),
        )
        result = PurchaseSerializer().validate(self._attrs(seller, "organic"))
        assert result["organic_status"] == "organic"

    def test_certificate_ending_prior_week_sunday_is_rejected(self, tenant):
        """``valid_until`` == the PRIOR week's Sunday → the delivery week's Monday
        is one day past the window (the tight closing edge)."""
        from isoweek import Week

        from apps.commissioning.errors import OrganicPurchaseCertificateRequired
        from apps.commissioning.serializers import PurchaseSerializer

        seller = ResellerFactory()
        OrganicCertificate.objects.create(
            reseller=seller,
            valid_from=Week(2026, 1).monday(),
            valid_until=Week(2026, 14).sunday(),
        )
        with pytest.raises(OrganicPurchaseCertificateRequired):
            PurchaseSerializer().validate(self._attrs(seller, "organic"))
