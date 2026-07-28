from django.db import models
from django.db.models import Q

from ..constants import CELLS_PER_BED
from .base import JasminModel


class CultivationPlanSolution(JasminModel):
    """One candidate placement for a year. Several can be computed; the office
    marks one ``chosen`` (the partial-unique constraint keeps it to exactly one)."""

    year = models.PositiveSmallIntegerField()
    version = models.PositiveSmallIntegerField()
    chosen = models.BooleanField(default=False)
    # Snapshot the grain the solver used, so an old plan still means the same
    # thing if CELLS_PER_BED is ever changed.
    cells_per_bed = models.PositiveSmallIntegerField(default=CELLS_PER_BED)

    class Meta:
        ordering = ["-year", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "version"], name="uniq_solution_year_version"
            ),
            models.UniqueConstraint(
                fields=["year"],
                condition=Q(chosen=True),
                name="one_chosen_solution_per_year",
            ),
        ]

    def __str__(self) -> str:
        marker = " (chosen)" if self.chosen else ""
        return f"Solution {self.year} v{self.version}{marker}"


class CultivationPlanSolutionDetail(JasminModel):
    """One placed batch: ``cell_count`` contiguous cells starting at ``start_cell``
    in the plot's serpentine (tractor-path) order. Bed = start_cell //
    solution.cells_per_bed; the week window comes from the batch."""

    solution = models.ForeignKey(
        "CultivationPlanSolution", related_name="details", on_delete=models.CASCADE
    )
    batch = models.ForeignKey("CultivationBatch", on_delete=models.CASCADE)
    plot = models.ForeignKey("Plot", on_delete=models.PROTECT)
    # 0-based serpentine index of the FIRST cell within the plot.
    start_cell = models.PositiveIntegerField()
    # Snapshot of amount_of_beds × cells_per_bed at solve time.
    cell_count = models.PositiveSmallIntegerField()

    class Meta:
        indexes = [
            # "all placements of this plan in this plot" — the read the layout
            # view and the rotation loader both do.
            models.Index(fields=["solution", "plot"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(cell_count__gt=0),
                name="solutiondetail_cell_count_positive",
            ),
        ]

    @property
    def end_cell(self) -> int:
        return self.start_cell + self.cell_count

    def __str__(self) -> str:
        return f"{self.batch_id} @ {self.plot_id} [{self.start_cell}:{self.end_cell}]"
