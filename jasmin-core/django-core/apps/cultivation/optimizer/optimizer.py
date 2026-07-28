"""Run the placement optimizer and persist candidate plans."""

from __future__ import annotations

from django.db import transaction
from ortools.sat.python import cp_model

from ..models import CultivationPlanSolution, CultivationPlanSolutionDetail
from . import config
from .loading import load_batches, load_blockers, load_carryover, load_plots
from .model import build_model
from .variables import OptimizerVars

# batch index -> (plot index, start cell)
Assignment = dict[int, tuple[int, int]]


class CultivationPlanOptimizer:
    """Places a year's finalized batches onto plots and saves the candidates."""

    def __init__(self, year: int, *, cells_per_bed: int = config.CELLS_PER_BED):
        self.year = year
        self.cells_per_bed = cells_per_bed
        self.batches = load_batches(year, cells_per_bed)
        self.plots = load_plots(cells_per_bed)
        self.blockers = load_blockers(year)
        self.carryover = load_carryover(year)

    def _new_solver(self) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = config.SOLVER_MAX_TIME_SECONDS
        solver.parameters.num_search_workers = config.SOLVER_WORKERS
        return solver

    def solve(
        self, num_solutions: int = config.DEFAULT_NUM_SOLUTIONS
    ) -> list[Assignment]:
        """Return up to ``num_solutions`` distinct assignments (best-first).

        Solves once, forbids that exact assignment with a no-good cut, and
        re-solves — so each next plan is the best one different from all before
        it.
        """
        if not self.batches:
            return []

        model, variables = build_model(
            self.batches, self.plots, self.blockers, self.carryover
        )

        solutions: list[Assignment] = []
        for _ in range(num_solutions):
            solver = self._new_solver()
            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                break
            assignment = self._extract(solver, variables)
            solutions.append(assignment)
            self._forbid(model, variables, assignment)
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
        """Persist each assignment as a versioned CultivationPlanSolution."""
        saved: list[CultivationPlanSolution] = []
        for version, assignment in enumerate(solutions, start=1):
            solution = CultivationPlanSolution.objects.create(
                year=self.year, version=version, cells_per_bed=self.cells_per_bed
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

    def run(
        self, num_solutions: int = config.DEFAULT_NUM_SOLUTIONS
    ) -> list[CultivationPlanSolution]:
        return self.save(self.solve(num_solutions))


def optimize_year(
    year: int, num_solutions: int = config.DEFAULT_NUM_SOLUTIONS
) -> list[CultivationPlanSolution]:
    """Convenience entry point: build, solve, and persist in one call."""
    return CultivationPlanOptimizer(year).run(num_solutions)
