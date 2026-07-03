"""Reusable ISO-week date/datetime helpers."""

from __future__ import annotations

import datetime as _dt
from typing import NamedTuple

from django.utils import timezone
from isoweek import Week


def week_day_to_date(year: int, week: int, day_index: int) -> _dt.date:
    """Convert (ISO year, ISO week, day index 0=Mon…6=Sun) to a calendar date."""
    return Week(year, week).day(day_index)


def delivery_date_from_fields(
    year: int | None,
    delivery_week: int | None,
    changed_day_number: int | None,
    delivery_day_number: int | None,
) -> _dt.date | None:
    """Core of :func:`share_delivery_date`, taking the raw Share fields.

    Callers that fetched a Share via ``.values(...)`` — to avoid instantiating
    full model instances in a hot loop — resolve the date through this instead
    of the duck-typed variant, keeping one implementation of the day-priority
    rule. Day priority: explicit ``changed_day_number`` override ->
    SharesDeliveryDay ``day_number`` -> Monday. The index is a 0=Mon…6=Sun
    DayNumberOptions value (``week_day_to_date`` raises on out-of-range).
    """
    if year is None or delivery_week is None:
        return None
    day_idx = changed_day_number
    if day_idx is None:
        day_idx = delivery_day_number
    if day_idx is None:
        day_idx = 0
    try:
        return week_day_to_date(year, delivery_week, day_idx)
    except (ValueError, TypeError):
        return None


def share_delivery_date(share_delivery) -> _dt.date | None:
    """Resolve the calendar date a ShareDelivery actually happens on.

    Reads the linked Share's ISO ``(year, week)`` plus a day index — an
    explicit ``changed_day_number`` if set, else the delivery_day's
    ``day_number``, defaulting to Monday. Returns ``None`` for a malformed
    Share row. Duck-typed on ``share_delivery`` so this stays a pure date
    helper with no model import. Single source for the optin, cancellation
    and billing-regen flows (previously duplicated in optin_service and
    payments.services).
    """
    share = share_delivery.share
    if share is None:
        return None
    delivery_day = getattr(share, "delivery_day", None)
    return delivery_date_from_fields(
        share.year,
        share.delivery_week,
        share.changed_day_number,
        getattr(delivery_day, "day_number", None),
    )


class StockCoordinates(NamedTuple):
    """A stock lookup key: ISO ``year``/``week`` plus a 0=Mon…6=Sun ``day_index``."""

    year: int
    week: int
    day_index: int


def previous_day_stock_coordinates(reference_date: _dt.date) -> StockCoordinates:
    """Stock coordinates for the calendar day immediately *before* ``reference_date``.

    Theoretical stock for a given day is read from the close of the prior
    day, so callers consistently need the previous day's ISO coordinates in
    the project's 0=Mon…6=Sun ``day_number`` convention. ``isocalendar``
    yields weekday 1=Mon…7=Sun, hence the ``- 1``; subtracting one calendar
    day first lets it roll the result back across week and year boundaries.
    """
    iso = (reference_date - _dt.timedelta(days=1)).isocalendar()
    return StockCoordinates(year=iso[0], week=iso[1], day_index=iso[2] - 1)


def date_from_order(order) -> _dt.date:
    """Return the calendar date for an order's ``(year, delivery_week, day_number)``.

    Falls back to today when ``order`` is ``None`` or its ``day_number`` is
    missing (treated as Monday). Used by tax-rate resolvers and other
    Order-keyed lookups that previously inlined this same 3-line pattern.
    """
    if order is None:
        return timezone.now().date()
    day_index = order.day_number if order.day_number is not None else 0
    return week_day_to_date(order.year, order.delivery_week, day_index)


def coerce_document_date(
    raw,
    *,
    fallback_date: _dt.date | None = None,
    fallback_order=None,
) -> _dt.date | None:
    """Resolve a user-supplied document date.

    Accepts a ``date``/``datetime``, an ISO ``YYYY-MM-DD`` string, or an
    empty/``None`` value. Falls back to ``fallback_date`` (e.g. the
    delivery note's date), then to the order's ``(year, delivery_week,
    day)`` via :func:`week_day_to_date`. Returns ``None`` only as a last
    resort. ``DeliveryNoteReseller.save`` / ``InvoiceReseller.save``
    refuse to persist a document with ``date=None`` and raise
    ``DocumentDateRequired`` — callers should treat a ``None`` return
    here as a sign that something upstream is mis-wired.
    """
    if isinstance(raw, _dt.datetime):
        return raw.date()
    if isinstance(raw, _dt.date):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return _dt.date.fromisoformat(raw.strip())
        except ValueError:
            pass
    if fallback_date:
        return fallback_date
    if (
        fallback_order is not None
        and getattr(fallback_order, "year", None)
        and getattr(fallback_order, "delivery_week", None)
        and getattr(fallback_order, "day_number", None) is not None
    ):
        try:
            return week_day_to_date(
                fallback_order.year,
                fallback_order.delivery_week,
                fallback_order.day_number,
            )
        except (ValueError, TypeError):
            # week_day_to_date raises ValueError on out-of-range week/day_number
            # and TypeError on None / wrong-type inputs; everything else (e.g.
            # an unexpected attribute miss) should bubble up.
            pass
    return None


def saturday_of_iso_week(year: int, week: int) -> _dt.date:
    """Return the Saturday of the given ISO week."""
    return Week(year, week).saturday()


def compute_rolled_back_week(
    year: int, delivery_week: int, activity_day: int, delivery_day: int
) -> tuple[int, int]:
    """Return (year, week) for an activity that may fall before the delivery day.

    If ``activity_day > delivery_day`` the activity belongs to the previous
    ISO week.  The rollback is done via ``isoweek.Week`` so it correctly
    handles year boundaries (e.g. week 1 → last week of previous year).
    """
    if activity_day > delivery_day:
        prev = Week(year, delivery_week) - 1
        return prev.year, prev.week
    return year, delivery_week


def make_noon_datetime(year: int, week: int, day: int) -> _dt.datetime:
    """Return an aware datetime at noon on the given ISO year/week/day."""
    dt = _dt.datetime.combine(Week(year, week).day(day), _dt.time(12, 0))
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def next_iso_week(year: int, week: int) -> tuple[int, int]:
    """ISO ``(year, week)`` immediately after ``(year, week)``, rolling
    correctly across 52/53-week year boundaries (via ``isoweek.Week``)."""
    nxt = Week(year, week) + 1
    return nxt.year, nxt.week


def iso_week_range(year: int, start_week: int, num_weeks: int) -> list[tuple[int, int]]:
    """``num_weeks`` consecutive ISO ``(year, week)`` pairs starting at
    ``(year, start_week)`` inclusive, rolling across year boundaries."""
    start = Week(year, start_week)
    return [((start + i).year, (start + i).week) for i in range(num_weeks)]


def next_monday(d: _dt.date) -> _dt.date:
    """Snap forward to the next Monday (returns ``d`` unchanged if already Monday).

    The project invariant is that ``valid_from`` dates are always Mondays."""
    return d + _dt.timedelta(days=(0 - d.weekday()) % 7)


def next_sunday(d: _dt.date) -> _dt.date:
    """Snap forward to the next Sunday (returns ``d`` unchanged if already Sunday).

    Cancellation / ``valid_until`` effective dates are always Sundays."""
    return d + _dt.timedelta(days=(6 - d.weekday()) % 7)


def previous_monday(d: _dt.date) -> _dt.date:
    """Snap back to the Monday of ``d``'s ISO week (unchanged if already Monday)."""
    return d - _dt.timedelta(days=d.weekday())
