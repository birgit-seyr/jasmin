"""The weekly market price list: the week before, and copying prices into the
next week."""

from __future__ import annotations

from functools import reduce
from operator import or_

from django.db import transaction
from django.db.models import Q
from isoweek import Week

from ..models import MarketPrice


def previous_week_prices(year: int, delivery_week: int) -> dict[str, MarketPrice]:
    """The prices of the ISO week before ``year`` / ``delivery_week``, by PLU
    (``market_article_id``)."""
    previous = Week(year, delivery_week) - 1
    prices = MarketPrice.objects.filter(year=previous.year, delivery_week=previous.week)
    return {price.market_article_id: price for price in prices}


def previous_week_price(price: MarketPrice) -> MarketPrice | None:
    """The price of the same PLU in the ISO week before ``price``'s."""
    previous = Week(price.year, price.delivery_week) - 1
    return MarketPrice.objects.filter(
        market_article_id=price.market_article_id,
        year=previous.year,
        delivery_week=previous.week,
    ).first()


def set_active(price_ids: list[str], is_active: bool) -> None:
    """Put the given prices on sale or take them off it."""
    MarketPrice.objects.filter(id__in=price_ids).update(is_active=is_active)


@transaction.atomic
def copy_to_next_week(price_ids: list[str]) -> dict:
    """Copy the given prices into the ISO week after their own. A PLU that
    already has a price in that week keeps it, and the copy is skipped."""
    prices = list(MarketPrice.objects.filter(id__in=price_ids))
    targets = {price.pk: Week(price.year, price.delivery_week) + 1 for price in prices}
    taken = set()
    if prices:
        weeks = {(week.year, week.week) for week in targets.values()}
        taken = set(
            MarketPrice.objects.filter(
                reduce(
                    or_,
                    (Q(year=year, delivery_week=week) for year, week in weeks),
                ),
                market_article_id__in={price.market_article_id for price in prices},
            ).values_list("market_article_id", "year", "delivery_week")
        )

    copies = []
    for price in prices:
        target = targets[price.pk]
        key = (price.market_article_id, target.year, target.week)
        if key in taken:
            continue
        taken.add(key)
        copies.append(
            MarketPrice(
                year=target.year,
                delivery_week=target.week,
                market_article_id=price.market_article_id,
                gross_price=price.gross_price,
                origin=price.origin,
                is_active=price.is_active,
            )
        )
    MarketPrice.objects.bulk_create(copies)
    return {
        "total_requested": len(price_ids),
        "total_copied": len(copies),
        "skipped_count": len(prices) - len(copies),
    }
