"""Load the optimizer's inputs (plots, batches, rotation history) from the DB.

Everything the solver needs is flattened into small frozen dataclasses here, so
the model builder is pure (no ORM access, easy to unit-test with hand-built
inputs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django.db.models import Sum

from ..models import (
    CultivationBatch,
    CultivationPlanSolutionDetail,
    HistoricalPlanting,
    Plot,
)
from .config import CELLS_PER_BED, END_WEEK_IS_INCLUSIVE, WEEKS_PER_YEAR


@dataclass(frozen=True)
class PlotInput:
    id: str
    name: str
    cell_capacity: int  # total cells = total beds × cells_per_bed


@dataclass(frozen=True)
class BatchInput:
    id: str
    cell_count: int
    planting_week: int
    end_week: int
    family_id: str | None
    break_years: int
    planting_lines: int
    # Week the fleece comes off; None if this crop needs no fleece.
    fleece_until: int | None


@dataclass(frozen=True)
class Blocker:
    """A cell range a family may not reoccupy this year (rotation history)."""

    plot_id: str
    family_id: str
    start_cell: int
    cell_count: int


@dataclass(frozen=True)
class Carryover:
    """Cells still physically occupied at the START of the planning year by an
    overwintering crop from the previous year — blocked in space AND time for
    weeks ``[1, until_week]`` (unlike a rotation Blocker, which is a whole-year
    family constraint)."""

    plot_id: str
    start_cell: int
    cell_count: int
    until_week: int


def occupancy_end_week(batch: BatchInput) -> int:
    """Last week the batch occupies its cells, on an absolute axis that unwraps
    overwintering crops.

    ``end_week < planting_week`` means the crop runs past the year boundary (e.g.
    planted week 45, free again week 8 next year). We add ``WEEKS_PER_YEAR`` so
    the interval math sees a positive, correctly-ordered window instead of one
    that collapses to a single week and lets another crop reuse the cells while
    this one is still in the ground.
    """
    end = batch.end_week if END_WEEK_IS_INCLUSIVE else batch.end_week - 1
    if end < batch.planting_week:
        end += WEEKS_PER_YEAR
    return end


def load_plots(cells_per_bed: int = CELLS_PER_BED) -> list[PlotInput]:
    """Outdoor plots with their total cell capacity.

    Greenhouse plots are excluded — greenhouse planning is a separate problem
    (mirrors the old solver's ``GWH=False`` filter).
    """
    rows = (
        Plot.objects.filter(is_greenhouse=False)
        .annotate(total_beds=Sum("contents__amount"))
        .order_by("name")
    )
    return [
        PlotInput(
            id=plot.pk,
            name=str(plot),
            cell_capacity=(plot.total_beds or 0) * cells_per_bed,
        )
        for plot in rows
    ]


def load_batches(year: int, cells_per_bed: int = CELLS_PER_BED) -> list[BatchInput]:
    """Finalized batches for ``year``, sized in cells.

    ``cell_count`` rounds ``amount_of_beds × cells_per_bed`` up — a partial bed
    still consumes whole cells.
    """
    qs = (
        CultivationBatch.objects.filter(year=year, is_final=True, amount_of_beds__gt=0)
        .select_related("vegetable__cultivation_break_family")
        .order_by("planting_week", "id")
    )
    batches: list[BatchInput] = []
    for batch in qs:
        family = batch.vegetable.cultivation_break_family
        batches.append(
            BatchInput(
                id=batch.pk,
                cell_count=math.ceil(batch.amount_of_beds * cells_per_bed),
                planting_week=batch.planting_week,
                end_week=batch.end_week,
                family_id=family.pk if family else None,
                break_years=family.cultivation_break_in_years if family else 0,
                planting_lines=batch.planting_lines,
                fleece_until=batch.week_when_fleece_is_removed,
            )
        )
    return batches


def load_blockers(year: int) -> list[Blocker]:
    """Cell ranges reserved by crop rotation from prior years.

    A family planted in year Y blocks its cells for the next
    ``cultivation_break_in_years`` years. Two sources are unioned: prior *chosen*
    plans (the natural source going forward) and hand-entered
    ``HistoricalPlanting`` rows (for farms adopting the system mid-rotation). We
    keep only placements whose block still covers ``year``.
    """
    blockers: list[Blocker] = []

    details = CultivationPlanSolutionDetail.objects.filter(
        solution__chosen=True, solution__year__lt=year
    ).select_related("solution", "batch__vegetable__cultivation_break_family")
    for detail in details:
        family = detail.batch.vegetable.cultivation_break_family
        if family is None:
            continue
        if year - detail.solution.year > family.cultivation_break_in_years:
            continue
        blockers.append(
            Blocker(
                plot_id=detail.plot_id,
                family_id=family.pk,
                start_cell=detail.start_cell,
                cell_count=detail.cell_count,
            )
        )

    history = HistoricalPlanting.objects.filter(year__lt=year).select_related(
        "cultivation_break_family"
    )
    for planting in history:
        family = planting.cultivation_break_family
        if year - planting.year > family.cultivation_break_in_years:
            continue
        blockers.append(
            Blocker(
                plot_id=planting.plot_id,
                family_id=family.pk,
                start_cell=planting.start_cell,
                cell_count=planting.cell_count,
            )
        )
    return blockers


def load_carryover(year: int) -> list[Carryover]:
    """Cells still occupied at the start of ``year`` by an overwintering crop
    from the previous year.

    Two sources: last year's chosen plan (batches whose window wraps the year
    boundary, ``end_week < planting_week``) and hand-entered
    ``HistoricalPlanting`` rows for ``year - 1`` with ``occupied_until_week``
    set. Each blocks its cells for this year's weeks ``[1, until_week]``.
    """
    carryover: list[Carryover] = []

    details = CultivationPlanSolutionDetail.objects.filter(
        solution__chosen=True, solution__year=year - 1
    ).select_related("batch")
    for detail in details:
        batch = detail.batch
        if batch.end_week >= batch.planting_week:
            continue  # does not wrap into `year`
        until = batch.end_week if END_WEEK_IS_INCLUSIVE else batch.end_week - 1
        if until >= 1:
            carryover.append(
                Carryover(
                    plot_id=detail.plot_id,
                    start_cell=detail.start_cell,
                    cell_count=detail.cell_count,
                    until_week=until,
                )
            )

    history = HistoricalPlanting.objects.filter(
        year=year - 1, occupied_until_week__isnull=False
    )
    for planting in history:
        carryover.append(
            Carryover(
                plot_id=planting.plot_id,
                start_cell=planting.start_cell,
                cell_count=planting.cell_count,
                until_week=planting.occupied_until_week,
            )
        )
    return carryover
