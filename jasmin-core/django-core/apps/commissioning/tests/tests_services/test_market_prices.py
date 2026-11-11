"""The weekly market price list: the week before and copying into the next
week, across the turn of a 53-week ISO year (2020 has a week 53)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.models import MarketPrice
from apps.commissioning.services.market_prices import (
    copy_to_next_week,
    previous_week_price,
    previous_week_prices,
)
from apps.commissioning.tests.factories import (
    MarketArticleFactory,
    MarketPriceFactory,
)


@pytest.mark.django_db
class TestPreviousWeek:
    def test_week_one_follows_week_53(self, tenant):
        """The week before 2021-W01 is 2020-W53, not 2020-W52."""
        plu = MarketArticleFactory()
        week_53 = MarketPriceFactory(market_article=plu, year=2020, delivery_week=53)
        MarketPriceFactory(market_article=plu, year=2020, delivery_week=52)
        current = MarketPriceFactory(market_article=plu, year=2021, delivery_week=1)

        assert previous_week_prices(2021, 1) == {plu.pk: week_53}
        assert previous_week_price(current) == week_53

    def test_no_price_the_week_before(self, tenant):
        current = MarketPriceFactory(year=2025, delivery_week=10)

        assert previous_week_prices(2025, 10) == {}
        assert previous_week_price(current) is None


@pytest.mark.django_db
class TestCopyToNextWeek:
    def test_copies_price_origin_and_flag_into_the_next_week(self, tenant):
        source = MarketPriceFactory(
            year=2020,
            delivery_week=53,
            gross_price=Decimal("3.49"),
            origin="ES",
            is_active=False,
        )

        result = copy_to_next_week([source.pk])

        copy = MarketPrice.objects.get(year=2021, delivery_week=1)
        assert result == {"total_requested": 1, "total_copied": 1, "skipped_count": 0}
        assert copy.market_article_id == source.market_article_id
        assert copy.gross_price == Decimal("3.49")
        assert copy.origin == "ES"
        assert copy.is_active is False

    def test_a_price_already_in_the_next_week_stays(self, tenant):
        source = MarketPriceFactory(gross_price=Decimal("2.00"))
        kept = MarketPriceFactory(
            market_article=source.market_article,
            delivery_week=source.delivery_week + 1,
            gross_price=Decimal("2.50"),
        )
        other = MarketPriceFactory()

        result = copy_to_next_week([source.pk, other.pk])

        kept.refresh_from_db()
        assert result == {"total_requested": 2, "total_copied": 1, "skipped_count": 1}
        assert kept.gross_price == Decimal("2.50")
        assert MarketPrice.objects.filter(
            market_article=other.market_article, delivery_week=other.delivery_week + 1
        ).exists()

    def test_one_plu_from_two_weeks_is_copied_once_per_target(self, tenant):
        plu = MarketArticleFactory()
        earlier = MarketPriceFactory(market_article=plu, delivery_week=10)
        later = MarketPriceFactory(market_article=plu, delivery_week=11)

        result = copy_to_next_week([earlier.pk, later.pk])

        # Week 11 already holds ``later``, so only week 12 gets a copy.
        assert result["total_copied"] == 1
        assert MarketPrice.objects.filter(market_article=plu).count() == 3

    def test_unknown_ids_copy_nothing(self, tenant):
        result = copy_to_next_week(["missing"])

        assert result == {"total_requested": 1, "total_copied": 0, "skipped_count": 0}
