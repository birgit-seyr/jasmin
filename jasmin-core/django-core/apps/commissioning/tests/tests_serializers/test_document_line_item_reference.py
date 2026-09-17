"""A delivery-note / invoice line references EXACTLY one item.

``OrderableItem`` defines the rule (an ``offer`` or a ``share_article``, never
both and never neither) and ``OrderContent`` inherits it from its model
``save()``. The two document-line models deliberately skip ``full_clean()`` —
running every field check on a legally immutable row would start rejecting
saves over unrelated legacy values — so their serializers carry the targeted
check for the client-writable path. These tests pin both endpoints.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import DeliveryNoteContent, InvoiceResellerContent
from apps.commissioning.tests.factories import (
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OfferFactory,
    ShareArticleFactory,
)

REFERENCE_INVALID = "orderable_item.reference_invalid"


def _line_payload(**overrides) -> dict:
    payload = {
        "amount": "1.000",
        "unit": "KG",
        "size": "M",
        "tax_rate": "7.00",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestInvoiceLineItemReference:
    URL = reverse("invoice_contents-list")

    def test_create_with_share_article_only_is_accepted(self, api_client, tenant):
        invoice = InvoiceResellerFactory()

        resp = api_client.post(
            self.URL,
            _line_payload(invoice=invoice.pk, share_article=ShareArticleFactory().pk),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_create_with_offer_only_is_accepted(self, api_client, tenant):
        invoice = InvoiceResellerFactory()

        resp = api_client.post(
            self.URL,
            _line_payload(invoice=invoice.pk, offer=OfferFactory().pk),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_create_with_both_references_is_rejected(self, api_client, tenant):
        invoice = InvoiceResellerFactory()

        resp = api_client.post(
            self.URL,
            _line_payload(
                invoice=invoice.pk,
                offer=OfferFactory().pk,
                share_article=ShareArticleFactory().pk,
            ),
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        assert not InvoiceResellerContent.objects.filter(invoice=invoice).exists()

    def test_create_with_neither_reference_is_rejected(self, api_client, tenant):
        invoice = InvoiceResellerFactory()

        resp = api_client.post(
            self.URL, _line_payload(invoice=invoice.pk), format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        assert not InvoiceResellerContent.objects.filter(invoice=invoice).exists()

    def test_patch_cannot_add_a_second_reference(self, api_client, tenant):
        invoice = InvoiceResellerFactory()
        line = InvoiceResellerContent.objects.create(
            invoice=invoice,
            share_article=ShareArticleFactory(),
            amount="1.000",
            unit="KG",
            size="M",
            tax_rate="7.00",
        )

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"offer": OfferFactory().pk},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        line.refresh_from_db()
        assert line.offer_id is None

    def test_patch_cannot_clear_the_only_reference(self, api_client, tenant):
        invoice = InvoiceResellerFactory()
        line = InvoiceResellerContent.objects.create(
            invoice=invoice,
            share_article=ShareArticleFactory(),
            amount="1.000",
            unit="KG",
            size="M",
            tax_rate="7.00",
        )

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"share_article": None},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        line.refresh_from_db()
        assert line.share_article_id is not None

    def test_patch_of_an_unrelated_field_keeps_the_stored_reference(
        self, api_client, tenant
    ):
        """A PATCH that omits both FKs resolves them from the stored row."""
        invoice = InvoiceResellerFactory()
        line = InvoiceResellerContent.objects.create(
            invoice=invoice,
            share_article=ShareArticleFactory(),
            amount="1.000",
            unit="KG",
            size="M",
            tax_rate="7.00",
        )

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"note": "edited"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "edited"

    def test_patch_echoing_an_unchanged_reference_saves_a_two_reference_line(
        self, api_client, tenant
    ):
        """The invoice line table sends the whole edited row, so a note-only
        edit re-states the stored ``share_article``. A line that carries both
        references stays editable while neither reference moves.
        """
        invoice = InvoiceResellerFactory()
        line = InvoiceResellerContent.objects.create(
            invoice=invoice,
            offer=OfferFactory(),
            share_article=ShareArticleFactory(),
            amount="1.000",
            unit="KG",
            size="M",
            tax_rate="7.00",
        )

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"note": "corrected", "share_article": line.share_article_id},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "corrected"
        assert line.offer_id is not None
        assert line.share_article_id is not None

    def test_patch_echoing_an_empty_reference_saves_a_reference_less_line(
        self, api_client, tenant
    ):
        """A line holding neither reference echoes ``share_article: null``, and
        that is still not a move.
        """
        invoice = InvoiceResellerFactory()
        line = InvoiceResellerContent.objects.create(
            invoice=invoice,
            amount="1.000",
            unit="KG",
            size="M",
            tax_rate="7.00",
        )

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"note": "corrected", "share_article": None},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "corrected"

    def test_patch_moving_a_reference_on_a_two_reference_line_is_rejected(
        self, api_client, tenant
    ):
        invoice = InvoiceResellerFactory()
        line = InvoiceResellerContent.objects.create(
            invoice=invoice,
            offer=OfferFactory(),
            share_article=ShareArticleFactory(),
            amount="1.000",
            unit="KG",
            size="M",
            tax_rate="7.00",
        )
        stored_share_article_id = line.share_article_id

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"share_article": ShareArticleFactory().pk},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        line.refresh_from_db()
        assert line.share_article_id == stored_share_article_id


@pytest.mark.django_db
class TestDeliveryNoteLineItemReference:
    URL = reverse("delivery_note_contents-list")

    def test_create_with_share_article_only_is_accepted(self, api_client, tenant):
        delivery_note = DeliveryNoteResellerFactory()

        resp = api_client.post(
            self.URL,
            _line_payload(
                delivery_note=delivery_note.pk,
                share_article=ShareArticleFactory().pk,
            ),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_create_with_offer_only_is_accepted(self, api_client, tenant):
        delivery_note = DeliveryNoteResellerFactory()

        resp = api_client.post(
            self.URL,
            _line_payload(delivery_note=delivery_note.pk, offer=OfferFactory().pk),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_create_with_both_references_is_rejected(self, api_client, tenant):
        delivery_note = DeliveryNoteResellerFactory()

        resp = api_client.post(
            self.URL,
            _line_payload(
                delivery_note=delivery_note.pk,
                offer=OfferFactory().pk,
                share_article=ShareArticleFactory().pk,
            ),
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        assert not DeliveryNoteContent.objects.filter(
            delivery_note=delivery_note
        ).exists()

    def test_create_with_neither_reference_is_rejected(self, api_client, tenant):
        delivery_note = DeliveryNoteResellerFactory()

        resp = api_client.post(
            self.URL, _line_payload(delivery_note=delivery_note.pk), format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        assert not DeliveryNoteContent.objects.filter(
            delivery_note=delivery_note
        ).exists()

    def test_patch_cannot_clear_the_only_reference(self, api_client, tenant):
        line = DeliveryNoteContentFactory()

        resp = api_client.patch(
            reverse("delivery_note_contents-detail", kwargs={"pk": line.pk}),
            {"share_article": None},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == REFERENCE_INVALID
        line.refresh_from_db()
        assert line.share_article_id is not None

    def test_patch_echoing_an_unchanged_reference_saves_a_two_reference_line(
        self, api_client, tenant
    ):
        """The delivery-note line table sends the whole edited row, so a
        note-only edit re-states the stored ``share_article``. A line that
        carries both references stays editable while neither reference moves.
        """
        line = DeliveryNoteContentFactory(offer=OfferFactory())

        resp = api_client.patch(
            reverse("delivery_note_contents-detail", kwargs={"pk": line.pk}),
            {"note": "corrected", "share_article": line.share_article_id},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "corrected"
        assert line.offer_id is not None
        assert line.share_article_id is not None
