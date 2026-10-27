"""Purchases the office records per week, without a weekday, and their plan.

A planned purchase (``TheoreticalPurchase``) and its theoretical movement sit on
``PURCHASE_DAY``. An office purchase without a weekday lands there too, so its
correction nets the plan: stock counts what was bought, not the plan on top.
Several purchases of one item on one day replace the plan together, so it is
subtracted once.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.db.models import Q, Sum
from django.urls import reverse
from rest_framework import status

from apps.commissioning.constants import PURCHASE_DAY
from apps.commissioning.models import MovementShareArticle, Purchase
from apps.commissioning.models.choices import MovementTypeOptions
from apps.commissioning.services.documentation_service import (
    GenericDocumentationService,
)
from apps.commissioning.services.documentation_summary_service import (
    DocumentationSummaryService,
)
from apps.commissioning.tests.factories import (
    AdditionalTheoreticalPurchaseFactory,
    ResellerFactory,
    ShareArticleFactory,
    StorageFactory,
    TheoreticalPurchaseFactory,
)
from apps.commissioning.utils.iso_week_utils import make_noon_datetime

YEAR, WEEK = 2026, 15


@pytest.fixture(autouse=True)
def _frozen_clock():
    # The writes go to week 15 of 2026, which the documentation and stock
    # count endpoints refuse once it lies more than a week back; on Monday of
    # week 15 it is the current week.
    with time_machine.travel(datetime.datetime(2026, 4, 6, 12, 0), tick=False):
        yield


PURCHASE_NOON = make_noon_datetime(YEAR, WEEK, PURCHASE_DAY)
MONDAY_NOON = make_noon_datetime(YEAR, WEEK, 0)
PURCHASE_URL = reverse("purchase-list")


@pytest.fixture
def storage():
    return StorageFactory(is_short_term_harvest_storage=True)


@pytest.fixture
def article():
    return ShareArticleFactory(is_purchased=True)


def _plan(article, storage, amount: int) -> None:
    """A planned purchase with its theoretical movement on PURCHASE_DAY."""
    theoretical = TheoreticalPurchaseFactory(
        year=YEAR,
        delivery_week=WEEK,
        day_number=PURCHASE_DAY,
        share_article=article,
        storage=storage,
        amount=amount,
    )
    MovementShareArticle.objects.create(
        date=PURCHASE_NOON,
        movement_type=MovementTypeOptions.PURCHASE,
        theoretical_purchase=theoretical,
        share_article=article,
        unit="KG",
        size="M",
        storage=storage,
        amount=Decimal(amount),
        is_theoretical=True,
    )


def _office_purchase(
    api_client, article, storage, amount: int, day_number: int | None = None
) -> Purchase:
    """What the purchase page sends: a week, a seller, no weekday."""
    payload = {
        "year": YEAR,
        "delivery_week": WEEK,
        "share_article": str(article.id),
        "unit": "KG",
        "size": "M",
        "amount": str(amount),
        "storage": str(storage.id),
        "seller": str(ResellerFactory().id),
    }
    if day_number is not None:
        payload["day_number"] = day_number
    resp = api_client.post(PURCHASE_URL, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.data
    return Purchase.objects.get(id=resp.data["id"])


def _stock(article, storage, until: datetime.datetime) -> Decimal:
    return MovementShareArticle.objects.filter(
        share_article=article, unit="KG", size="M", storage=storage, date__lte=until
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")


def _end_of(day: datetime.datetime) -> datetime.datetime:
    return day.replace(hour=23, minute=59, second=59)


@pytest.mark.django_db
class TestOfficePurchaseWithoutWeekday:
    def test_lands_with_its_plan_and_replaces_it(
        self, api_client, tenant, article, storage
    ):
        _plan(article, storage, 10)

        purchase = _office_purchase(api_client, article, storage, 10)

        assert purchase.day_number == PURCHASE_DAY
        movement = MovementShareArticle.objects.get(purchase=purchase)
        assert movement.date == PURCHASE_NOON
        assert movement.counted_amount == Decimal("10")
        assert _stock(article, storage, _end_of(MONDAY_NOON)) == Decimal("0")
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("10")

    def test_without_a_plan_still_lands_on_purchase_day(
        self, api_client, tenant, article, storage
    ):
        purchase = _office_purchase(api_client, article, storage, 7)

        movement = MovementShareArticle.objects.get(purchase=purchase)
        assert movement.date == PURCHASE_NOON
        assert movement.amount == Decimal("7")

    def test_a_harvest_without_weekday_stays_on_monday(self):
        harvest_day = GenericDocumentationService.movement_day_number(
            None, MovementTypeOptions.HARVEST
        )
        purchase_day = GenericDocumentationService.movement_day_number(
            None, MovementTypeOptions.PURCHASE
        )

        assert (harvest_day, purchase_day) == (0, PURCHASE_DAY)


# Purchase ids are random; these pin which purchase sorts first by source, and so
# carries the plan, in either creation order.
FIRST_ID, LAST_ID = "AAAAAAAAAAAA", "zzzzzzzzzzzz"


def _purchase(article, storage, amount: int, purchase_id: str, day_number=None):
    return GenericDocumentationService.create_purchase_with_related_objects(
        {
            "id": purchase_id,
            "year": YEAR,
            "delivery_week": WEEK,
            "share_article": article,
            "unit": "KG",
            "size": "M",
            "amount": Decimal(amount),
            "storage": storage,
            "seller": ResellerFactory(),
            "day_number": day_number,
        }
    )


def _movement_amounts(*purchases) -> list[Decimal]:
    return [MovementShareArticle.objects.get(purchase=p).amount for p in purchases]


@pytest.mark.django_db
class TestSeveralPurchasesOfADay:
    @pytest.mark.parametrize(
        "ids", [(FIRST_ID, LAST_ID), (LAST_ID, FIRST_ID)], ids=["first", "takeover"]
    )
    @pytest.mark.parametrize(
        "day_number", [None, PURCHASE_DAY], ids=["no-weekday", "purchase-day"]
    )
    def test_replace_the_plan_once(self, tenant, article, storage, ids, day_number):
        _plan(article, storage, 10)

        six = _purchase(article, storage, 6, ids[0], day_number)
        four = _purchase(article, storage, 4, ids[1], day_number)

        carrier, other = (six, four) if six.id == FIRST_ID else (four, six)
        counted = {six.id: Decimal("6"), four.id: Decimal("4")}
        assert _movement_amounts(carrier, other) == [
            counted[carrier.id] - 10,
            counted[other.id],
        ]
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("10")

    def test_the_carrier_stays_the_same_across_edits(
        self, api_client, tenant, article, storage
    ):
        _plan(article, storage, 10)
        carrier = _purchase(article, storage, 6, FIRST_ID)
        other = _purchase(article, storage, 4, LAST_ID)

        for purchase in (other, carrier):
            resp = api_client.patch(
                reverse("purchase-detail", args=[purchase.id]),
                {"note": "edited"},
                format="json",
            )
            assert resp.status_code == status.HTTP_200_OK, resp.data

        assert _movement_amounts(carrier, other) == [Decimal("-4"), Decimal("4")]

    def test_deleting_the_carrier_hands_the_plan_over(
        self, api_client, tenant, article, storage
    ):
        _plan(article, storage, 10)
        carrier = _purchase(article, storage, 6, FIRST_ID)
        other = _purchase(article, storage, 4, LAST_ID)

        resp = api_client.delete(reverse("purchase-detail", args=[carrier.id]))

        assert resp.status_code == status.HTTP_204_NO_CONTENT, resp.data
        assert _movement_amounts(other) == [Decimal("-6")]
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("4")

    @pytest.mark.parametrize("change", ["cleared", "moved"])
    def test_a_carrier_leaving_the_day_hands_the_plan_over(
        self, api_client, tenant, article, storage, change
    ):
        _plan(article, storage, 10)
        carrier = _purchase(article, storage, 6, FIRST_ID)
        other = _purchase(article, storage, 4, LAST_ID)
        body = (
            {"amount": None}
            if change == "cleared"
            else {"storage": str(StorageFactory().id)}
        )

        resp = api_client.patch(
            reverse("purchase-detail", args=[carrier.id]), body, format="json"
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _movement_amounts(other) == [Decimal("-6")]
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("4")


@pytest.mark.django_db
class TestAdditionalAmountOnAnOfficePurchase:
    def test_lands_on_purchase_day_with_the_purchase(
        self, api_client, tenant, article, storage
    ):
        _plan(article, storage, 10)
        purchase = _office_purchase(api_client, article, storage, 12)

        DocumentationSummaryService.update_additional_theoretical_amount(
            {"amount": 2}, pk=purchase.pk, model="Purchase"
        )

        additional = MovementShareArticle.objects.get(
            additional_theoretical_purchase__isnull=False
        )
        assert additional.date == PURCHASE_NOON
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("12")

    def test_editing_it_moves_a_purchase_dated_monday(
        self, api_client, tenant, article, storage
    ):
        _plan(article, storage, 10)
        purchase = _office_purchase(api_client, article, storage, 12)
        # A purchase whose stored movement is on Monday, un-netted.
        MovementShareArticle.objects.filter(purchase=purchase).update(
            date=MONDAY_NOON, amount=Decimal("12")
        )

        DocumentationSummaryService.update_additional_theoretical_amount(
            {"amount": 2}, pk=purchase.pk, model="Purchase"
        )

        movement = MovementShareArticle.objects.get(purchase=purchase)
        assert movement.date == PURCHASE_NOON
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("12")

    @pytest.mark.parametrize("edit", ["purchase-page", "purchase-list-note"])
    def test_an_edit_moves_a_monday_pair_together(
        self, api_client, tenant, article, storage, edit
    ):
        _plan(article, storage, 10)
        purchase = _office_purchase(api_client, article, storage, 12)
        # A purchase stored without a weekday, as the page's used to be.
        Purchase.objects.filter(pk=purchase.pk).update(day_number=None)
        additional = AdditionalTheoreticalPurchaseFactory(
            year=YEAR,
            delivery_week=WEEK,
            day_number=None,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            seller=purchase.seller,
            amount=2,
        )
        # A purchase and its additional amount whose movements are both stored
        # on Monday, netted against each other.
        MovementShareArticle.objects.create(
            date=MONDAY_NOON,
            movement_type=MovementTypeOptions.PURCHASE,
            additional_theoretical_purchase=additional,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
            amount=Decimal("2"),
            is_theoretical=True,
        )
        MovementShareArticle.objects.filter(purchase=purchase).update(
            date=MONDAY_NOON, amount=Decimal("10")
        )

        if edit == "purchase-page":
            resp = api_client.patch(
                reverse("purchase-detail", args=[purchase.id]),
                {"note": "edited"},
                format="json",
            )
            assert resp.status_code == status.HTTP_200_OK, resp.data
        else:
            DocumentationSummaryService.update_additional_theoretical_amount(
                {"note": "edited"}, pk=purchase.pk, model="Purchase"
            )

        dates = set(
            MovementShareArticle.objects.filter(
                Q(purchase=purchase) | Q(additional_theoretical_purchase=additional)
            ).values_list("date", flat=True)
        )
        assert dates == {PURCHASE_NOON}
        assert _stock(article, storage, _end_of(MONDAY_NOON)) == Decimal("0")
        assert _stock(article, storage, _end_of(PURCHASE_NOON)) == Decimal("12")
