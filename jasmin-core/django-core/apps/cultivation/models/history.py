from django.db import models

from .base import JasminModel, week_field


class HistoricalPlanting(JasminModel):
    """A hand-entered record of what grew where in a *past* year.

    For farms adopting the system mid-rotation: the optimizer's crop rotation
    needs to know what a bed held in prior years, but there is no chosen
    ``CultivationPlanSolution`` for the years before adoption. These rows fill
    that gap — enter, per past year, which rotation family occupied which cells
    of which plot.

    Cells match the solver's axis (``start_cell`` / ``cell_count``); the entry
    UI takes a bed range and converts (bed k = cells ``[k·W, (k+1)·W)``).

    ``occupied_until_week`` is optional: set it when an overwintering crop from
    that year is still physically in the ground at the start of the next year, so
    the first planned year treats those cells as occupied through that week
    (cross-year carryover).
    """

    year = models.PositiveSmallIntegerField()
    plot = models.ForeignKey(
        "Plot", on_delete=models.CASCADE, related_name="historical_plantings"
    )
    cultivation_break_family = models.ForeignKey(
        "CultivationBreakFamily",
        on_delete=models.CASCADE,
        related_name="historical_plantings",
    )
    # Optional, for reference/display only — rotation keys off the family.
    vegetable = models.ForeignKey(
        "Vegetable", on_delete=models.SET_NULL, blank=True, null=True
    )
    start_cell = models.PositiveIntegerField()
    cell_count = models.PositiveSmallIntegerField()
    # Set if the crop overwinters into the following year (still occupying these
    # cells through this week of the next year).
    occupied_until_week = week_field(blank=True, null=True)
    note = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ["-year"]
        indexes = [
            models.Index(fields=["year", "plot"]),
            models.Index(fields=["year", "cultivation_break_family"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cell_count__gt=0),
                name="historicalplanting_cell_count_positive",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.cultivation_break_family_id} @ {self.plot_id} "
            f"[{self.start_cell}:{self.start_cell + self.cell_count}] ({self.year})"
        )
