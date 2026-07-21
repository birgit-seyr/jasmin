from typing import Any

from django.db import IntegrityError, models
from nanoid import generate

from ..constants import ID_LENGTH, JASMIN_ID_ALPHABET


def generate_jasmin_id() -> str:
    return generate(alphabet=JASMIN_ID_ALPHABET, size=ID_LENGTH)


class JasminModel(models.Model):
    id = models.CharField(
        "ID",
        max_length=ID_LENGTH,
        unique=True,
        primary_key=True,
        default=generate_jasmin_id,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save with retry logic for primary-key (nanoid) collision.

        Detects PK collisions specifically by inspecting the failing
        constraint, instead of substring-matching on the error message
        (which previously could swallow other unique-constraint failures
        that happened to mention the word "id").
        """
        max_retries = 5
        for attempt in range(max_retries):
            try:
                super().save(*args, **kwargs)
                return
            except IntegrityError as e:
                if self._is_pk_collision(e) and attempt < max_retries - 1:
                    self.id = generate_jasmin_id()
                else:
                    raise

    def _is_pk_collision(self, exc: IntegrityError) -> bool:
        """Return True iff the IntegrityError is a duplicate on the PK.

        Uses the psycopg constraint name when available
        (PostgreSQL convention: ``<table>_pkey``) and falls back to a
        narrower string match.
        """
        cause = getattr(exc, "__cause__", None)
        constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
        if constraint_name:
            return constraint_name.endswith("_pkey")
        # Fallback for non-PG backends or when diag is unavailable.
        msg = str(exc).lower()
        return "_pkey" in msg

    def get_display_id(self) -> str:
        """
        Convert the nanoid to a human-readable format.
        Examples:
            'aBc123XyZ' -> 'ABC-123-XYZ'
            'xK9mP2nQ4' -> 'XK9-MP2-NQ4'
        """
        if not self.id:
            return ""

        # Convert to uppercase for better readability
        readable_id = self.id.upper()

        # Split into groups of 3 characters with dashes
        CHUNK_SIZE = 3
        chunks = [
            readable_id[i : i + CHUNK_SIZE]
            for i in range(0, len(readable_id), CHUNK_SIZE)
        ]

        return "-".join(chunks)


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
