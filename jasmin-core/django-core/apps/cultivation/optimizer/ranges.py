"""Cell-range normalisation for history facts.

Rotation blockers and cross-year carryover describe what *already happened*. They
enter the model as always-present fixed intervals, so if two of them overlap the
model is unsatisfiable before a single batch is considered — the whole year yields
no plan.

Overlap is not exotic. It arises from perfectly ordinary data:

* the same year recorded twice (a chosen plan **and** a hand-entered
  ``HistoricalPlanting`` row for documentation — ``load_blockers`` unions both);
* legitimate intra-year succession (spring kohlrabi on beds 0-4, autumn cabbage on
  beds 2-6 — both brassicas, one rotation family);
* widening a family's ``cultivation_break_in_years`` after the fact, which pulls
  two older plans into the same window even though each was legal when solved.

So these ranges are coalesced into disjoint runs before they become constraints:
"blocked" is a property of the ground, and unioning it can never lose information.
"""

from __future__ import annotations

from collections.abc import Iterable

# (start_cell, cell_count)
Range = tuple[int, int]
# (start_cell, cell_count, weight) — weight is "occupied until week N"
WeightedRange = tuple[int, int, int]


def coalesce(ranges: Iterable[Range]) -> list[Range]:
    """Merge overlapping or touching ranges into disjoint maximal runs.

    >>> coalesce([(0, 25), (15, 25)])
    [(0, 40)]
    >>> coalesce([(0, 5), (5, 5)])
    [(0, 10)]
    >>> coalesce([(0, 5), (10, 5)])
    [(0, 5), (10, 5)]
    """
    merged: list[list[int]] = []
    for start, count in sorted(ranges):
        if count <= 0:
            continue
        if merged and start <= merged[-1][0] + merged[-1][1]:
            end = max(merged[-1][0] + merged[-1][1], start + count)
            merged[-1][1] = end - merged[-1][0]
        else:
            merged.append([start, count])
    return [(start, count) for start, count in merged]


def coalesce_weighted(ranges: Iterable[WeightedRange]) -> list[WeightedRange]:
    """Flatten ranges that carry a weight into disjoint runs, each keeping the
    MAX weight of the sources covering it.

    Used for carryover, where the weight is "still occupied until week N": if two
    records disagree about how long a cell is busy, the longer one is the safe
    (and physically correct) answer. Segments only merge when their weight is
    equal, so a genuine step in occupancy is preserved.

    >>> coalesce_weighted([(0, 10, 8), (5, 10, 12)])
    [(0, 5, 8), (5, 10, 12)]
    >>> coalesce_weighted([(0, 5, 8), (0, 5, 8)])
    [(0, 5, 8)]
    """
    items = [(s, c, w) for s, c, w in ranges if c > 0]
    if not items:
        return []

    boundaries = sorted(
        {p for start, count, _ in items for p in (start, start + count)}
    )
    out: list[list[int]] = []
    for low, high in zip(boundaries, boundaries[1:], strict=False):
        covering = [w for s, c, w in items if s <= low and s + c >= high]
        if not covering:
            continue
        weight = max(covering)
        if out and out[-1][0] + out[-1][1] == low and out[-1][2] == weight:
            out[-1][1] = high - out[-1][0]
        else:
            out.append([low, high - low, weight])
    return [(start, count, weight) for start, count, weight in out]
