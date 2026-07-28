"""Assemble the CP-SAT placement model.

Thin orchestrator: create the variables, add the hard constraints, add the soft
objective. The substance lives in :mod:`variables`, :mod:`hard_constraints`, and
:mod:`soft_constraints`. Pure w.r.t. the DB — it takes the dataclasses from
:mod:`loading`, so it can be exercised with hand-built inputs.

Formulation in one breath: each batch is a contiguous run of cells within one
plot (an interval on the cell axis) crossed with its fixed week window (an
interval on the time axis); ``AddNoOverlap2D`` per plot keeps two crops off the
same cell in the same week (succession falls out for free); crop rotation is a
per-(plot, family) 1-D no-overlap against prior chosen plans; and a per-bed
occupancy bridge carries the bed-level constraints (planting lines, fleece,
bed counting, compactness) over from the old boolean grid.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from .hard_constraints import add_all_hard_constraints
from .loading import BatchInput, Blocker, Carryover, PlotInput
from .soft_constraints import add_all_soft_constraints
from .variables import OptimizerVars, create_variables


def build_model(
    batches: list[BatchInput],
    plots: list[PlotInput],
    blockers: list[Blocker],
    carryover: list[Carryover] = (),
) -> tuple[cp_model.CpModel, OptimizerVars]:
    model = cp_model.CpModel()
    variables = create_variables(batches, plots, model)
    add_all_hard_constraints(model, batches, plots, blockers, carryover, variables)
    add_all_soft_constraints(model, batches, plots, variables)
    return model, variables
