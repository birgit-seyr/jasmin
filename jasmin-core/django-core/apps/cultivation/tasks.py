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
    from apps.notifications.jobs import run_job

    from .optimizer.optimizer import CultivationPlanOptimizer

    with run_job(schema_name, job_id) as job:
        optimizer = CultivationPlanOptimizer(year, progress_cb=job.progress)
        solutions = optimizer.run(num_solutions)
        job.result = {
            "year": year,
            "count": len(solutions),
            "solution_ids": [str(s.pk) for s in solutions],
            "versions": [s.version for s in solutions],
            "batches": len(optimizer.batches),
            "plots": len(optimizer.plots),
        }
