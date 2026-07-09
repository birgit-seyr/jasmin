"""Shared capacity-window parsing + ``capacity_by_week`` dict building.

The delivery-station-day and the share-type-variation capacity serializers
expose the SAME ``{"<year>-<week>": {occupied, free}}`` surface over the SAME
``year`` / ``delivery_week`` / ``num_weeks`` query window. Both the window
parsing and the per-week ``{occupied, free}`` assembly live here so the two
axes can't drift apart on the wire.

The only real difference is the capacity nullability: a delivery station-day may
have no capacity limit (``free`` is then ``None``), whereas a variation always
carries a numeric cap — parameterized via ``capacity_nullable``.
"""

from __future__ import annotations

from typing import Any

from .query_params import validate_query_params


def parse_capacity_window(request) -> tuple[int | None, int | None, int]:
    """Resolve ``(year, start_week, num_weeks)`` from a request's query params.

    Returns ``(None, None, 52)`` when there's no request, or when ``year`` /
    ``delivery_week`` aren't both present — the serializers read that as "no
    capacity window on the request" and emit ``None``. ``num_weeks`` defaults to
    52 (its catalogue default). Validates via the central query-param catalogue,
    so a malformed value is a clean 400, not a 500.
    """
    if not request:
        return None, None, 52
    parsed = validate_query_params(
        request,
        optional=["year", "delivery_week", "num_weeks"],
    )
    year = parsed["year"]
    start_week = parsed["delivery_week"]
    num_weeks = parsed["num_weeks"]
    if year is not None and start_week is not None:
        return year, start_week, num_weeks
    return None, None, 52


def build_capacity_by_week(
    year_weeks: list[tuple[int, int]],
    counts: dict[tuple[str, int, int], int],
    obj_id: str,
    capacity: int | None,
    *,
    capacity_nullable: bool = False,
) -> dict[str, dict[str, int | None]]:
    """Assemble the ``{"<year>-<week>": {occupied, free}}`` map for one object.

    ``counts`` is the batched occupancy keyed by ``(obj_id, year, week)``;
    missing keys read as 0. ``free`` is ``max(0, capacity - occupied)``.

    When ``capacity_nullable`` is set (delivery station-days, which may have no
    limit), a ``None`` capacity yields ``free = None`` instead. Variations always
    carry a numeric cap, so they leave it off (the default) — matching each
    serializer's existing behaviour exactly.
    """
    result: dict[str, dict[str, Any]] = {}
    for current_year, week in year_weeks:
        occupied = counts.get((obj_id, current_year, week), 0)
        if capacity_nullable and capacity is None:
            free: int | None = None
        else:
            free = max(0, capacity - occupied)
        result[f"{current_year}-{week}"] = {"occupied": occupied, "free": free}
    return result
