"""Tests for resellers_viewsets.py — Reseller, Offer, OfferGroup, OrderContent,
Invoice, DeliveryNote, CommissioningList viewsets."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import CrateOrderContent, Order
from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OfferFactory,
    OfferGroupFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
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
        # GDPR-MIN-1: ContactEntity.iban is encrypted at rest; the reseller read
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
# CrateOrderContentViewSet — write-body validation (OC-1)
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
