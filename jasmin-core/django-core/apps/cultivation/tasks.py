"""Background tasks for the cultivation app.

Auto-discovered by djhuey (any installed app's ``tasks.py`` is imported at
startup), so nothing else needs wiring.
"""

from __future__ import annotations

from huey.contrib.djhuey import db_task


@db_task(retries=0)
def run_cultivation_solver(
    *,
    schema_name: str,
    job_id: str,
    year: int,
    num_solutions: int | None = None,
) -> None:
    """Solve the placement problem for ``year`` and persist the candidate plans.

    Progress is streamed to the ``BackgroundJob`` row so the planner page can
    render a bar; ``retries=0`` because a re-run would duplicate solutions.
    """
    # Deferred: these pull in TENANT_APPS models, which must not be imported at
    # module scope in a task module.
    from ortools.sat.python import cp_model

    from apps.notifications.jobs import run_job

    from .errors import PlanInfeasible, PlanSolveTimedOut
    from .optimizer.optimizer import CultivationPlanOptimizer

    with run_job(schema_name, job_id) as job:
        optimizer = CultivationPlanOptimizer(year, progress_cb=job.progress)
        solutions = optimizer.run(num_solutions)

        # An empty result is a FAILURE, not a quiet success — and the two causes
        # need different remedies, so say which one happened. (Raising marks the
        # job failed with this message, which is what the office sees.)
        if not solutions:
            if optimizer.last_status == cp_model.INFEASIBLE:
                raise PlanInfeasible(
                    f"No placement can satisfy every constraint for {year}: "
                    f"{len(optimizer.batches)} batches over "
                    f"{len(optimizer.plots)} plots. Check whether demand exceeds "
                    f"the available beds, or whether crop-rotation history leaves "
                    f"a family nowhere to go."
                )
            raise PlanSolveTimedOut(
                f"The solver found no plan for {year} within its time budget "
                f"(status {optimizer.status_name}). Raise the time budget in the "
                f"solver settings, or switch off the planting-line rule to shrink "
                f"the model."
            )

        job.result = {
            "year": year,
            "count": len(solutions),
            "status": optimizer.status_name,
            "solution_ids": [str(s.pk) for s in solutions],
            "versions": [s.version for s in solutions],
            "batches": len(optimizer.batches),
            "plots": len(optimizer.plots),
        }
