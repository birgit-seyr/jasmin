from django.db import models

from .base import JasminModel, week_field
from .choices import PlantingOptions


class CultivationBatch(JasminModel):
    year = models.PositiveSmallIntegerField()
    planting_week = week_field()
    week_when_net_is_removed = week_field(blank=True, null=True)
    week_when_fleece_is_removed = week_field(blank=True, null=True)
    harvesting_start_week = week_field()
    harvesting_end_week = week_field()
    delivery_start_week = week_field(blank=True, null=True)
    delivery_end_week = week_field(blank=True, null=True)
    # after this: new stuff can be planted on the same spot:
    end_week = week_field()

    vegetable = models.ForeignKey(
        "Vegetable", related_name="batches", on_delete=models.PROTECT
    )
    vegetable_set = models.ForeignKey(
        "VegetableAggregation",
        related_name="batches",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    planting_lines = models.PositiveSmallIntegerField()
    distance_in_row_in_m = models.DecimalField(max_digits=5, decimal_places=3)
    planting_mode = models.CharField(max_length=10, choices=PlantingOptions.choices)
    seedlings_are_produced_on_site = models.BooleanField(default=False)
    pieces_per_plant = models.DecimalField(max_digits=3, decimal_places=1)
    yield_kg_per_m2 = models.DecimalField(max_digits=5, decimal_places=2)

    used_bed_type = models.ForeignKey(
        "BedType", on_delete=models.PROTECT, blank=True, null=True
    )
    amount_of_beds = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    growing_area_m2 = models.IntegerField(blank=True, null=True)

    note = models.CharField(max_length=200, blank=True, null=True)

    # Only finalized batches are fed into the placement optimizer.
    is_final = models.BooleanField(default=False)

    class Meta:
        ordering = ["year", "planting_week"]
        indexes = [
            # The optimizer pulls "all finalized batches for year Y".
            models.Index(fields=["year", "is_final"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planting_lines__gt=0),
                name="cultivationbatch_planting_lines_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(distance_in_row_in_m__gt=0),
                name="cultivationbatch_distance_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(pieces_per_plant__gt=0),
                name="cultivationbatch_pieces_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(yield_kg_per_m2__gte=0),
                name="cultivationbatch_yield_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_of_beds__isnull=True)
                | models.Q(amount_of_beds__gt=0),
                name="cultivationbatch_beds_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(growing_area_m2__isnull=True)
                | models.Q(growing_area_m2__gt=0),
                name="cultivationbatch_area_positive",
            ),
            # NOTE: no planting_week <= end_week check — overwintering crops
            # (plant week 48, free again week 10 next year) legitimately wrap
            # the year boundary, so week ordering is not monotone.
        ]

    def __str__(self) -> str:
        return f"{self.vegetable} · {self.year} KW{self.planting_week}"
