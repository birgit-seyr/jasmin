"""What a share planning row's article has in stock just before each delivery
day's shares are packed.

The stock is read at the close of the day before the packing day. The planned
harvests, purchases and packing of the days before count in it, and an entered
harvest or count takes the place of the planned amount, so the figure is only
as right as those entries. A day packed on its delivery day reads the day
before the delivery. Before that day has come the reading would rest on plans
alone, so it is left out until then.

An article harvested on the packing day itself, before the packing, has its
harvest of that day added once one of them is entered: the harvest movements
of the day, planned and entered, which net to what was entered. The packing
day's other movements stay out, its packing above all.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone
from isoweek import Week

from ..models import MovementShareArticle, Share, SharesDeliveryDay
from ..models.choices import MovementTypeOptions
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
# (share article id, unit, size, storage id) → amount.
AmountByStorage = dict[tuple[str, str | None, str | None, str | None], Decimal]


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

    stock_by_date: dict[StockCoordinates, dict[tuple, dict]] = {}
    readings: dict[str, tuple[date, StockCoordinates]] = {}
    for day in days:
        packing_date = _packing_date(day, packing_days_of[day.id], year, week)
        if packing_date - timedelta(days=1) > today:
            continue
        before_packing = previous_day_stock_coordinates(packing_date)
        if before_packing not in stock_by_date:
            # Scoped to the rows' articles: away from today the reading walks
            # the movements, and a saved row asks for its one article.
            stock_by_date[before_packing] = StockService.get_theoretical_current_stock(
                year=before_packing.year,
                delivery_week=before_packing.week,
                day_number=before_packing.day_index,
                entity_filter={"share_article_id": article_ids},
            )
        readings[str(day.id)] = (packing_date, before_packing)

    harvests_by_date = _entered_packing_day_harvests(
        {packing_date for packing_date, _ in readings.values()}, article_ids
    )
    return {
        day_id: _stock_by_article(
            stock_by_date[before_packing], harvests_by_date.get(packing_date, {})
        )
        for day_id, (packing_date, before_packing) in readings.items()
    }


def _entered_packing_day_harvests(
    packing_dates: set[date], article_ids: list[str]
) -> dict[date, AmountByStorage]:
    """The harvest movements on each packing date, by storage, of every
    (article, unit, size) whose harvest of that date has been entered."""
    if not packing_dates:
        return {}
    amounts: defaultdict[tuple[date, tuple], AmountByStorage] = defaultdict(dict)
    entered: set[tuple[date, tuple]] = set()
    for (
        moment,
        article_id,
        unit,
        size,
        storage_id,
        amount,
        harvest_id,
    ) in MovementShareArticle.objects.filter(
        movement_type=MovementTypeOptions.HARVEST,
        share_article_id__in=article_ids,
        date__date__in=packing_dates,
    ).values_list(
        "date", "share_article_id", "unit", "size", "storage_id", "amount", "harvest_id"
    ):
        article = (str(article_id), unit, size)
        day_article = (timezone.localtime(moment).date(), article)
        storage_key = (*article, str(storage_id) if storage_id else None)
        by_storage = amounts[day_article]
        by_storage[storage_key] = by_storage.get(storage_key, Decimal("0")) + amount
        if harvest_id is not None:
            entered.add(day_article)

    harvests_by_date: defaultdict[date, AmountByStorage] = defaultdict(dict)
    for day_article in entered:
        harvests_by_date[day_article[0]].update(amounts[day_article])
    return dict(harvests_by_date)


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


def _stock_by_article(
    stock_data: dict[tuple, dict], harvests: AmountByStorage
) -> StockByArticle:
    """The stock of each (article, unit, size) over its storages, each with
    the ``harvests`` it takes in on the packing day: what each holds for the
    packing to draw on, a storage with nothing or less counting nothing."""
    storages: dict[tuple, Mapping[str, Any]] = dict(stock_data)
    for storage_key, amount in harvests.items():
        storages[storage_key] = _with_harvest(storages.get(storage_key, {}), amount)

    totals: defaultdict[tuple[str, str | None, str | None], Decimal] = defaultdict(
        Decimal
    )
    for (article_id, unit, size, _storage), values in storages.items():
        available = allocatable_amount(values)
        if available is not None:
            totals[(str(article_id), unit, size)] += Decimal(str(available))
    return dict(totals)


def _with_harvest(values: Mapping[str, Any], amount: Decimal) -> dict[str, Any]:
    """A storage's reading with ``amount`` harvested into it, its count of the
    day before included where it has one."""
    counted = values.get("current_stock_amount")
    return {
        "theoretical_current_stock": (
            Decimal(str(values.get("theoretical_current_stock") or 0)) + amount
        ),
        "current_stock_amount": (
            None if counted is None else Decimal(str(counted)) + amount
        ),
    }
