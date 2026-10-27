"""A purchase's weekly slot, where the office's purchases, the planner's
placeholders and the bulk "set as expected" meet.

A new purchase without a day takes ``PURCHASE_DAY`` and fills the empty
placeholder of its supplier and storage instead of adding a second row. The
planner's placeholder never takes over a purchase documented from another
supplier, nor joins one as an empty row, and "set as expected" writes the
selected supplier's row only.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.constants import PURCHASE_DAY
from apps.commissioning.models import (
    AdditionalTheoreticalPurchase,
    MovementShareArticle,
    Purchase,
)
from apps.commissioning.services.documentation_summary_service import (
    DocumentationSummaryService,
)
from apps.commissioning.services.theoretical_objects import (
    TheoreticalSourceData,
    _ensure_purchase_placeholder,
)
from apps.commissioning.tests.factories import (
    PurchaseFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareContentFactory,
    StorageFactory,
)

YEAR, WEEK = 2026, 15
PURCHASE_URL = reverse("purchase-list")
BULK_URL = reverse("purchase-bulk-set-as-expected")


@pytest.fixture(autouse=True)
def _frozen_clock():
    # Week 15 of 2026 is the current week on its Monday, so the documentation
    # endpoints accept writes to it.
    with time_machine.travel(datetime.datetime(2026, 4, 6, 12, 0), tick=False):
        yield


@pytest.fixture
def storage():
    return StorageFactory(is_short_term_harvest_storage=True)


@pytest.fixture
def article():
    return ShareArticleFactory(is_purchased=True)


def _row(article, storage, seller, amount):
    return PurchaseFactory(
        year=YEAR,
        delivery_week=WEEK,
        day_number=PURCHASE_DAY,
        share_article=article,
        unit="KG",
        size="M",
        storage=storage,
        seller=seller,
        amount=amount,
    )


def _plan(article, storage, seller):
    return TheoreticalSourceData(
        year=YEAR,
        delivery_week=WEEK,
        delivery_day=2,
        harvesting_day=None,
        washing_day=None,
        cleaning_day=None,
        share_article=article,
        amount=Decimal("8"),
        unit="KG",
        size="M",
        note=None,
        washing=False,
        cleaning=False,
        forecast=None,
        is_purchased=True,
        share_content=ShareContentFactory(share_article=article),
        seller=seller,
        storage=storage,
    )


def _slot(article):
    return Purchase.objects.filter(share_article=article)


@pytest.mark.django_db
class TestPlannerPlaceholder:
    def test_a_purchase_from_another_supplier_keeps_its_supplier_and_the_plan(
        self, tenant, article, storage
    ):
        """No empty row joins it: "set as expected" on one would book the plan
        on top of the purchase."""
        other, planned = ResellerFactory(), ResellerFactory()
        documented = _row(article, storage, other, Decimal("5"))

        _ensure_purchase_placeholder(_plan(article, storage, planned))

        documented.refresh_from_db()
        assert documented.seller_id == other.pk
        assert _slot(article).count() == 1

    def test_beside_a_purchase_from_another_supplier_the_placeholder_follows(
        self, tenant, article, storage
    ):
        other, planned = ResellerFactory(), ResellerFactory()
        documented = _row(article, storage, other, Decimal("5"))
        placeholder = _row(article, storage, ResellerFactory(), None)

        plan = _plan(article, storage, planned)
        # Twice: a second plan run finds the slot's rows as the first left them.
        _ensure_purchase_placeholder(plan)
        _ensure_purchase_placeholder(plan)

        documented.refresh_from_db()
        placeholder.refresh_from_db()
        assert documented.seller_id == other.pk
        assert placeholder.seller_id == planned.pk
        assert _slot(article).count() == 2

    def test_the_planned_suppliers_purchase_is_the_slots_row(
        self, tenant, article, storage
    ):
        planned = ResellerFactory()
        _row(article, storage, planned, Decimal("5"))

        _ensure_purchase_placeholder(_plan(article, storage, planned))

        assert _slot(article).count() == 1

    def test_an_empty_placeholder_follows_the_plan_to_its_supplier(
        self, tenant, article, storage
    ):
        placeholder = _row(article, storage, ResellerFactory(), None)
        planned = ResellerFactory()

        _ensure_purchase_placeholder(_plan(article, storage, planned))

        placeholder.refresh_from_db()
        assert placeholder.seller_id == planned.pk
        assert _slot(article).count() == 1

    def test_a_plan_without_a_supplier_keeps_the_placeholders(
        self, tenant, article, storage
    ):
        seller = ResellerFactory()
        placeholder = _row(article, storage, seller, None)

        _ensure_purchase_placeholder(_plan(article, storage, None))

        placeholder.refresh_from_db()
        assert placeholder.seller_id == seller.pk
        assert _slot(article).count() == 1


@pytest.mark.django_db
class TestOfficePurchase:
    def _post(self, api_client, article, storage, seller):
        """What the purchase page sends: a week, a seller, no weekday."""
        return api_client.post(
            PURCHASE_URL,
            {
                "year": YEAR,
                "delivery_week": WEEK,
                "share_article": str(article.id),
                "unit": "KG",
                "size": "M",
                "amount": "4",
                "storage": str(storage.id),
                **({"seller": str(seller.id)} if seller else {}),
            },
            format="json",
        )

    def test_without_a_supplier_fills_the_placeholder_without_one(
        self, api_client, tenant, article, storage
    ):
        placeholder = _row(article, storage, None, None)

        resp = self._post(api_client, article, storage, None)

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["id"] == placeholder.id
        placeholder.refresh_from_db()
        assert placeholder.amount == Decimal("4")
        assert _slot(article).count() == 1

    def test_fills_the_empty_placeholder_of_its_supplier_and_storage(
        self, api_client, user, tenant, article, storage
    ):
        seller = ResellerFactory()
        placeholder = _row(article, storage, seller, None)

        resp = self._post(api_client, article, storage, seller)

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["id"] == placeholder.id
        placeholder.refresh_from_db()
        assert placeholder.amount == Decimal("4")
        assert placeholder.created_by_id == user.pk
        assert _slot(article).count() == 1
        assert MovementShareArticle.objects.filter(purchase=placeholder).exists()

    def test_next_to_another_suppliers_placeholder_gets_its_own_row(
        self, api_client, tenant, article, storage
    ):
        placeholder = _row(article, storage, ResellerFactory(), None)
        seller = ResellerFactory()

        resp = self._post(api_client, article, storage, seller)

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        purchase = Purchase.objects.get(id=resp.data["id"])
        assert (purchase.day_number, purchase.seller_id) == (PURCHASE_DAY, seller.pk)
        placeholder.refresh_from_db()
        assert placeholder.amount is None
        assert _slot(article).count() == 2

    def test_a_placeholder_in_another_storage_is_left_alone(
        self, api_client, tenant, article, storage
    ):
        seller = ResellerFactory()
        placeholder = _row(article, StorageFactory(), seller, None)

        resp = self._post(api_client, article, storage, seller)

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["id"] != placeholder.id
        placeholder.refresh_from_db()
        assert placeholder.amount is None


@pytest.mark.django_db
class TestSetAsExpected:
    def _item(self, article, storage, **extra):
        return {
            "id": str(article.id),
            "year": YEAR,
            "delivery_week": WEEK,
            "theoretical_purchase_amount": "8",
            "theoretical_purchase_unit": "KG",
            "theoretical_purchase_size": "M",
            "storage": str(storage.id),
            **extra,
        }

    def test_writes_the_selected_suppliers_row_only(
        self, api_client, tenant, article, storage
    ):
        planned, other = ResellerFactory(), ResellerFactory()
        placeholder = _row(article, storage, planned, None)
        bought = _row(article, storage, other, Decimal("0"))

        resp = api_client.post(
            BULK_URL,
            {"selectedData": [self._item(article, storage, seller=str(planned.id))]},
            format="json",
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.data
        placeholder.refresh_from_db()
        bought.refresh_from_db()
        assert placeholder.amount == Decimal("8")
        assert bought.amount == Decimal("0")
        assert _slot(article).count() == 2

    def test_a_row_without_a_supplier_is_written_as_one(
        self, api_client, tenant, article, storage
    ):
        placeholder = _row(article, storage, None, None)
        bought = _row(article, storage, ResellerFactory(), Decimal("0"))

        resp = api_client.post(
            BULK_URL,
            {"selectedData": [self._item(article, storage, seller=None)]},
            format="json",
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.data
        placeholder.refresh_from_db()
        bought.refresh_from_db()
        assert placeholder.amount == Decimal("8")
        assert bought.amount == Decimal("0")

    def test_a_client_that_sends_no_seller_writes_the_slots_empty_row(
        self, api_client, tenant, article, storage
    ):
        placeholder = _row(article, storage, ResellerFactory(), None)
        bought = _row(article, storage, ResellerFactory(), Decimal("0"))

        resp = api_client.post(
            BULK_URL, {"selectedData": [self._item(article, storage)]}, format="json"
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.data
        placeholder.refresh_from_db()
        bought.refresh_from_db()
        assert placeholder.amount == Decimal("8")
        assert bought.amount == Decimal("0")
        assert _slot(article).count() == 2

    def test_an_unknown_seller_is_refused(self, api_client, tenant, article, storage):
        placeholder = _row(article, storage, ResellerFactory(), None)

        resp = api_client.post(
            BULK_URL,
            {"selectedData": [self._item(article, storage, seller="unknown")]},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        placeholder.refresh_from_db()
        assert placeholder.amount is None


@pytest.mark.django_db
class TestAdditionalAmountOnTheSlot:
    def test_a_documented_purchase_takes_it_and_keeps_its_fields(
        self, tenant, article, storage
    ):
        seller = ResellerFactory()
        documented = _row(article, storage, seller, Decimal("5"))
        Purchase.objects.filter(pk=documented.pk).update(amount_per_pu=Decimal("2.5"))

        with mock.patch.object(
            DocumentationSummaryService, "_get_short_term_storage", return_value=storage
        ):
            instance = DocumentationSummaryService.add_additional_theoretical_amount(
                {
                    "share_article": article.id,
                    "year": YEAR,
                    "delivery_week": WEEK,
                    "unit": "KG",
                    "size": "M",
                    "seller": seller.id,
                    "amount": 3,
                },
                "purchase",
            )

        assert instance.pk == documented.pk
        documented.refresh_from_db()
        assert (documented.amount, documented.amount_per_pu) == (
            Decimal("5"),
            Decimal("2.5"),
        )
        assert AdditionalTheoreticalPurchase.objects.filter(
            share_article=article, seller=seller, amount=Decimal("3")
        ).exists()
        assert _slot(article).count() == 1
