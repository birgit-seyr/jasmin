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

**Terms are normalised.** Raw counts differ by orders of magnitude — "plots used"
tops out at the number of plots (say 4) while "beds used" tops out at the number
of beds (say 100). Multiplying those by the raw weights made the numbers in the
UI misleading: weight 100 on plots contributed at most 400, weight 10 on beds up
to 1000, so the *smaller* weight dominated. Each term is therefore scaled by its
own maximum, so its contribution lands in ``0..weight × _OBJECTIVE_SCALE`` and a
weight of 100 really is ten times a weight of 10.
"""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from . import config
from .loading import BatchInput, PlotInput
from .variables import OptimizerVars

# Resolution of a normalised term. Big enough that dividing by a term's maximum
# still leaves a meaningful integer coefficient (CP-SAT objectives are integral).
_OBJECTIVE_SCALE = 10_000


def _coefficient(weight: int, max_count: int) -> int:
    """Per-variable coefficient that caps a term's total at ``weight × SCALE``.

    Floors at 1 for an enabled term (weight > 0): a term whose maximum exceeds
    ``weight × SCALE`` would otherwise round to a 0 coefficient and silently
    vanish, which is the wrong way to fail — better slightly over-weighted than
    silently ignored.
    """
    if weight <= 0 or max_count <= 0:
        return 0
    return max(1, (weight * _OBJECTIVE_SCALE) // max_count)


def add_all_soft_constraints(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> None:
    terms: list = []
    terms += _minimize_plots_used(model, batches, plots, v)
    terms += _minimize_beds_used(plots, v)
    terms += _minimize_beds_per_batch(batches, v)
    terms += _minimize_compact_span(model, plots, v)
    if v.settings.enable_line_dispersion:
        terms += _line_dispersion(model, batches, plots, v)
    if v.settings.enable_fleece:
        terms += _minimize_fleece_count(v)
    model.Minimize(sum(terms))


def _minimize_plots_used(
    model: cp_model.CpModel,
    batches: list[BatchInput],
    plots: list[PlotInput],
    v: OptimizerVars,
) -> list:
    """Consolidate the plan onto as few plots as possible."""
    coefficient = _coefficient(v.settings.weight_plots_used, len(plots))
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
        terms.append(coefficient * used)
    return terms


def _minimize_beds_used(plots: list[PlotInput], v: OptimizerVars) -> list:
    """Fewer distinct beds across the whole season — rewards succession (reusing
    a bed for sequential crops)."""
    coefficient = _coefficient(v.settings.weight_beds_used, sum(v.num_beds))
    return [
        coefficient * v.bed_used[(p, k)]
        for p in range(len(plots))
        for k in range(v.num_beds[p])
    ]


def _minimize_beds_per_batch(batches: list[BatchInput], v: OptimizerVars) -> list:
    """Keep each batch bed-aligned — the fewer beds it spans, the better (an
    unaligned start straddles an extra bed). Sum of occupancy incidences.

    Normalised against the beds a batch can actually span (its own width plus the
    one extra bed an unaligned start straddles), NOT the number of occ variables
    — most of those are zero because a batch sits in one plot.
    """
    width = v.settings.cells_per_bed
    max_incidences = sum(-(-b.cell_count // width) + 1 for b in batches)
    coefficient = _coefficient(v.settings.weight_beds_per_batch, max_incidences)
    return [coefficient * occ for occ in v.occ.values()]


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
    coefficient = _coefficient(v.settings.weight_compact_span, sum(v.num_beds))
    terms = []
    for p in range(len(plots)):
        if v.num_beds[p] == 0:
            continue
        used = [v.bed_used[(p, k)] for k in range(v.num_beds[p])]
        wasted = _gap_penalty(model, used, f"compact_p{p}")
        terms.append(coefficient * wasted)
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

    coefficient = _coefficient(
        v.settings.weight_line_dispersion, sum(v.num_beds) * max(len(by_line), 1)
    )
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
            terms.append(coefficient * wasted)
    return terms


def _minimize_fleece_count(v: OptimizerVars) -> list:
    """Minimise the number of fleece-weeks used."""
    coefficient = _coefficient(v.settings.weight_fleece_count, len(v.fleece))
    return [coefficient * fleece for fleece in v.fleece.values()]
