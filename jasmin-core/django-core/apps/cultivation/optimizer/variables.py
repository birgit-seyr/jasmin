"""Create every CP-SAT variable the model uses.

Two viewpoints are created here and *channeled* together in
:mod:`hard_constraints`:

* the **placement** viewpoint — per (batch, plot) interval vars (start cell +
  fixed size on the space axis, fixed week window on the time axis). Contiguity
  and within-plot bounds are implicit in an interval var.
* the **per-bed occupancy** viewpoint — ``occ[b, p, k]`` (batch b touches bed k
  of plot p) and ``bed_used[p, k]`` (any batch does). The old boolean grid had
  this for free; the interval model has to derive it, which is what lets the
  bed-level constraints (planting-line homogeneity, fleece, bed counting,
  compactness) carry over.

Optional fleece placement vars are created only when ``config.ENABLE_FLEECE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from . import config
from .loading import BatchInput, PlotInput, occupancy_end_week


@dataclass
class OptimizerVars:
    # placement viewpoint
    present: dict[tuple[int, int], cp_model.IntVar]
    start: dict[tuple[int, int], cp_model.IntVar]
    cell_interval: dict[tuple[int, int], cp_model.IntervalVar]
    time_interval: dict[tuple[int, int], cp_model.IntervalVar]
    # bed viewpoint (channeled in hard_constraints)
    start_bed: dict[tuple[int, int], cp_model.IntVar]
    end_bed: dict[tuple[int, int], cp_model.IntVar]
    occ: dict[tuple[int, int, int], cp_model.IntVar]
    bed_used: dict[tuple[int, int], cp_model.IntVar]
    # fleece (empty unless ENABLE_FLEECE)
    fleece: dict[tuple[int, int, int], cp_model.IntVar]
    fleece_weeks: list[int]
    # geometry
    num_beds: list[int]
    options: dict[int, list[int]]
    # objective handles (filled by soft_constraints)
    plot_used: dict[int, cp_model.IntVar] = field(default_factory=dict)


def batch_plot_options(
    batches: list[BatchInput], plots: list[PlotInput]
) -> dict[int, list[int]]:
    """For each batch, the plot indices it fits in. Raises if it fits nowhere."""
    options: dict[int, list[int]] = {}
    for b, batch in enumerate(batches):
        fits = [
            p for p, plot in enumerate(plots) if batch.cell_count <= plot.cell_capacity
        ]
        if not fits:
            raise ValueError(
                f"Batch {batch.id} needs {batch.cell_count} cells but no plot "
                f"is large enough."
            )
        options[b] = fits
    return options


def _time_span(batch: BatchInput) -> int:
    """Number of weeks the batch occupies its cells (interval size).

    Uses the wrap-aware occupancy end so overwintering crops get their true
    multi-week span instead of collapsing to a single week.
    """
    return occupancy_end_week(batch) - batch.planting_week + 1


def create_variables(
    batches: list[BatchInput], plots: list[PlotInput], model: cp_model.CpModel
) -> OptimizerVars:
    width = config.CELLS_PER_BED
    num_beds = [plot.cell_capacity // width for plot in plots]
    options = batch_plot_options(batches, plots)

    present: dict[tuple[int, int], cp_model.IntVar] = {}
    start: dict[tuple[int, int], cp_model.IntVar] = {}
    cell_interval: dict[tuple[int, int], cp_model.IntervalVar] = {}
    time_interval: dict[tuple[int, int], cp_model.IntervalVar] = {}
    start_bed: dict[tuple[int, int], cp_model.IntVar] = {}
    end_bed: dict[tuple[int, int], cp_model.IntVar] = {}
    occ: dict[tuple[int, int, int], cp_model.IntVar] = {}

    for b, batch in enumerate(batches):
        span = _time_span(batch)
        for p in options[b]:
            plot = plots[p]
            is_present = model.NewBoolVar(f"present_b{b}_p{p}")
            s = model.NewIntVar(
                0, plot.cell_capacity - batch.cell_count, f"start_b{b}_p{p}"
            )
            present[(b, p)] = is_present
            start[(b, p)] = s
            cell_interval[(b, p)] = model.NewOptionalFixedSizeIntervalVar(
                s, batch.cell_count, is_present, f"cell_b{b}_p{p}"
            )
            time_interval[(b, p)] = model.NewOptionalFixedSizeIntervalVar(
                batch.planting_week, span, is_present, f"time_b{b}_p{p}"
            )
            start_bed[(b, p)] = model.NewIntVar(
                0, num_beds[p] - 1, f"start_bed_b{b}_p{p}"
            )
            end_bed[(b, p)] = model.NewIntVar(0, num_beds[p] - 1, f"end_bed_b{b}_p{p}")
            for k in range(num_beds[p]):
                occ[(b, p, k)] = model.NewBoolVar(f"occ_b{b}_p{p}_k{k}")

    bed_used: dict[tuple[int, int], cp_model.IntVar] = {}
    for p in range(len(plots)):
        for k in range(num_beds[p]):
            bed_used[(p, k)] = model.NewBoolVar(f"bed_used_p{p}_k{k}")

    fleece: dict[tuple[int, int, int], cp_model.IntVar] = {}
    fleece_weeks: list[int] = []
    if config.ENABLE_FLEECE:
        fleece_weeks = sorted(
            {
                w
                for batch in batches
                if batch.fleece_until is not None
                for w in range(batch.planting_week, batch.fleece_until + 1)
            }
        )
        wide = config.FLEECE_WIDTH_IN_BEDS
        for p in range(len(plots)):
            for w in fleece_weeks:
                for f in range(max(0, num_beds[p] - wide + 1)):
                    fleece[(p, w, f)] = model.NewBoolVar(f"fleece_p{p}_w{w}_f{f}")

    return OptimizerVars(
        present=present,
        start=start,
        cell_interval=cell_interval,
        time_interval=time_interval,
        start_bed=start_bed,
        end_bed=end_bed,
        occ=occ,
        bed_used=bed_used,
        fleece=fleece,
        fleece_weeks=fleece_weeks,
        num_beds=num_beds,
        options=options,
    )
