"""A share planning row's stock before each delivery day's shares are packed.

It is read at the close of the day before the packing day: the packing day the
week's shares carry, else the delivery day's default, else the delivery day,
a week back when it falls after the delivery day; a share without one is
packed on its delivery day, and shares packed on different days are read
before the first. Over the storages it sums what the packing draws on: a
storage's count, else its calculated stock, nothing below 0. Every row gets it for
every delivery day running in its week whose day before packing is today or
past, from the planning list and from a saved row alike; before that day it
would rest on plans alone. Once an article's harvest of the packing day itself
is entered, that day's harvest movements are added to its storages.

The stock itself comes from the stock service, which answers per day here and
is asked for the rows' articles only.
The clock is frozen on Saturday 14 November 2026, the end of ISO week 46,
unless a test moves it earlier in the week.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.models import Share
from apps.commissioning.services.available_stock import (
    add_available_stock,
    available_stock_key,
)
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    HarvestFactory,
    MovementShareArticleFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    TheoreticalHarvestFactory,
)

WEEK = 46
TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY = 1, 2, 3, 4, 5
STOCK = (
    "apps.commissioning.services.available_stock.StockService"
    ".get_theoretical_current_stock"
)


@pytest.fixture(autouse=True)
def _saturday_of_week_46():
    with time_machine.travel(datetime.datetime(2026, 11, 14, 12, 0), tick=False):
        yield


def _on(day_of_november):
    """The clock moved to that day of November 2026, at noon."""
    return time_machine.travel(
        datetime.datetime(2026, 11, day_of_november, 12, 0), tick=False
    )


def _stock_on(stock_by_day):
    """The stock service answering ``stock_by_day[(year, week, day_index)]``,
    and nothing for any other day."""
    return patch(
        STOCK,
        side_effect=lambda year, delivery_week, day_number, **_scope: (
            stock_by_day.get((year, delivery_week, day_number), {})
        ),
    )


def _in_stock(article, amount, storage="st-cellar", unit="KG", size="M", **values):
    return {
        (article.id, unit, size, storage): {
            "theoretical_current_stock": Decimal(amount),
            "current_stock_amount": None,
            **values,
        }
    }


def _row(article, unit="KG", size="M"):
    return {
        "year": 2026,
        "delivery_week": WEEK,
        "share_article": article.id,
        "unit": unit,
        "size": size,
    }


def _available(day, article, stock_by_day):
    row = _row(article)
    with _stock_on(stock_by_day):
        add_available_stock([row])
    return row[available_stock_key(day.id)]


@pytest.mark.django_db
class TestTheDayTheStockIsReadOn:
    def test_a_day_packed_on_its_delivery_day_reads_the_day_before(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)

        available = _available(
            friday, article, {(2026, WEEK, THURSDAY): _in_stock(article, "12")}
        )

        assert available == 12.0

    def test_a_day_packed_the_day_before_reads_the_day_before_packing(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(
            day_number=FRIDAY, default_packing_day=THURSDAY
        )

        available = _available(
            friday,
            article,
            {
                (2026, WEEK, WEDNESDAY): _in_stock(article, "9"),
                (2026, WEEK, THURSDAY): _in_stock(article, "1"),
            },
        )

        assert available == 9.0

    def test_a_packing_day_after_the_delivery_day_lies_in_the_week_before(self, tenant):
        article = ShareArticleFactory()
        tuesday = SharesDeliveryDayFactory(
            day_number=TUESDAY, default_packing_day=SATURDAY
        )

        available = _available(
            tuesday, article, {(2026, WEEK - 1, FRIDAY): _in_stock(article, "4")}
        )

        assert available == 4.0

    def test_the_weeks_shares_carry_the_packing_day_of_their_own(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        share = ShareFactory(
            year=2026,
            delivery_week=WEEK,
            delivery_day=friday,
            share_type_variation=ShareTypeVariationFactory(),
        )
        share.packing_day = WEDNESDAY
        share.save()

        available = _available(
            friday,
            article,
            {
                (2026, WEEK, TUESDAY): _in_stock(article, "7"),
                (2026, WEEK, THURSDAY): _in_stock(article, "1"),
            },
        )

        assert available == 7.0

    def test_a_share_without_a_packing_day_is_packed_on_its_delivery_day(self, tenant):
        # As the packing movements date it, whatever the day's default says.
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(
            day_number=FRIDAY, default_packing_day=WEDNESDAY
        )
        share = ShareFactory(
            year=2026,
            delivery_week=WEEK,
            delivery_day=friday,
            share_type_variation=ShareTypeVariationFactory(),
        )
        Share.objects.filter(pk=share.pk).update(packing_day=None)

        available = _available(
            friday,
            article,
            {
                (2026, WEEK, TUESDAY): _in_stock(article, "9"),
                (2026, WEEK, THURSDAY): _in_stock(article, "5"),
            },
        )

        assert available == 5.0

    def test_shares_packed_on_different_days_read_before_the_first(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        for packing_day in (THURSDAY, WEDNESDAY):
            share = ShareFactory(
                year=2026,
                delivery_week=WEEK,
                delivery_day=friday,
                share_type_variation=ShareTypeVariationFactory(),
            )
            share.packing_day = packing_day
            share.save()

        available = _available(
            friday,
            article,
            {
                (2026, WEEK, TUESDAY): _in_stock(article, "4"),
                (2026, WEEK, WEDNESDAY): _in_stock(article, "8"),
            },
        )

        assert available == 4.0

    def test_a_day_without_a_default_packing_day_packs_on_its_delivery_day(
        self, tenant
    ):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=None)

        available = _available(
            friday,
            article,
            {
                (2026, WEEK, WEDNESDAY): _in_stock(article, "9"),
                (2026, WEEK, THURSDAY): _in_stock(article, "5"),
            },
        )

        assert available == 5.0


@pytest.mark.django_db
class TestWhenTheStockIsShown:
    def test_not_before_the_day_before_packing(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        row = _row(article)

        # Wednesday: Friday's shares are read on Thursday, still to come.
        with _on(11), _stock_on({}) as stock_service:
            add_available_stock([row])

        assert available_stock_key(friday.id) not in row
        stock_service.assert_not_called()

    def test_from_the_day_before_packing_itself(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)

        with _on(12):
            available = _available(
                friday, article, {(2026, WEEK, THURSDAY): _in_stock(article, "6")}
            )

        assert available == 6.0

    def test_each_day_of_the_week_from_its_own_day_before_packing(self, tenant):
        article = ShareArticleFactory()
        wednesday = SharesDeliveryDayFactory(
            day_number=WEDNESDAY, default_packing_day=WEDNESDAY
        )
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        row = _row(article)

        with _on(11), _stock_on({(2026, WEEK, TUESDAY): _in_stock(article, "20")}):
            add_available_stock([row])

        assert row[available_stock_key(wednesday.id)] == 20.0
        assert available_stock_key(friday.id) not in row


@pytest.mark.django_db
class TestTheStockOfARow:
    def test_sums_the_calculated_stock_of_the_storages(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        stock = {
            **_in_stock(article, "10", storage="st-cellar"),
            **_in_stock(article, "5", storage="st-cold"),
            # Another unit of the same article isn't the row's.
            **_in_stock(article, "50", unit="PCS"),
        }

        available = _available(friday, article, {(2026, WEEK, THURSDAY): stock})

        assert available == 15.0

    def test_takes_each_storage_as_the_packing_draws_on_it(self, tenant):
        # A count stands for its storage's calculated stock; a storage below
        # zero holds nothing to draw on.
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        stock = {
            **_in_stock(article, "10", storage="st-cellar"),
            **_in_stock(
                article, "5", storage="st-cold", current_stock_amount=Decimal("3")
            ),
            **_in_stock(article, "-4", storage="st-field"),
        }

        available = _available(friday, article, {(2026, WEEK, THURSDAY): stock})

        assert available == 13.0

    def test_is_never_below_zero_and_zero_when_nothing_is_in_stock(self, tenant):
        short, missing = ShareArticleFactory(), ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        stock = {(2026, WEEK, THURSDAY): _in_stock(short, "-4")}

        assert _available(friday, short, stock) == 0.0
        assert _available(friday, missing, stock) == 0.0

    def test_every_delivery_day_of_the_week_gets_its_own_reading(self, tenant):
        article = ShareArticleFactory()
        wednesday = SharesDeliveryDayFactory(
            day_number=WEDNESDAY, default_packing_day=WEDNESDAY
        )
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        # Starts after this week, so not one of its days.
        SharesDeliveryDayFactory(
            day_number=SATURDAY, valid_from=datetime.date(2026, 12, 7)
        )
        row = _row(article)

        with _stock_on(
            {
                (2026, WEEK, TUESDAY): _in_stock(article, "20"),
                (2026, WEEK, THURSDAY): _in_stock(article, "6"),
            }
        ):
            add_available_stock([row])

        available = {key: value for key, value in row.items() if "available" in key}
        assert available == {
            available_stock_key(wednesday.id): 20.0,
            available_stock_key(friday.id): 6.0,
        }

    def test_days_packed_on_the_same_day_read_it_once(self, tenant):
        article = ShareArticleFactory()
        SharesDeliveryDayFactory(day_number=THURSDAY, default_packing_day=WEDNESDAY)
        SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=WEDNESDAY)

        with _stock_on({}) as stock_service:
            add_available_stock([_row(article)])

        stock_service.assert_called_once_with(
            year=2026,
            delivery_week=WEEK,
            day_number=TUESDAY,
            entity_filter={"share_article_id": [article.id]},
        )

    def test_the_stock_is_read_for_the_rows_articles_only(self, tenant):
        carrots, beets = ShareArticleFactory(), ShareArticleFactory()
        SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)

        with _stock_on({}) as stock_service:
            add_available_stock([_row(carrots), _row(beets), _row(carrots)])

        assert stock_service.call_args.kwargs["entity_filter"] == {
            "share_article_id": sorted([carrots.id, beets.id])
        }


def _harvest_movement(article, day_of_november, amount, storage, entered):
    """A harvest movement at noon of that day of November 2026: an entered
    harvest's correction, or a planned harvest."""
    documentation = {
        "year": 2026,
        "delivery_week": WEEK,
        "day_number": datetime.date(2026, 11, day_of_november).weekday(),
        "share_article": article,
        "storage": storage,
    }
    source = (
        {"harvest": HarvestFactory(**documentation)}
        if entered
        else {"theoretical_harvest": TheoreticalHarvestFactory(**documentation)}
    )
    return MovementShareArticleFactory(
        date=timezone.make_aware(datetime.datetime(2026, 11, day_of_november, 12, 0)),
        movement_type="HARVEST",
        share_article=article,
        amount=Decimal(amount),
        storage=storage,
        is_theoretical=not entered,
        **source,
    )


@pytest.mark.django_db
class TestTheHarvestOfThePackingDay:
    def test_an_entered_harvest_of_the_packing_day_counts(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        field = StorageFactory(is_short_term_harvest_storage=True)
        # Planned 5 kg on Friday the 13th, entered as 8: the correction is 3.
        _harvest_movement(article, 13, "5", field, entered=False)
        _harvest_movement(article, 13, "3", field, entered=True)
        thursday = {
            **_in_stock(article, "2", storage=field.id),
            **_in_stock(article, "1", storage="st-cellar"),
        }

        available = _available(friday, article, {(2026, WEEK, THURSDAY): thursday})

        assert available == 11.0

    def test_it_adds_to_a_count_of_the_day_before(self, tenant):
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        field = StorageFactory(is_short_term_harvest_storage=True)
        _harvest_movement(article, 13, "4", field, entered=True)
        thursday = _in_stock(
            article, "9", storage=field.id, current_stock_amount=Decimal("3")
        )

        available = _available(friday, article, {(2026, WEEK, THURSDAY): thursday})

        assert available == 7.0

    def test_a_planned_harvest_of_the_packing_day_waits_for_its_entry(self, tenant):
        carrots, beets = ShareArticleFactory(), ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        field = StorageFactory(is_short_term_harvest_storage=True)
        _harvest_movement(carrots, 13, "6", field, entered=True)
        _harvest_movement(beets, 13, "5", field, entered=False)
        row = _row(beets)

        with _stock_on({(2026, WEEK, THURSDAY): _in_stock(beets, "2")}):
            add_available_stock([_row(carrots), row])

        assert row[available_stock_key(friday.id)] == 2.0

    def test_a_harvest_of_another_day_is_left_to_the_reading(self, tenant):
        # Thursday's harvest is in Thursday's stock already.
        article = ShareArticleFactory()
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        field = StorageFactory(is_short_term_harvest_storage=True)
        _harvest_movement(article, 12, "6", field, entered=True)

        available = _available(
            friday, article, {(2026, WEEK, THURSDAY): _in_stock(article, "2")}
        )

        assert available == 2.0


@pytest.mark.django_db
class TestThePlanningRows:
    def _line(self):
        friday = SharesDeliveryDayFactory(day_number=FRIDAY, default_packing_day=FRIDAY)
        station_day = DeliveryStationDayFactory(delivery_day=friday)
        line = ShareContentFactory(
            share=ShareFactory(
                year=2026,
                delivery_week=WEEK,
                delivery_day=friday,
                share_type_variation=ShareTypeVariationFactory(),
            ),
            share_article=ShareArticleFactory(),
            delivery_station=station_day.delivery_station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )
        return friday, line

    def test_the_planning_list_carries_it(self, tenant):
        friday, line = self._line()

        with _stock_on({(2026, WEEK, THURSDAY): _in_stock(line.share_article, "30")}):
            rows = ShareContentService().get_share_content_for_week(
                year=2026,
                delivery_week=WEEK,
                share_option=line.share.share_type_variation.share_type.share_option,
            )

        [row] = [row for row in rows if row["share_article"] == line.share_article_id]
        assert row[available_stock_key(friday.id)] == 30.0

    def test_a_saved_row_carries_it(self, tenant):
        friday, line = self._line()

        with _stock_on({(2026, WEEK, THURSDAY): _in_stock(line.share_article, "30")}):
            row = ShareContentService().get_group_data([line])

        assert row is not None
        assert row[available_stock_key(friday.id)] == 30.0
