"""OfferService.create_offers adding the stock set aside for resellers.

The offers add the stock that an INVENTORY row on the offer week's Monday flags
``for_resellers``. StockService hands that stock out as floats and reads it from
the CurrentStockBalance projection when the Monday is today, from the movement
ledger on any other day, so the tests against the real service run on both.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

import pytest
import time_machine
from isoweek import Week

from apps.commissioning.models import Harvest, Offer, Waste
from apps.commissioning.models.choices import MovementTypeOptions
from apps.commissioning.services.documentation_service import (
    GenericDocumentationService,
)
from apps.commissioning.services.inventory_counts import (
    get_or_create_inventory,
    inventory_datetime,
)
from apps.commissioning.services.offer_service import OfferService
from apps.commissioning.services.stock_service import StockService
from apps.commissioning.tests.factories import (
    ForecastFactory,
    MovementShareArticleFactory,
    OfferGroupFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
    StorageFactory,
)

YEAR, WEEK = 2026, 15
MONDAY, FRIDAY = 0, 4


def _offered_article():
    """An article sold to resellers by the 5 KG packing unit, with order prices."""
    article = ShareArticleFactory(
        is_sold_to_resellers=True,
        default_commissioning_unit="KG",
        default_kg_per_pu_reseller=Decimal("5.000"),
    )
    ShareArticleNetPriceFactory(
        share_article=article,
        net_price_for_orders_kg_1=Decimal("3.00"),
        net_price_for_orders_kg_2=Decimal("2.50"),
        net_price_for_orders_kg_3=Decimal("2.00"),
    )
    return article


def _forecast_for_resellers(article, amount):
    ForecastFactory(
        share_article=article,
        year=YEAR,
        delivery_week=WEEK,
        for_all_resellers=True,
        amount=amount,
        unit="KG",
        size="M",
    )


def _book_on_the_friday_before(model_class, article, storage, amount):
    """Record a harvest or a waste through the documentation service, which
    writes its movement and refreshes the snapshots and the current balance."""
    week_before = Week(YEAR, WEEK) - 1
    GenericDocumentationService.create_with_related_objects(
        model_class,
        {
            "year": week_before.year,
            "delivery_week": week_before.week,
            "day_number": FRIDAY,
            "share_article": article,
            "storage": storage,
            "unit": "KG",
            "size": "M",
            "amount": amount,
            "note": "",
        },
    )


def _count_on_monday(article, storage, counted):
    """The office counts the stock on Monday and sets it aside for resellers."""
    get_or_create_inventory(
        {
            "year": YEAR,
            "delivery_week": WEEK,
            "day_number": MONDAY,
            "share_article_id": article.id,
            "unit": "KG",
            "size": "M",
            "storage_id": storage.id,
        },
        {"amount": counted, "for_resellers": True},
    )


def _set_aside_uncounted_on_monday(article, storage):
    """The stock page's flag without a count: a zero-delta INVENTORY row that
    leaves the stock uncounted."""
    MovementShareArticleFactory(
        movement_type=MovementTypeOptions.INVENTORY,
        date=inventory_datetime(YEAR, WEEK, MONDAY),
        share_article=article,
        storage=storage,
        unit="KG",
        size="M",
        amount=Decimal("0"),
        counted_amount=None,
        for_resellers=True,
    )


def _monday_stock(article, storage):
    """The (theoretical, counted) pair StockService reports for Monday."""
    row = StockService.get_theoretical_current_stock(YEAR, WEEK, MONDAY)[
        (article.id, "KG", "M", storage.id)
    ]
    return row["theoretical_current_stock"], row["current_stock_amount"]


def _offer_amount(article, offer_group):
    return Offer.objects.get(share_article=article, offer_group=offer_group).amount


@pytest.fixture(params=["projection", "ledger"])
def stock_read_path(request, tenant):
    """Freeze the clock on the offer week's Monday, where StockService reads the
    projection, or two days later, where it sums the ledger."""
    monday = Week(YEAR, WEEK).monday()
    wednesday = monday + datetime.timedelta(days=2)
    today = monday if request.param == "projection" else wednesday
    with time_machine.travel(
        datetime.datetime.combine(today, datetime.time(12, 0)), tick=False
    ):
        yield request.param


@pytest.mark.django_db
@pytest.mark.usefixtures("stock_read_path")
class TestCreateOffersAddsResellerStock:
    def test_the_clock_picks_the_read_path(self, stock_read_path):
        with mock.patch.object(
            StockService,
            "_current_stock_from_projection",
            wraps=StockService._current_stock_from_projection,
        ) as projection:
            StockService.get_theoretical_current_stock(YEAR, WEEK, MONDAY)

        assert projection.called is (stock_read_path == "projection")

    def test_counted_stock_is_offered(self):
        article = _offered_article()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        group = OfferGroupFactory()
        _forecast_for_resellers(article, amount=20)
        _book_on_the_friday_before(Harvest, article, storage, Decimal("30"))
        _count_on_monday(article, storage, Decimal("25"))
        assert _monday_stock(article, storage) == (30.0, 25.0)

        result = OfferService.create_offers(YEAR, WEEK)

        assert result["created_count"] >= 1
        # (20 KG forecast + the 25 KG counted) / 5 KG per packing unit — not the
        # 30 KG the books expected before the count.
        assert _offer_amount(article, group) == Decimal("9")

    def test_uncounted_stock_set_aside_offers_its_expected_balance(self):
        article = _offered_article()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        group = OfferGroupFactory()
        _forecast_for_resellers(article, amount=20)
        _book_on_the_friday_before(Harvest, article, storage, Decimal("30"))
        _set_aside_uncounted_on_monday(article, storage)
        assert _monday_stock(article, storage) == (30.0, None)

        OfferService.create_offers(YEAR, WEEK)

        # (20 KG forecast + 30 KG expected) / 5 KG per packing unit
        assert _offer_amount(article, group) == Decimal("10")

    def test_a_deficit_does_not_shrink_the_offer(self):
        article = _offered_article()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        group = OfferGroupFactory()
        _forecast_for_resellers(article, amount=20)
        # Waste booked from a storage that holds nothing on the books.
        _book_on_the_friday_before(Waste, article, storage, Decimal("10"))
        _set_aside_uncounted_on_monday(article, storage)
        assert _monday_stock(article, storage) == (-10.0, None)

        OfferService.create_offers(YEAR, WEEK)

        # 20 KG forecast / 5 KG per packing unit, not (20 − 10) / 5
        assert _offer_amount(article, group) == Decimal("4")


def _stock_row(*, theoretical, counted=None, for_resellers=True):
    """One StockService row, with the floats it hands out."""
    return {
        "theoretical_current_stock": theoretical,
        "current_stock_amount": counted,
        "for_resellers": for_resellers,
    }


@pytest.mark.django_db
class TestResellerStockAcrossStorages:
    def test_each_storage_gives_its_count_or_balance_but_never_a_deficit(self, tenant):
        article = _offered_article()
        group = OfferGroupFactory()
        _forecast_for_resellers(article, amount=20)
        entity = (article.id, "KG", "M")
        stock_map = {
            (*entity, "cold-store"): _stock_row(theoretical=30.0, counted=25.0),
            (*entity, "cellar"): _stock_row(theoretical=7.5),
            (*entity, "harvest-store"): _stock_row(theoretical=-10.0),
            (*entity, "shed"): _stock_row(theoretical=99.0, for_resellers=False),
        }

        with mock.patch.object(
            StockService, "get_theoretical_current_stock", return_value=stock_map
        ):
            OfferService.create_offers(YEAR, WEEK)

        # (20 KG forecast + 25 KG counted + 7.5 KG expected) / 5 KG per packing
        # unit; the deficit and the stock kept back from resellers add nothing.
        assert _offer_amount(article, group) == Decimal("10.5")
