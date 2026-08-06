"""Hard constraints — every candidate plan must satisfy all of these.

Ported from the old ``hard_constraints.py``. Several old constraints are now
*implicit* in the interval formulation and need no code:

* ``respect_bed_count``            → the cell interval's fixed size is cell_count.
* ``one_starting_point`` / start   → an interval has exactly one start.
* ``starting_position`` bounds     → the start var's domain keeps it in-plot.
* ``continuous_usage_of_beds``     → the time interval spans the whole window.

What remains is written below.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from ortools.sat.python import cp_model

from . import config
from .loading import (
    BatchInput,
    Blocker,
    Carryover,
    PlotInput,
    fleece_weeks_for,
    occupancy_end_week,
)
from .ranges import coalesce, coalesce_weighted
from .variables import OptimizerVars


def add_all_hard_constraints(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    blockers: list[Blocker],
    carryover: list[Carryover],
    v: OptimizerVars,
) -> None:
    _one_plot_per_batch(model, batches, v)
    _no_overlap_space_time(model, batches, plots, carryover, v)
    _channel_bed_occupancy(model, batches, plots, v)
    _crop_rotation(model, batches, plots, blockers, v)
    if v.settings.enable_planting_line_homogeneity:
        _planting_line_homogeneity(model, batches, plots, v)
    if v.settings.enable_fleece:
        _fleece_coverage(model, batches, plots, v)


def _one_plot_per_batch(
    model: cp_model.CpModel, batches: list[BatchInput], v: OptimizerVars
) -> None:
    for b in range(len(batches)):
        model.AddExactlyOne(v.present[(b, p)] for p in v.options[b])


def _no_overlap_space_time(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    carryover: list[Carryover],
    v: OptimizerVars,
) -> None:
    """No two batches share a cell in the same week, within each plot.

    2-D no-overlap: cells on the x axis, weeks on the y axis. Two batches may
    share cells if their weeks are disjoint (succession) and share weeks if
    their cells are disjoint.

    Cross-year carryover is folded in as FIXED boxes: an overwintering crop from
    last year occupies its cells for weeks ``[1, until_week]`` of this year, so a
    this-year batch overlapping those weeks cannot reuse those cells.

    Those boxes are always-present, so two that overlap would contradict each other
    and make the whole model unsatisfiable — and since every carryover box starts at
    week 1, ANY cell overlap is automatically a 2-D overlap. They are therefore
    coalesced per plot first, keeping the longest occupancy per cell.
    """
    plot_index = {plot.id: p for p, plot in enumerate(plots)}
    by_plot: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for c in carryover:
        p = plot_index.get(c.plot_id)
        if p is None:
            continue  # plot no longer exists / is a greenhouse now
        by_plot[p].append((c.start_cell, c.cell_count, c.until_week))

    carry_boxes: dict[int, list[tuple]] = defaultdict(list)
    for p, raw in by_plot.items():
        for i, (start, count, until) in enumerate(coalesce_weighted(raw)):
            if until < 1:
                continue  # a zero-week box would block nothing
            cell_iv = model.NewFixedSizeIntervalVar(
                start, count, f"carry_cell_p{p}_{i}"
            )
            # weeks [1, until] inclusive -> interval [1, until + 1)
            time_iv = model.NewFixedSizeIntervalVar(1, until, f"carry_time_p{p}_{i}")
            carry_boxes[p].append((cell_iv, time_iv))

    for p in range(len(plots)):
        pairs = [
            (v.cell_interval[(b, p)], v.time_interval[(b, p)])
            for b in range(len(batches))
            if (b, p) in v.cell_interval
        ]
        pairs += carry_boxes.get(p, [])
        if pairs:
            model.AddNoOverlap2D([c for c, _ in pairs], [t for _, t in pairs])


def _channel_bed_occupancy(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> None:
    """Link the placement viewpoint to the per-bed occupancy viewpoint.

    ``start_bed = start // W``, ``end_bed = (start + count - 1) // W``, and
    ``occ[b, p, k] ⟺ present ∧ start_bed ≤ k ≤ end_bed``. Then
    ``bed_used[p, k] = OR_b occ[b, p, k]``.
    """
    width = v.settings.cells_per_bed
    for (b, p), s in v.start.items():
        count = batches[b].cell_count
        model.AddDivisionEquality(v.start_bed[(b, p)], s, width)
        last_cell = model.NewIntVar(
            0, plots[p].cell_capacity - 1, f"last_cell_b{b}_p{p}"
        )
        model.Add(last_cell == s + count - 1)
        model.AddDivisionEquality(v.end_bed[(b, p)], last_cell, width)

        for k in range(v.num_beds[p]):
            occ = v.occ[(b, p, k)]
            ge = model.NewBoolVar(f"ge_b{b}_p{p}_k{k}")  # k >= start_bed
            le = model.NewBoolVar(f"le_b{b}_p{p}_k{k}")  # k <= end_bed
            model.Add(v.start_bed[(b, p)] <= k).OnlyEnforceIf(ge)
            model.Add(v.start_bed[(b, p)] >= k + 1).OnlyEnforceIf(ge.Not())
            model.Add(v.end_bed[(b, p)] >= k).OnlyEnforceIf(le)
            model.Add(v.end_bed[(b, p)] <= k - 1).OnlyEnforceIf(le.Not())
            model.AddBoolAnd([v.present[(b, p)], ge, le]).OnlyEnforceIf(occ)
            model.AddBoolOr(
                [v.present[(b, p)].Not(), ge.Not(), le.Not()]
            ).OnlyEnforceIf(occ.Not())

    for p in range(len(plots)):
        for k in range(v.num_beds[p]):
            members = [
                v.occ[(b, p, k)] for b in range(len(batches)) if (b, p, k) in v.occ
            ]
            if members:
                model.AddMaxEquality(v.bed_used[(p, k)], members)
            else:
                model.Add(v.bed_used[(p, k)] == 0)


def _crop_rotation(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    blockers: list[Blocker],
    v: OptimizerVars,
) -> None:
    """A family never reoccupies a cell within its rotation break.

    Per (plot, family), a 1-D no-overlap on the cell axis over this-year batches
    of that family plus fixed blocker intervals from prior years. Being
    time-independent, it also stops a family doubling up on the same cells within
    a single year.

    History blockers are always-present intervals, so two overlapping ones would be
    a contradiction and the whole year would come back INFEASIBLE — from data that
    is merely duplicated (a chosen plan plus a hand-entered row for the same year),
    legitimately overlapping (intra-year succession of one family), or retroactively
    widened (raising a family's break years pulls two older plans into one window).
    "Blocked" is a property of the ground, so they are coalesced into disjoint runs
    instead of being asked to satisfy each other.
    """
    family_batches: dict[str, list[int]] = defaultdict(list)
    for b, batch in enumerate(batches):
        if batch.family_id is not None:
            family_batches[batch.family_id].append(b)

    plot_index = {plot.id: p for p, plot in enumerate(plots)}
    history: dict[tuple[int, str], list[tuple[int, int]]] = defaultdict(list)
    for blocker in blockers:
        p = plot_index.get(blocker.plot_id)
        if p is None:
            continue  # plot no longer exists / is a greenhouse now
        history[(p, blocker.family_id)].append((blocker.start_cell, blocker.cell_count))

    for p in range(len(plots)):
        for family_id, member_batches in family_batches.items():
            # A 0-year break means the family needs no rotation gap — it may
            # reuse its own cells freely, so skip the no-overlap entirely.
            if batches[member_batches[0]].break_years == 0:
                continue
            intervals = [
                v.cell_interval[(b, p)]
                for b in member_batches
                if (b, p) in v.cell_interval
            ]
            for i, (s0, c0) in enumerate(coalesce(history.get((p, family_id), []))):
                intervals.append(
                    model.NewFixedSizeIntervalVar(
                        s0, c0, f"block_p{p}_f{family_id}_{i}"
                    )
                )
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)


def _time_overlap(a: BatchInput, b: BatchInput, settings) -> bool:
    """Do the two occupancy windows share a week? Uses the wrap-aware end so
    an overwintering crop is compared on the same absolute axis."""
    return a.planting_week <= occupancy_end_week(
        b, settings
    ) and b.planting_week <= occupancy_end_week(a, settings)


def _planting_line_homogeneity(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> None:
    """Within one bed, crops present at the same time share a planting line.

    Two batches with different planting-line counts whose week windows overlap
    may not both occupy the same bed. (Batches whose windows are disjoint can
    share a bed regardless of line — that is succession, not a conflict.)
    """
    for b1, b2 in combinations(range(len(batches)), 2):
        if batches[b1].planting_lines == batches[b2].planting_lines:
            continue
        if not _time_overlap(batches[b1], batches[b2], v.settings):
            continue
        for p in range(len(plots)):
            if (b1, p) not in v.present or (b2, p) not in v.present:
                continue
            for k in range(v.num_beds[p]):
                model.AddBoolOr([v.occ[(b1, p, k)].Not(), v.occ[(b2, p, k)].Not()])


def _fleece_coverage(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> None:
    """Crops needing fleece must be covered by a fleece unit every fleece week.

    A fleece unit is ``FLEECE_WIDTH_IN_BEDS`` consecutive beds wide, starting at
    bed ``f`` (covering beds ``f .. f+width-1``). For each fleece-needing batch,
    each bed it occupies, and each week of its fleece window, at least one fleece
    covering that bed must exist. A plot with fewer than ``width`` beds cannot fit
    any fleece, so a fleece-needing batch is forbidden from it entirely — without
    this it would otherwise be placed there uncovered.
    """
    wide = v.settings.fleece_width_in_beds
    for b, batch in enumerate(batches):
        if batch.fleece_until is None:
            continue
        weeks = fleece_weeks_for(batch, v.settings)
        for p in range(len(plots)):
            if (b, p) not in v.present:
                continue
            if v.num_beds[p] < wide:
                model.Add(v.present[(b, p)] == 0)  # no fleece fits in this plot
                continue
            for k in range(v.num_beds[p]):
                for w in weeks:
                    covers = [
                        v.fleece[(p, w, f)]
                        for f in range(max(0, k - wide + 1), k + 1)
                        if (p, w, f) in v.fleece
                    ]
                    # covers is non-empty whenever num_beds >= width (guarded
                    # above); enforce coverage on every bed the batch occupies.
                    model.AddBoolOr(covers).OnlyEnforceIf(v.occ[(b, p, k)])
