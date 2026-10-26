"""How good is a plan? Comparable numbers for one candidate solution.

The trick to judging placements: **the work is fixed**. Every candidate plans the
same batches for the same weeks, so "how much did we plant" (``planted_cell_weeks``)
is identical across solutions and says nothing. What differs is how much
*land-time the plan had to open* to fit that same work in.

So the headline number is waste: a bed is "open" in a week if any of its cells are
used that week, which costs you the whole bed for that week — path, irrigation,
cultivation, the lot. Cells left empty inside an open bed are the loss.

    wasted_cell_weeks = bed_weeks_opened × cells_per_bed − planted_cell_weeks
    efficiency        = planted_cell_weeks / (bed_weeks_opened × cells_per_bed)

Lower waste (higher efficiency) is a tighter plan. Because the numerator is
constant, ranking by efficiency is the same as ranking by bed-weeks opened — one
number that captures compactness in space *and* in time.
"""

from __future__ import annotations

from collections import defaultdict

from ..constants import CELLS_PER_BED
from ..models import CultivationPlanSolution

# ISO weeks in a planning year. A crop that overwinters is counted here only up
# to year end; its remainder belongs to next year's plan (as carryover), and
# double-counting it would overstate this year's usage.
_WEEKS = 52


def _weeks_in_plan_year(planting_week: int, end_week: int) -> range:
    """The weeks this batch holds ground *within its own planning year*."""
    if end_week >= planting_week:
        return range(planting_week, min(end_week, _WEEKS) + 1)
    return range(planting_week, _WEEKS + 1)


def solution_metrics(solution: CultivationPlanSolution) -> dict:
    """Quality numbers for one candidate plan. Safe on an empty plan."""
    width = solution.cells_per_bed or CELLS_PER_BED

    planted_cell_weeks = 0
    # week -> plot -> set of beds touched that week
    open_beds: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    week_cells: dict[int, int] = defaultdict(int)
    beds_touched: set[tuple[str, int]] = set()
    crops_per_bed: dict[tuple[str, int], int] = defaultdict(int)
    plots_used: set[str] = set()

    for detail in solution.details.select_related("batch").all():
        batch = detail.batch
        weeks = _weeks_in_plan_year(batch.planting_week, batch.end_week)
        span = len(weeks)
        if span == 0:
            continue
        plots_used.add(detail.plot_id)
        planted_cell_weeks += detail.cell_count * span

        cells = range(detail.start_cell, detail.start_cell + detail.cell_count)
        beds = {cell // width for cell in cells}
        for bed in beds:
            beds_touched.add((detail.plot_id, bed))
            crops_per_bed[(detail.plot_id, bed)] += 1
        for week in weeks:
            week_cells[week] += detail.cell_count
            open_beds[week][detail.plot_id].update(beds)

    bed_weeks_opened = sum(
        len(beds) for plots in open_beds.values() for beds in plots.values()
    )
    capacity_cell_weeks = bed_weeks_opened * width
    wasted = max(capacity_cell_weeks - planted_cell_weeks, 0)
    efficiency = (
        round(planted_cell_weeks / capacity_cell_weeks * 100, 1)
        if capacity_cell_weeks
        else 0.0
    )
    peak_week, peak_cells = (
        max(week_cells.items(), key=lambda kv: kv[1]) if week_cells else (0, 0)
    )
    # A bed hosting N crops across the season delivers N-1 successions.
    successions = sum(max(n - 1, 0) for n in crops_per_bed.values())

    return {
        "planted_cell_weeks": planted_cell_weeks,
        "bed_weeks_opened": bed_weeks_opened,
        "wasted_cell_weeks": wasted,
        "efficiency_percent": efficiency,
        "plots_used": len(plots_used),
        "beds_touched": len(beds_touched),
        "peak_week": peak_week,
        "peak_cells_used": peak_cells,
        "successions": successions,
    }
