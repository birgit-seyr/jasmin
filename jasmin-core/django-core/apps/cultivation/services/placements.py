"""Manual (gardener-driven) edits to a plan's placements.

The solver can never capture every real-world constraint, so the office/gardener
must be able to move a batch by hand and store the result. This module validates
only what the ground itself forbids — running past the end of a plot, two crops
occupying the same cell in the same week, or a batch landing on beds of a type it
was not sized for — and deliberately allows agronomic overrides (e.g. bending a
rotation break), because the gardener is the authority on those.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django.db import transaction

from ..constants import CELLS_PER_BED
from ..errors import (
    BatchPlacedTwice,
    BedTypeMismatch,
    PlacementOutOfBounds,
    PlacementOverlaps,
)
from ..models import (
    CultivationBatch,
    CultivationPlanSolution,
    CultivationPlanSolutionDetail,
    Plot,
)
from ..optimizer.config import DEFAULT_SETTINGS
from ..optimizer.loading import (
    BatchInput,
    PlotInput,
    allowed_start_ranges,
    occupancy_end_week,
    plot_segments,
    segment_at,
)


@dataclass(frozen=True)
class ProposedPlacement:
    batch_id: str
    plot_id: str
    start_cell: int


def _plots(cells_per_bed: int) -> dict[str, PlotInput]:
    """Every plot with its capacity and bed-type layout, keyed by id.

    Built through the optimizer's own loader so a hand placement is judged
    against exactly the geometry the solver used — two implementations of "which
    cells are which bed type" would eventually disagree.
    """
    rows = Plot.objects.prefetch_related("contents__bed_type")
    plots: dict[str, PlotInput] = {}
    for plot in rows:
        segments = plot_segments(plot, cells_per_bed)
        plots[plot.pk] = PlotInput(
            id=plot.pk,
            name=str(plot),
            cell_capacity=sum(segment.cell_count for segment in segments),
            segments=tuple(segments),
        )
    return plots


def _window(batch: CultivationBatch) -> tuple[int, int]:
    """Absolute [first, last] occupied week, unwrapping overwintering crops so
    the comparison matches what the solver enforces."""
    stub = BatchInput(
        id=batch.pk,
        cell_count=0,
        planting_week=batch.planting_week,
        end_week=batch.end_week,
        family_id=None,
        break_years=0,
        planting_lines=batch.planting_lines,
        fleece_until=None,
    )
    return batch.planting_week, occupancy_end_week(stub, DEFAULT_SETTINGS)


def _batch_input(batch: CultivationBatch, cell_count: int) -> BatchInput:
    """The batch as the optimizer's loader would have built it, for reusing
    :func:`allowed_start_ranges` on the manual-edit path."""
    return BatchInput(
        id=batch.pk,
        cell_count=cell_count,
        planting_week=batch.planting_week,
        end_week=batch.end_week,
        family_id=None,
        break_years=0,
        planting_lines=batch.planting_lines,
        fleece_until=None,
        bed_type_id=batch.used_bed_type_id,
    )


def _weeks_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _cells_overlap(s1: int, c1: int, s2: int, c2: int) -> bool:
    return s1 < s2 + c2 and s2 < s1 + c1


def _check_bed_type(
    placement: ProposedPlacement,
    batch: CultivationBatch,
    plot: PlotInput,
    cell_count: int,
) -> None:
    """Reject a hand placement that lands the batch on the wrong bed type.

    Physically impossible in the sense that matters here: the beds it would sit
    on are not the beds it was sized for, so the plan claims an area the ground
    does not have. Batches with no ``used_bed_type`` are unconstrained.
    """
    if batch.used_bed_type_id is None:
        return
    ranges = allowed_start_ranges(_batch_input(batch, cell_count), plot)
    if any(lo <= placement.start_cell <= hi for lo, hi in ranges):
        return

    wanted = str(batch.used_bed_type)
    landed = segment_at(plot, placement.start_cell)
    if not ranges:
        detail = (
            f"{plot.name} has no block of {wanted} with {cell_count} "
            f"contiguous cells."
        )
    elif landed is not None and landed.bed_type_id != batch.used_bed_type_id:
        detail = f"cell {placement.start_cell} is {landed.bed_type_name}, not {wanted}."
    else:
        detail = f"the run would cross out of the {wanted} block into the next one."
    raise BedTypeMismatch(
        f"{batch.vegetable.name} is planned in beds of {wanted}, but {detail}",
        field="start_cell",
        details={
            "batch": batch.pk,
            "bed_type": batch.used_bed_type_id,
            "allowed_start_ranges": [list(r) for r in ranges],
        },
    )


@transaction.atomic
def save_placements(
    solution: CultivationPlanSolution,
    placements: list[ProposedPlacement],
) -> list[CultivationPlanSolutionDetail]:
    """Replace ``solution``'s placements with ``placements``.

    Raises :class:`PlacementOutOfBounds`, :class:`BedTypeMismatch` or
    :class:`PlacementOverlaps` — the cases the ground itself rules out — and
    otherwise persists exactly what was sent. A batch omitted from the list is
    simply unplaced (the planner's "park it on the left" state).
    """
    # A crop holds ONE position for its whole week window, so a batch may appear
    # at most once. Without this the collision check below would wave through a
    # batch listed twice at different cells (it overlaps itself in time, but not
    # in space), storing the same crop in two places at once.
    seen: set[str] = set()
    for placement in placements:
        if placement.batch_id in seen:
            raise BatchPlacedTwice(
                "A batch can only be placed once — it holds its cells for its "
                "whole growing period.",
                field="placements",
                details={"batch": placement.batch_id},
            )
        seen.add(placement.batch_id)

    cells_per_bed = solution.cells_per_bed or CELLS_PER_BED
    plots = _plots(cells_per_bed)
    batches = {
        b.pk: b
        for b in CultivationBatch.objects.filter(
            pk__in=[p.batch_id for p in placements]
        ).select_related("used_bed_type", "vegetable")
    }

    resolved = []
    for placement in placements:
        batch = batches.get(placement.batch_id)
        if batch is None:
            raise PlacementOutOfBounds(
                f"Unknown batch {placement.batch_id}.", field="batch"
            )
        # Same sizing rule as the solver (load_batches): a partial bed consumes
        # whole cells. amount_of_beds is nullable — treat "unset" as one cell.
        cell_count = (
            math.ceil(batch.amount_of_beds * cells_per_bed)
            if batch.amount_of_beds
            else 1
        )
        plot = plots.get(placement.plot_id)
        if plot is None:
            raise PlacementOutOfBounds(
                f"Unknown plot {placement.plot_id}.", field="plot"
            )
        capacity = plot.cell_capacity
        if placement.start_cell < 0 or placement.start_cell + cell_count > capacity:
            raise PlacementOutOfBounds(
                f"Batch needs cells {placement.start_cell}–"
                f"{placement.start_cell + cell_count - 1} but the plot has "
                f"{capacity} cells.",
                field="start_cell",
                details={"capacity": capacity, "cell_count": cell_count},
            )
        _check_bed_type(placement, batch, plot, cell_count)
        resolved.append((placement, batch, cell_count, _window(batch)))

    # Physical collision check: same plot, overlapping weeks, overlapping cells.
    for i in range(len(resolved)):
        p1, b1, c1, w1 = resolved[i]
        for j in range(i + 1, len(resolved)):
            p2, b2, c2, w2 = resolved[j]
            if p1.plot_id != p2.plot_id:
                continue
            if not _weeks_overlap(w1, w2):
                continue
            if _cells_overlap(p1.start_cell, c1, p2.start_cell, c2):
                raise PlacementOverlaps(
                    f"{b1.vegetable.name} and {b2.vegetable.name} would share "
                    f"cells during weeks {max(w1[0], w2[0])}–{min(w1[1], w2[1])}.",
                    details={"batches": [b1.pk, b2.pk]},
                )

    solution.details.all().delete()
    return CultivationPlanSolutionDetail.objects.bulk_create(
        CultivationPlanSolutionDetail(
            solution=solution,
            batch_id=placement.batch_id,
            plot_id=placement.plot_id,
            start_cell=placement.start_cell,
            cell_count=cell_count,
        )
        for placement, _batch, cell_count, _window in resolved
    )


@transaction.atomic
def choose_solution(solution: CultivationPlanSolution) -> CultivationPlanSolution:
    """Mark ``solution`` as the chosen plan for its year, unsetting any other.

    Explicit (no signal, no save() override) so the partial-unique constraint
    ``one_chosen_solution_per_year`` is a guarantee rather than the mechanism.
    """
    CultivationPlanSolution.objects.filter(year=solution.year, chosen=True).exclude(
        pk=solution.pk
    ).update(chosen=False)
    solution.chosen = True
    solution.save(update_fields=["chosen"])
    return solution
