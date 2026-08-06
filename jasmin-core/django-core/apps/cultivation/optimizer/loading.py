"""Load the optimizer's inputs (plots, batches, rotation history) from the DB.

Everything the solver needs is flattened into small frozen dataclasses here, so
the model builder is pure (no ORM access, easy to unit-test with hand-built
inputs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import (
    CultivationBatch,
    CultivationPlanSolutionDetail,
    HistoricalPlanting,
    Plot,
    SolverSettings,
)
from .config import CELLS_PER_BED, DEFAULT_SETTINGS, SolverConfig


@dataclass(frozen=True)
class BedSegment:
    """A plot's block of beds that are all the same :class:`BedType`.

    A plot's cells are numbered continuously across its blocks in ``position``
    order, so a segment is simply a cell range within the plot's existing axis —
    which is what keeps every stored ``start_cell`` meaning the same thing.
    """

    bed_type_id: str
    bed_type_name: str
    start_cell: int
    cell_count: int

    @property
    def end_cell(self) -> int:
        """One past the last cell of the segment."""
        return self.start_cell + self.cell_count


@dataclass(frozen=True)
class PlotInput:
    id: str
    name: str
    cell_capacity: int  # total cells = total beds × cells_per_bed
    # Bed-type blocks in layout order. Empty when the plot has no PlotContent
    # rows, in which case it has no capacity either.
    segments: tuple[BedSegment, ...] = ()


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
    # The bed type this batch was sized against. ``amount_of_beds`` counts beds
    # OF THIS TYPE, so placing it on a different type would silently give it a
    # different area. None means the gardener left it unset = place anywhere.
    bed_type_id: str | None = None


def allowed_start_ranges(batch: BatchInput, plot: PlotInput) -> list[tuple[int, int]]:
    """Inclusive ``[lo, hi]`` start cells at which ``batch`` may begin in ``plot``.

    Empty means the batch cannot go in this plot at all.

    With no ``bed_type_id`` the batch is unconstrained and may start anywhere it
    still fits. With one, it must lie **wholly inside** that bed type's block:
    ``amount_of_beds`` was measured in beds of that type, so a run that spilled
    into the neighbouring block would be part 50 m beds and part 25 m ones and
    would not be the area the gardener planned. Requiring the whole run inside
    one segment falls out of the start bounds — no extra constraint needed.

    ``PlotContent`` is unique per (plot, bed_type), so a bed type appears at most
    once per plot and the result is at most one range; it is returned as a list
    anyway so callers do not depend on that.
    """
    if batch.cell_count <= 0:
        return []
    if batch.bed_type_id is None:
        if batch.cell_count > plot.cell_capacity:
            return []
        return [(0, plot.cell_capacity - batch.cell_count)]
    return [
        (segment.start_cell, segment.end_cell - batch.cell_count)
        for segment in plot.segments
        if segment.bed_type_id == batch.bed_type_id
        and segment.cell_count >= batch.cell_count
    ]


def segment_at(plot: PlotInput, cell: int) -> BedSegment | None:
    """The bed-type block containing ``cell``, or None if out of range."""
    for segment in plot.segments:
        if segment.start_cell <= cell < segment.end_cell:
            return segment
    return None


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
    # Display only — what is holding the ground. The solver ignores it; it exists
    # so the planner grid can draw these blocks from the SAME loader the solver
    # used, rather than a parallel query that could disagree about what is busy.
    label: str = ""


def occupancy_end_week(
    batch: BatchInput, settings: SolverConfig = DEFAULT_SETTINGS
) -> int:
    """Last week the batch occupies its cells, on an absolute axis that unwraps
    overwintering crops.

    ``end_week < planting_week`` means the crop runs past the year boundary (e.g.
    planted week 45, free again week 8 next year). We add ``weeks_per_year`` so
    the interval math sees a positive, correctly-ordered window instead of one
    that collapses to a single week and lets another crop reuse the cells while
    this one is still in the ground.
    """
    end = batch.end_week if settings.end_week_is_inclusive else batch.end_week - 1
    if end < batch.planting_week:
        end += settings.weeks_per_year
    return end


def fleece_end_week(
    batch: BatchInput, settings: SolverConfig = DEFAULT_SETTINGS
) -> int | None:
    """Last week the batch needs fleece, on the same absolute axis as
    :func:`occupancy_end_week`. ``None`` when the crop needs no fleece.

    An autumn-sown crop uncovered in spring has ``fleece_until < planting_week``,
    so the naive ``range(planting_week, fleece_until + 1)`` is EMPTY and the crop
    silently gets no fleece constraint at all — exactly the crops that need
    covering most. Unwrapping past the year boundary fixes that.
    """
    if batch.fleece_until is None:
        return None
    end = batch.fleece_until
    if end < batch.planting_week:
        end += settings.weeks_per_year
    return end


def fleece_weeks_for(
    batch: BatchInput, settings: SolverConfig = DEFAULT_SETTINGS
) -> range:
    """The weeks a batch needs fleece, wrap-aware (empty when it needs none)."""
    end = fleece_end_week(batch, settings)
    if end is None:
        return range(0)
    return range(batch.planting_week, end + 1)


def load_solver_settings() -> SolverConfig:
    """The tenant's effective solver configuration.

    Reads the ``SolverSettings`` singleton (created with the code defaults on
    first access) and freezes it into the dataclass the model builders take.
    ``cells_per_bed`` stays a code constant — it is the grain, not a preference.
    """
    row = SolverSettings.get_active()
    return SolverConfig(
        cells_per_bed=CELLS_PER_BED,
        max_time_seconds=float(row.solver_max_time_seconds),
        workers=row.solver_workers,
        num_solutions=row.default_num_solutions,
        enable_planting_line_homogeneity=row.enable_planting_line_homogeneity,
        enable_fleece=row.enable_fleece,
        enable_line_dispersion=row.enable_line_dispersion,
        weight_plots_used=row.weight_plots_used,
        weight_beds_used=row.weight_beds_used,
        weight_beds_per_batch=row.weight_beds_per_batch,
        weight_compact_span=row.weight_compact_span,
        weight_line_dispersion=row.weight_line_dispersion,
        weight_fleece_count=row.weight_fleece_count,
    )


def plot_segments(plot: Plot, cells_per_bed: int = CELLS_PER_BED) -> list[BedSegment]:
    """A plot's bed-type blocks laid out along its cell axis, in layout order.

    Walks ``contents`` in ``position`` order (the model's ``Meta.ordering``) and
    hands each block the next stretch of cells, so the blocks tile the plot's
    axis exactly and every cell belongs to exactly one bed type.
    """
    segments: list[BedSegment] = []
    cursor = 0
    for content in plot.contents.all():
        count = content.amount * cells_per_bed
        segments.append(
            BedSegment(
                bed_type_id=content.bed_type_id,
                bed_type_name=str(content.bed_type),
                start_cell=cursor,
                cell_count=count,
            )
        )
        cursor += count
    return segments


def load_plots(cells_per_bed: int = CELLS_PER_BED) -> list[PlotInput]:
    """Outdoor plots with their cell capacity and bed-type layout.

    Greenhouse plots are excluded — greenhouse planning is a separate problem
    (mirrors the old solver's ``GWH=False`` filter).
    """
    rows = (
        Plot.objects.filter(is_greenhouse=False)
        .prefetch_related("contents__bed_type")
        .order_by("name")
    )
    plots: list[PlotInput] = []
    for plot in rows:
        segments = plot_segments(plot, cells_per_bed)
        plots.append(
            PlotInput(
                id=plot.pk,
                name=str(plot),
                # Sum of the blocks rather than a separate aggregate, so capacity
                # and layout can never disagree about how big the plot is.
                cell_capacity=sum(segment.cell_count for segment in segments),
                segments=tuple(segments),
            )
        )
    return plots


def load_batches(year: int, cells_per_bed: int = CELLS_PER_BED) -> list[BatchInput]:
    """Finalized OUTDOOR batches for ``year``, sized in cells.

    Greenhouse batches are excluded, mirroring ``load_plots`` skipping greenhouse
    plots — protected cultivation is planned separately, and without this filter
    every tunnel crop would be forced onto an outdoor bed.

    ``cell_count`` rounds ``amount_of_beds × cells_per_bed`` up — a partial bed
    still consumes whole cells.
    """
    qs = (
        CultivationBatch.objects.filter(
            year=year,
            is_final=True,
            is_greenhouse=False,
            amount_of_beds__gt=0,
        )
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
                bed_type_id=batch.used_bed_type_id,
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


def load_carryover(
    year: int, settings: SolverConfig = DEFAULT_SETTINGS
) -> list[Carryover]:
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
    ).select_related("batch__vegetable")
    for detail in details:
        batch = detail.batch
        if batch.end_week >= batch.planting_week:
            continue  # does not wrap into `year`
        until = batch.end_week if settings.end_week_is_inclusive else batch.end_week - 1
        if until >= 1:
            carryover.append(
                Carryover(
                    plot_id=detail.plot_id,
                    start_cell=detail.start_cell,
                    cell_count=detail.cell_count,
                    until_week=until,
                    label=batch.vegetable.name,
                )
            )

    history = HistoricalPlanting.objects.filter(
        year=year - 1, occupied_until_week__isnull=False
    ).select_related("vegetable", "cultivation_break_family")
    for planting in history:
        # Hand-entered history need not name a vegetable; fall back to the
        # rotation family, which it always has.
        label = (
            planting.vegetable.name
            if planting.vegetable
            else planting.cultivation_break_family.name
        )
        carryover.append(
            Carryover(
                plot_id=planting.plot_id,
                start_cell=planting.start_cell,
                cell_count=planting.cell_count,
                until_week=planting.occupied_until_week,
                label=label,
            )
        )
    return carryover
