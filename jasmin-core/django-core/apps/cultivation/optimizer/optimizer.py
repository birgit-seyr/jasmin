"""Run the placement optimizer and persist candidate plans."""

from __future__ import annotations

import time
from collections.abc import Callable

from django.db import transaction
from django.db.models import Max
from ortools.sat.python import cp_model

from ..models import CultivationPlanSolution, CultivationPlanSolutionDetail
from .config import DEFAULT_SETTINGS, SolverConfig
from .loading import (
    load_batches,
    load_blockers,
    load_carryover,
    load_plots,
    load_solver_settings,
)
from .model import build_model
from .variables import OptimizerVars

# batch index -> (plot index, start cell)
Assignment = dict[int, tuple[int, int]]

# Progress payloads use the shape the shared JobProgressDrawer understands:
# percent = processed / total. CP-SAT cannot predict when it will finish, so
# "processed" is the elapsed share of the TIME BUDGET (0..100), not a forecast —
# a run that proves optimality early simply jumps to 100.
ProgressCallback = Callable[[dict], None]
_PROGRESS_TOTAL = 100
_MIN_TICK_SECONDS = 1.0


class _ProgressReporter:
    """Throttled progress emitter shared by the solve loop and the CP-SAT
    solution callback (which is the only hook that fires *during* a solve)."""

    def __init__(self, callback: ProgressCallback | None, budget_seconds: float):
        self._callback = callback
        self._budget = max(budget_seconds, 1e-6)
        self._started = time.monotonic()
        self._last_emit = 0.0
        self._high_water = 0
        self.solutions_found = 0

    def tick(self, *, force: bool = False, done: bool = False) -> None:
        if self._callback is None:
            return
        now = time.monotonic()
        if not force and now - self._last_emit < _MIN_TICK_SECONDS:
            return
        self._last_emit = now
        elapsed = now - self._started
        share = (
            _PROGRESS_TOTAL if done else int(min(elapsed / self._budget, 0.99) * 100)
        )
        # Never let the bar run backwards (a fast final solve shrinks the budget
        # estimate but the user must not see progress regress).
        self._high_water = max(self._high_water, share)
        self._callback(
            {
                "processed": self._high_water,
                "total": _PROGRESS_TOTAL,
                "successful": self.solutions_found,
                "failed": 0,
                "elapsed_seconds": round(elapsed, 1),
                "solutions_found": self.solutions_found,
            }
        )


class _SolutionTicker(cp_model.CpSolverSolutionCallback):
    """Keeps the progress bar moving inside a single (up to max_time) solve."""

    def __init__(self, reporter: _ProgressReporter):
        super().__init__()
        self._reporter = reporter

    def on_solution_callback(self) -> None:  # noqa: N802 (or-tools API)
        self._reporter.tick()


class CultivationPlanOptimizer:
    """Places a year's finalized batches onto plots and saves the candidates."""

    def __init__(
        self,
        year: int,
        *,
        settings: SolverConfig | None = None,
        progress_cb: ProgressCallback | None = None,
    ):
        # Tenant-configured weights/flags; falls back to the module defaults.
        self.settings = settings if settings is not None else load_solver_settings()
        self.year = year
        self.cells_per_bed = self.settings.cells_per_bed
        self.progress_cb = progress_cb
        self.batches = load_batches(year, self.cells_per_bed)
        self.plots = load_plots(self.cells_per_bed)
        self.blockers = load_blockers(year)
        self.carryover = load_carryover(year, self.settings)

    def _new_solver(self) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.settings.max_time_seconds
        solver.parameters.num_search_workers = self.settings.workers
        return solver

    def solve(self, num_solutions: int | None = None) -> list[Assignment]:
        """Return up to ``num_solutions`` distinct assignments (best-first).

        Solves once, forbids that exact assignment with a no-good cut, and
        re-solves — so each next plan is the best one different from all before
        it.
        """
        if num_solutions is None:
            num_solutions = self.settings.num_solutions
        if not self.batches:
            return []

        reporter = _ProgressReporter(
            self.progress_cb, num_solutions * self.settings.max_time_seconds
        )
        reporter.tick(force=True)

        model, variables = build_model(
            self.batches, self.plots, self.blockers, self.carryover, self.settings
        )

        solutions: list[Assignment] = []
        for _ in range(num_solutions):
            solver = self._new_solver()
            status = solver.Solve(model, _SolutionTicker(reporter))
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                break
            assignment = self._extract(solver, variables)
            solutions.append(assignment)
            reporter.solutions_found = len(solutions)
            reporter.tick(force=True)
            self._forbid(model, variables, assignment)
        reporter.tick(force=True, done=True)
        return solutions

    def _extract(
        self, solver: cp_model.CpSolver, variables: OptimizerVars
    ) -> Assignment:
        assignment: Assignment = {}
        for b in range(len(self.batches)):
            for p in range(len(self.plots)):
                key = (b, p)
                if key in variables.present and solver.Value(variables.present[key]):
                    assignment[b] = (p, solver.Value(variables.start[key]))
                    break
        return assignment

    def _forbid(
        self, model: cp_model.CpModel, variables: OptimizerVars, assignment: Assignment
    ) -> None:
        """No-good cut: at least one batch must change plot or start cell."""
        stayed = []
        for b, (p, s0) in assignment.items():
            key = (b, p)
            same_start = model.NewBoolVar(f"same_start_{b}_{len(stayed)}")
            model.Add(variables.start[key] == s0).OnlyEnforceIf(same_start)
            model.Add(variables.start[key] != s0).OnlyEnforceIf(same_start.Not())
            stay = model.NewBoolVar(f"stay_{b}_{len(stayed)}")
            model.AddBoolAnd([variables.present[key], same_start]).OnlyEnforceIf(stay)
            model.AddBoolOr(
                [variables.present[key].Not(), same_start.Not()]
            ).OnlyEnforceIf(stay.Not())
            stayed.append(stay)
        if stayed:
            model.AddBoolOr([s.Not() for s in stayed])

    @transaction.atomic
    def save(self, solutions: list[Assignment]) -> list[CultivationPlanSolution]:
        """Persist each assignment as a versioned CultivationPlanSolution.

        Versions continue after any plans already stored for this year, so
        re-running the optimizer adds candidates instead of colliding with the
        ``(year, version)`` unique constraint.
        """
        next_version = (
            CultivationPlanSolution.objects.filter(year=self.year).aggregate(
                top=Max("version")
            )["top"]
            or 0
        ) + 1

        saved: list[CultivationPlanSolution] = []
        for offset, assignment in enumerate(solutions):
            solution = CultivationPlanSolution.objects.create(
                year=self.year,
                version=next_version + offset,
                cells_per_bed=self.cells_per_bed,
            )
            CultivationPlanSolutionDetail.objects.bulk_create(
                CultivationPlanSolutionDetail(
                    solution=solution,
                    batch_id=self.batches[b].id,
                    plot_id=self.plots[p].id,
                    start_cell=start_cell,
                    cell_count=self.batches[b].cell_count,
                )
                for b, (p, start_cell) in assignment.items()
            )
            saved.append(solution)
        return saved

    def run(self, num_solutions: int | None = None) -> list[CultivationPlanSolution]:
        return self.save(self.solve(num_solutions))


def optimize_year(
    year: int,
    num_solutions: int | None = None,
    *,
    progress_cb: ProgressCallback | None = None,
) -> list[CultivationPlanSolution]:
    """Convenience entry point: build, solve, and persist in one call."""
    return CultivationPlanOptimizer(year, progress_cb=progress_cb).run(num_solutions)


__all__ = [
    "CultivationPlanOptimizer",
    "optimize_year",
    "Assignment",
    "ProgressCallback",
    "DEFAULT_SETTINGS",
]
