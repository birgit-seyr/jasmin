"""What a share planning row's article has in stock just before each delivery
day's shares are packed.

The stock is read at the close of the day before the packing day. The planned
harvests, purchases and packing of the days before count in it, and an entered
harvest or count takes the place of the planned amount, so the figure is only
as right as those entries. A day packed on its delivery day reads the day
before the delivery. Before that day has come the reading would rest on plans
alone, so it is left out until then.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone
from isoweek import Week

from ..models import Share, SharesDeliveryDay
from ..models.managers import active_on_date_q
from ..utils.iso_week_utils import (
    StockCoordinates,
    compute_rolled_back_week,
    previous_day_stock_coordinates,
    saturday_of_iso_week,
)
from .movements import allocatable_amount
from .stock_service import StockService

# (share article id, unit, size) → stock.
StockByArticle = dict[tuple[str, str | None, str | None], Decimal]


def available_stock_key(delivery_day_id: str) -> str:
    """The planning row's key of a delivery day's available stock."""
    return f"day_{delivery_day_id}_available_stock"


def add_available_stock(rows: list[dict[str, Any]]) -> None:
    """Give each row, for every delivery day of its week whose day before
    packing is today or past, its article's stock in the row's unit and size
    before the day's shares are packed, summed over the storages as the
    packing allocation draws on them (``allocatable_amount``)."""
    for year, week in {(row["year"], row["delivery_week"]) for row in rows}:
        week_rows = [
            row for row in rows if (row["year"], row["delivery_week"]) == (year, week)
        ]
        stock_by_day = _stock_before_packing(
            year, week, sorted({str(row["share_article"]) for row in week_rows})
        )
        for row in week_rows:
            article = (str(row["share_article"]), row["unit"], row["size"])
            for day_id, stock in stock_by_day.items():
                row[available_stock_key(day_id)] = float(
                    stock.get(article, Decimal("0"))
                )


def _stock_before_packing(
    year: int, week: int, article_ids: list[str]
) -> dict[str, StockByArticle]:
    """The stock of ``article_ids`` before packing of each delivery day running
    in the week whose day before packing has come, by the day's id."""
    today = timezone.localdate()
    days = list(
        SharesDeliveryDay.objects.filter(
            active_on_date_q(saturday_of_iso_week(year, week))
        )
    )
    packing_days_of: defaultdict[str, set[int | None]] = defaultdict(set)
    for day_id, packing_day in (
        Share.objects.filter(year=year, delivery_week=week, delivery_day__in=days)
        .values_list("delivery_day_id", "packing_day")
        .distinct()
    ):
        packing_days_of[day_id].add(packing_day)

    stock_by_date: dict[StockCoordinates, StockByArticle] = {}
    stock_by_day: dict[str, StockByArticle] = {}
    for day in days:
        packing_date = _packing_date(day, packing_days_of[day.id], year, week)
        if packing_date - timedelta(days=1) > today:
            continue
        before_packing = previous_day_stock_coordinates(packing_date)
        if before_packing not in stock_by_date:
            # Scoped to the rows' articles: away from today the reading walks
            # the movements, and a saved row asks for its one article.
            stock_by_date[before_packing] = _stock_by_article(
                StockService.get_theoretical_current_stock(
                    year=before_packing.year,
                    delivery_week=before_packing.week,
                    day_number=before_packing.day_index,
                    entity_filter={"share_article_id": article_ids},
                )
            )
        stock_by_day[str(day.id)] = stock_by_date[before_packing]
    return stock_by_day


def _packing_date(
    day: SharesDeliveryDay, packing_days: set[int | None], year: int, week: int
) -> date:
    """When the day's shares of the week are packed, as the packing movements
    date it: a share's own packing day, or its delivery day where it carries
    none, a week back when it falls after the delivery day. Shares packed on
    different days are read before the first of them; a week without shares
    goes by the day's default."""
    if packing_days:
        candidates = {
            packing_day if packing_day is not None else day.day_number
            for packing_day in packing_days
        }
    elif day.default_packing_day is not None:
        candidates = {day.default_packing_day}
    else:
        candidates = {day.day_number}
    dates = []
    for packing_day in candidates:
        packing_year, packing_week = compute_rolled_back_week(
            year, week, packing_day, day.day_number
        )
        dates.append(Week(packing_year, packing_week).day(packing_day))
    return min(dates)


def _stock_by_article(stock_data: dict[tuple, dict]) -> StockByArticle:
    """The stock of each (article, unit, size) over its storages: what each
    holds for the packing to draw on, a storage with nothing or less counting
    nothing."""
    totals: defaultdict[tuple[str, str | None, str | None], Decimal] = defaultdict(
        Decimal
    )
    for (article_id, unit, size, _storage), values in stock_data.items():
        amount = allocatable_amount(values)
        if amount is not None:
            totals[(str(article_id), unit, size)] += Decimal(str(amount))
    return dict(totals)
