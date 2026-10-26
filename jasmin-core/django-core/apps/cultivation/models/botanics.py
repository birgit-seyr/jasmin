from django.db import models

from .base import JasminModel
from .choices import FertilizerRequirementsOptions, PlantingOptions, UnitOptions


class CultivationBreakFamily(JasminModel):
    name = models.CharField(max_length=200)
    cultivation_break_in_years = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"], name="uniq_cultivationbreakfamily_name"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Vegetable(JasminModel):
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    average_kg_per_piece = models.DecimalField(max_digits=5, decimal_places=3)

    # default values (can be changed on each set)
    default_planting_lines = models.IntegerField()
    default_distance_in_row = models.DecimalField(max_digits=4, decimal_places=2)
    default_planting_mode = models.CharField(
        max_length=10, choices=PlantingOptions.choices
    )
    default_pieces_per_plant = models.IntegerField(blank=True, null=True)
    default_yield_kg_per_m2 = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )

    fertilizer_requirement = models.CharField(
        max_length=50, choices=FertilizerRequirementsOptions.choices
    )
    cultivation_break_family = models.ForeignKey(
        "CultivationBreakFamily",
        related_name="vegetables",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name"], name="uniq_vegetable_name"),
            models.CheckConstraint(
                condition=models.Q(average_kg_per_piece__gt=0),
                name="vegetable_avg_kg_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


# this model can be used in cultivationset to show that some things need to be
# planted close, like for example zucchini and melons, because they both need
# mulching
class VegetableAggregation(JasminModel):
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"], name="uniq_vegetableaggregation_name"
            ),
        ]

    def __str__(self) -> str:
        return self.name
