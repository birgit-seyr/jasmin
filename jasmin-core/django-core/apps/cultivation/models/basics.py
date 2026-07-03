from django.db import models
from nanoid import generate

from ..constants import ID_LENGTH


def generate_jasmin_id():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return generate(alphabet=alphabet, size=ID_LENGTH)


class JasminModel(models.Model):
    id = models.CharField(
        "ID",
        max_length=ID_LENGTH,
        unique=True,
        primary_key=True,
        default=generate_jasmin_id,
    )

    class Meta:
        abstract = True


# class VegetableFamily(JasminModel):

#     PLANTING_CHOICES = [
#         ('P', 'P'),
#         ('S', 'S'),
#     ]

#     name = models.CharField(max_length=150)
#     unit = models.CharField(
#         max_length=5, choices=[(unit.value, unit.name) for unit in choices.Unit]
#     )
#     average_kg_per_piece = models.DecimalField(max_digits=5, decimal_places=3, default=1.000)

#     cultivation_break_family = models.ForeignKey(
#         "CultivationBreakFamily", on_delete=models.PROTECT, blank=True, null=True
#     )  # leguminose etc to determine the cultivation break
#     cultivation_break = models.IntegerField(blank=True, null=True)
#     fertilizer_type = models.ForeignKey(
#         "FertilizerType", on_delete=models.PROTECT, blank=True, null=True
#     )
#     is_cabbage = models.BooleanField(default=False)

#     # these following fields are default values for the sets - they can be changed for each set invidually though
#     usual_output_yield = models.DecimalField(
#         max_digits=5, decimal_places=3, blank=True, null=True
#     )  # this is in kg/m2
#     usual_pieces_per_plant = models.IntegerField(blank=True, null=True)
#     usual_planting_lines = models.IntegerField(blank=True, null=True)  # per bed
#     usual_planting = models.CharField(
#         max_length=1,
#         choices=PLANTING_CHOICES, blank=True, null=True)

#     def __str__(self):
#         return f"{self.name} [{self.unit}]"

# #     YearlyBox,
#     PlannedAmountBoxes,
#     CultivationPlanSet,
#     CultivationBreakFamily,
#     VegetableSetAggregation,
#     FertilizerType,
#     CultivationPlanSolution,
#     CultivationPlanSolutionDetail,
#     SeedlingsVendor,
#     SeedsVendor,
#     SeedlingsOrder,
#     SeedsOrder,
#     BedType,
#     Tunnels,
