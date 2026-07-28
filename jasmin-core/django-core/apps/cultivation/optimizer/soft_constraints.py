"""Soft constraints — the objective the solver minimises.

Ported from the old ``soft_constraints.py``. ``minimize_blocks_used`` is dropped
(blocks no longer exist — a block was "just a modulo inside the plot"). The old
per-week pairwise ``minimize_planting_line_dispersion`` is reformulated as a
safe per-line gap penalty (see :func:`_line_dispersion`) — the literal per-week
version tied to the boolean grid could not carry over without risking
infeasibility.

The real objective ("optimal of what") is still open — these weighted terms are
a reasonable placeholder. Each ``_minimize_*`` returns a list of weighted terms;
:func:`add_all_soft_constraints` sums them into a single ``model.Minimize``.
"""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from . import config
from .loading import BatchInput, PlotInput
from .variables import OptimizerVars


def add_all_soft_constraints(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> None:
    terms: list = []
    terms += _minimize_plots_used(model, batches, plots, v)
    terms += _minimize_beds_used(plots, v)
    terms += _minimize_beds_per_batch(v)
    terms += _minimize_compact_span(model, plots, v)
    if config.ENABLE_LINE_DISPERSION:
        terms += _line_dispersion(model, batches, plots, v)
    if config.ENABLE_FLEECE:
        terms += _minimize_fleece_count(v)
    model.Minimize(sum(terms))


def _minimize_plots_used(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> list:
    """Consolidate the plan onto as few plots as possible."""
    terms = []
    for p in range(len(plots)):
        used = model.NewBoolVar(f"plot_used_{p}")
        members = [
            v.present[(b, p)] for b in range(len(batches)) if (b, p) in v.present
        ]
        if members:
            model.AddMaxEquality(used, members)
        else:
            model.Add(used == 0)
        v.plot_used[p] = used
        terms.append(config.WEIGHT_PLOTS_USED * used)
    return terms


def _minimize_beds_used(plots: list[PlotInput], v: OptimizerVars) -> list:
    """Fewer distinct beds across the whole season — rewards succession (reusing
    a bed for sequential crops)."""
    return [
        config.WEIGHT_BEDS_USED * v.bed_used[(p, k)]
        for p in range(len(plots))
        for k in range(v.num_beds[p])
    ]


def _minimize_beds_per_batch(v: OptimizerVars) -> list:
    """Keep each batch bed-aligned — the fewer beds it spans, the better (an
    unaligned start straddles an extra bed). Sum of occupancy incidences."""
    return [config.WEIGHT_BEDS_PER_BATCH * occ for occ in v.occ.values()]


def _gap_penalty(
    model: cp_model.CpModel, used: list[cp_model.IntVar], prefix: str
) -> cp_model.IntVar:
    """``span - count`` over a sequence of bed-used bools: the number of unused
    beds wedged between the first and last used one (0 if none/contiguous)."""
    n = len(used)
    big = n + 1
    any_used = model.NewBoolVar(f"{prefix}_any")
    model.AddMaxEquality(any_used, used)
    last = model.NewIntVar(0, n, f"{prefix}_last")
    model.AddMaxEquality(last, [(k + 1) * used[k] for k in range(n)])
    first = model.NewIntVar(0, big, f"{prefix}_first")
    model.AddMinEquality(first, [big + (k + 1 - big) * used[k] for k in range(n)])
    span = model.NewIntVar(0, n, f"{prefix}_span")
    model.Add(span == last - first + 1).OnlyEnforceIf(any_used)
    model.Add(span == 0).OnlyEnforceIf(any_used.Not())
    count = model.NewIntVar(0, n, f"{prefix}_count")
    model.Add(count == sum(used))
    wasted = model.NewIntVar(0, n, f"{prefix}_wasted")
    model.Add(wasted == span - count)
    return wasted


def _minimize_compact_span(
    model: cp_model.CpModel, plots: list[PlotInput], v: OptimizerVars
) -> list:
    """No gaps between the first and last used bed of each plot."""
    terms = []
    for p in range(len(plots)):
        if v.num_beds[p] == 0:
            continue
        used = [v.bed_used[(p, k)] for k in range(v.num_beds[p])]
        wasted = _gap_penalty(model, used, f"compact_p{p}")
        terms.append(config.WEIGHT_COMPACT_SPAN * wasted)
    return terms


def _line_dispersion(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> list:
    """Keep beds sharing a planting line grouped together.

    Reformulation of the old pairwise per-week dispersion: for each plot and each
    planting-line value, penalise gaps between the beds that line occupies. Safe
    (no infeasibility) because it reads occupancy rather than pinning a single
    line onto each bed, so a bed hosting different-line crops in succession is
    fine.
    """
    by_line: dict[int, list[int]] = defaultdict(list)
    for b, batch in enumerate(batches):
        by_line[batch.planting_lines].append(b)

    terms = []
    for p in range(len(plots)):
        nb = v.num_beds[p]
        if nb == 0:
            continue
        for line, member_batches in by_line.items():
            line_used = []
            for k in range(nb):
                members = [
                    v.occ[(b, p, k)] for b in member_batches if (b, p, k) in v.occ
                ]
                used = model.NewBoolVar(f"lineused_p{p}_l{line}_k{k}")
                if members:
                    model.AddMaxEquality(used, members)
                else:
                    model.Add(used == 0)
                line_used.append(used)
            wasted = _gap_penalty(model, line_used, f"line_p{p}_l{line}")
            terms.append(config.WEIGHT_LINE_DISPERSION * wasted)
    return terms


def _minimize_fleece_count(v: OptimizerVars) -> list:
    """Minimise the number of fleece-weeks used."""
    return [config.WEIGHT_FLEECE_COUNT * fleece for fleece in v.fleece.values()]
