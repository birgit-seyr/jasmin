"""OfferViewSet — an edit saves only what it changes, and sets the available
amount by compare-and-set.

Order lines move an offer's available amount (``Offer.amount``) under the
offer's row lock, on drafts as on published offers, while the Offers page holds
the amount it loaded. The page sends the whole loaded row on every save, with
the amount the row opened with as ``expected_amount``. The edit saves only the fields that
differ from the stored offer, so a published offer, which lets only its amount
change, takes an edit of the amount; and it saves an amount only when the
client changed it and the stock hasn't moved since.

No test here depends on the wall clock: neither the offer nor the order-line
endpoint has a past-week guard.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import Offer
from apps.commissioning.tests.factories import (
    CrateFactory,
    OfferFactory,
    OfferGroupFactory,
    ResellerFactory,
    ShareArticleFactory,
)

LIST_URL = reverse("offer-list")


def _detail_url(offer_id: str) -> str:
    return reverse("offer-detail", kwargs={"pk": offer_id})


def _load(api_client, offer: Offer) -> dict[str, Any]:
    """The offer's row as the Offers page loads it."""
    resp = api_client.get(_detail_url(offer.pk))
    assert resp.status_code == status.HTTP_200_OK, resp.data
    return resp.json()


def _save(api_client, row: dict[str, Any], **changes: Any):
    """Save ``row`` as the Offers page does: the whole loaded row with the
    office's changes over it, and the amount the row opened with as
    ``expected_amount``."""
    body = {**row, **changes, "expected_amount": row["amount"]}
    return api_client.patch(_detail_url(row["id"]), body, format="json")


def _order(api_client, offer: Offer, amount: str) -> None:
    """An order line on ``offer``, which takes ``amount`` off its stock."""
    resp = api_client.post(
        reverse("order_contents-list"),
        {
            "offer": str(offer.id),
            "reseller": str(ResellerFactory().id),
            "year": offer.year,
            "delivery_week": offer.delivery_week,
            "day_number": 0,
            "amount": amount,
            "price_per_unit": "4.5",
            "unit": "KG",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data


def _offer_updates(captured: CaptureQueriesContext) -> list[str]:
    return [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].startswith('UPDATE "commissioning_offer"')
    ]


@pytest.mark.django_db
class TestOfferEditKeepsTheStock:
    def test_a_price_edit_keeps_what_orders_took_since_the_page_loaded(
        self, api_client, tenant
    ):
        offer = OfferFactory(amount=Decimal("100"), price_1=Decimal("2.40"))
        row = _load(api_client, offer)
        _order(api_client, offer, "8.000")

        resp = _save(api_client, row, price_1="2.60")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["amount"] == "92.000"
        offer.refresh_from_db()
        assert offer.amount == Decimal("92")
        assert offer.price_1 == Decimal("2.60")

    def test_an_amount_edit_after_orders_moved_the_stock_is_refused(
        self, api_client, tenant
    ):
        offer = OfferFactory(amount=Decimal("100"), price_1=Decimal("2.40"))
        row = _load(api_client, offer)
        _order(api_client, offer, "8.000")

        resp = _save(api_client, row, amount="120.000", price_1="2.60")

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "offer.amount_changed"
        assert resp.data["details"] == {"offer_id": offer.pk, "amount": "92.000"}
        offer.refresh_from_db()
        assert offer.amount == Decimal("92")
        assert offer.price_1 == Decimal("2.40")

    def test_an_amount_edit_of_unmoved_stock_is_saved(self, api_client, tenant):
        offer = OfferFactory(amount=Decimal("100"))
        row = _load(api_client, offer)

        resp = _save(api_client, row, amount="120.500")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["amount"] == "120.500"
        offer.refresh_from_db()
        assert offer.amount == Decimal("120.5")

    def test_the_answer_keeps_the_lists_annotations(self, api_client, tenant):
        offer = OfferFactory()
        row = _load(api_client, offer)

        resp = _save(api_client, row, note="Washed")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["share_article_name"] == offer.share_article.name
        assert resp.data["amount_ordered"] == row["amount_ordered"]
        assert resp.data["organic_status"] == offer.share_article.organic_status
        assert resp.data["note"] == "Washed"

    def test_a_crate_is_set_and_cleared(self, api_client, tenant):
        offer = OfferFactory()
        crate = CrateFactory()

        resp = _save(api_client, _load(api_client, offer), used_crate=crate.pk)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.used_crate_id == crate.pk

        resp = _save(api_client, resp.json(), used_crate=None)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.used_crate_id is None

    def test_the_offer_is_read_under_its_row_lock(self, api_client, tenant):
        offer = OfferFactory()
        row = _load(api_client, offer)

        with CaptureQueriesContext(connection) as captured:
            _save(api_client, row, amount="50.000")

        assert any(
            "FOR UPDATE" in query["sql"]
            and 'FROM "commissioning_offer"' in query["sql"]
            for query in captured.captured_queries
        )

    def test_only_the_changed_fields_are_written(self, api_client, tenant):
        offer = OfferFactory()
        row = _load(api_client, offer)

        with CaptureQueriesContext(connection) as captured:
            _save(api_client, row, note="Washed")

        (update,) = _offer_updates(captured)
        assert '"note"' in update
        assert '"amount"' not in update

    def test_a_save_without_changes_writes_nothing(self, api_client, tenant):
        offer = OfferFactory()
        row = _load(api_client, offer)

        with CaptureQueriesContext(connection) as captured:
            resp = _save(api_client, row)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _offer_updates(captured) == []


@pytest.mark.django_db
class TestOfferEditWithoutExpectedAmount:
    """A client that doesn't send the amount it read, such as a tab still
    running an older page, can't tell its own change from stock that moved."""

    def test_the_stored_amount_goes_through_with_the_other_changes(
        self, api_client, tenant
    ):
        offer = OfferFactory(amount=Decimal("100"))

        resp = api_client.patch(
            _detail_url(offer.pk),
            {"amount": "100.000", "note": "Washed"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.note == "Washed"

    def test_another_amount_is_refused(self, api_client, tenant):
        offer = OfferFactory(amount=Decimal("100"))

        resp = api_client.patch(
            _detail_url(offer.pk), {"amount": "92.000", "note": "Washed"}, format="json"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "offer.amount_changed"
        assert resp.data["message"].startswith("This page is out of date.")
        offer.refresh_from_db()
        assert offer.amount == Decimal("100")
        assert offer.note is None

    def test_an_edit_without_an_amount_leaves_the_stock_alone(self, api_client, tenant):
        offer = OfferFactory(amount=Decimal("100"))

        resp = api_client.patch(
            _detail_url(offer.pk), {"note": "Washed"}, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.amount == Decimal("100")


@pytest.mark.django_db
class TestPublishedOfferEdit:
    """A published offer lets only its amount change, in Python and in the
    database trigger alike."""

    def test_the_page_corrects_a_published_offers_amount(self, api_client, tenant):
        offer = OfferFactory(amount=Decimal("100"), is_finalized=True)
        row = _load(api_client, offer)

        resp = _save(api_client, row, amount="80.000")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.amount == Decimal("80")
        assert offer.is_finalized is True

    def test_its_other_fields_stay_as_published(self, api_client, tenant):
        offer = OfferFactory(amount=Decimal("100"), is_finalized=True)
        row = _load(api_client, offer)

        resp = _save(api_client, row, amount="80.000", note="Washed")

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "commissioning.already_finalized"
        offer.refresh_from_db()
        assert offer.amount == Decimal("100")
        assert offer.note is None

    def test_an_unchanged_save_is_no_error(self, api_client, tenant):
        offer = OfferFactory(is_finalized=True)
        row = _load(api_client, offer)

        resp = _save(api_client, row)

        assert resp.status_code == status.HTTP_200_OK, resp.data

    def test_a_new_amount_after_orders_moved_the_stock_is_refused(
        self, api_client, tenant
    ):
        offer = OfferFactory(amount=Decimal("100"), is_finalized=True)
        row = _load(api_client, offer)
        _order(api_client, offer, "8.000")

        resp = _save(api_client, row, amount="80.000")

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "offer.amount_changed"
        offer.refresh_from_db()
        assert offer.amount == Decimal("92")

    def test_stored_text_with_spaces_around_it_counts_as_unchanged(
        self, api_client, tenant
    ):
        # The serializer strips the text it takes, so the untouched description
        # comes back without the spaces the stored one has.
        offer = OfferFactory(
            amount=Decimal("100"), description="Organic ", is_finalized=True
        )

        resp = _save(api_client, _load(api_client, offer), amount="80.000")

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.amount == Decimal("80")


@pytest.mark.django_db
class TestOfferCreate:
    def test_a_new_offer_ignores_expected_amount(self, api_client, tenant):
        resp = api_client.post(
            LIST_URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_article": str(ShareArticleFactory().id),
                "unit": "KG",
                "size": "M",
                "amount_per_pu": "1.000",
                "amount": "40.000",
                "offer_group": str(OfferGroupFactory().id),
                "expected_amount": "5.000",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert Offer.objects.get(pk=resp.data["id"]).amount == Decimal("40")
