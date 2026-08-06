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

from ..errors import BatchDoesNotFit
from . import config
from .config import DEFAULT_SETTINGS, SolverConfig
from .loading import (
    BatchInput,
    PlotInput,
    allowed_start_ranges,
    fleece_weeks_for,
    occupancy_end_week,
)


@dataclass
class OptimizerVars:
    # Effective tunables for this run — carried here so the constraint modules
    # read `v.settings.<field>` instead of module-level constants.
    settings: SolverConfig
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
    """For each batch, the plot indices it fits in. Raises if it fits nowhere.

    "Fits" means there is at least one legal start cell, which for a batch with a
    ``bed_type_id`` means a block of that bed type long enough to hold the whole
    run — not merely a plot with enough cells somewhere.
    """
    options: dict[int, list[int]] = {}
    for b, batch in enumerate(batches):
        fits = [p for p, plot in enumerate(plots) if allowed_start_ranges(batch, plot)]
        if not fits:
            # A domain error rather than ValueError: this is a data problem the
            # office has to fix, and it reaches them through the background job's
            # failure message, so it needs a stable code and a readable sentence.
            if batch.bed_type_id is None:
                raise BatchDoesNotFit(
                    f"Batch {batch.id} needs {batch.cell_count} contiguous cells "
                    f"but no plot is large enough.",
                    details={"batch": batch.id, "cell_count": batch.cell_count},
                )
            raise BatchDoesNotFit(
                f"Batch {batch.id} needs {batch.cell_count} contiguous cells of "
                f"its bed type, but no plot has a block of that bed type that "
                f"long. Either give the plot more beds of that type, or clear the "
                f"batch's bed type to let it go anywhere.",
                details={
                    "batch": batch.id,
                    "cell_count": batch.cell_count,
                    "bed_type": batch.bed_type_id,
                },
            )
        options[b] = fits
    return options


def _start_domain(batch: BatchInput, plot: PlotInput) -> cp_model.Domain:
    """The batch's legal start cells in this plot, as a CP-SAT domain.

    Confining the bed-type rule to the variable's domain — rather than adding
    constraints — means it costs the solver nothing and cannot be contradicted
    later: an illegal start is simply not a value the variable can take.
    """
    return cp_model.Domain.FromIntervals(
        [[lo, hi] for lo, hi in allowed_start_ranges(batch, plot)]
    )


def _time_span(batch: BatchInput, settings: SolverConfig) -> int:
    """Number of weeks the batch occupies its cells (interval size).

    Uses the wrap-aware occupancy end so overwintering crops get their true
    multi-week span instead of collapsing to a single week.
    """
    return occupancy_end_week(batch, settings) - batch.planting_week + 1


def create_variables(
    batches: list[BatchInput],
    plots: list[PlotInput],
    model: cp_model.CpModel,
    settings: SolverConfig = DEFAULT_SETTINGS,
) -> OptimizerVars:
    width = settings.cells_per_bed
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
        span = _time_span(batch, settings)
        for p in options[b]:
            plot = plots[p]
            is_present = model.NewBoolVar(f"present_b{b}_p{p}")
            s = model.NewIntVarFromDomain(
                _start_domain(batch, plot), f"start_b{b}_p{p}"
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
    if settings.enable_fleece:
        fleece_weeks = sorted(
            {w for batch in batches for w in fleece_weeks_for(batch, settings)}
        )
        wide = settings.fleece_width_in_beds
        for p in range(len(plots)):
            for w in fleece_weeks:
                for f in range(max(0, num_beds[p] - wide + 1)):
                    fleece[(p, w, f)] = model.NewBoolVar(f"fleece_p{p}_w{w}_f{f}")

    return OptimizerVars(
        settings=settings,
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
