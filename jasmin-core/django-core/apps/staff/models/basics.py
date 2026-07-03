from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from nanoid import generate

from apps.accounts.models import JasminUser

from ..constants import ID_LENGTH, JASMIN_ID_ALPHABET


def generate_jasmin_id():
    return generate(alphabet=JASMIN_ID_ALPHABET, size=ID_LENGTH)


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

    def get_display_id(self):
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

        # Split into groups of 3-4 characters with dashes
        chunk_size = 3
        chunks = [
            readable_id[i : i + chunk_size]
            for i in range(0, len(readable_id), chunk_size)
        ]

        return "-".join(chunks)


class Employee(JasminModel):
    # can also be a member
    is_active = models.BooleanField(default=True, db_index=True)
    short_name_for_weekly_plan = models.CharField(max_length=50)
    first_name = models.CharField(max_length=200, blank=True, null=True)
    last_name = models.CharField(max_length=200, blank=True, null=True)

    employee_number = models.CharField(
        max_length=50, unique=True, blank=True, null=True
    )
    user = models.OneToOneField(
        JasminUser,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employee_profile",
    )

    def __str__(self):
        return (
            f"Employee: {self.user.get_full_name()}"
            if self.user
            else f"Employee: {self.id}"
        )


class Employment(JasminModel):
    employee = models.ForeignKey(
        "Employee", on_delete=models.CASCADE, related_name="jobs"
    )
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=2)

    def save(self, *args, **kwargs) -> None:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError(
                {
                    "valid_until": "End date must be same or after start date.",
                    "valid_from": "Start date must be same or before end date.",
                }
            )
        super().save(*args, **kwargs)


class WeeklyPlanCategory(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=200)
    max_lines = models.IntegerField()


class WeeklyPlan(JasminModel):
    year = models.PositiveSmallIntegerField()
    week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    day = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)],
    )
    weekly_plan_category = models.ForeignKey(
        "WeeklyPlanCategory", on_delete=models.CASCADE
    )
    employee = models.ForeignKey("Employee", on_delete=models.CASCADE)
    row_index = models.IntegerField(blank=True, null=True)  # just inside the category


class AbsenceCategory(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)


class Absence(JasminModel):
    year = models.PositiveSmallIntegerField()
    week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    day = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)],
    )
    absence_category = models.ForeignKey("AbsenceCategory", on_delete=models.CASCADE)
    employee = models.ForeignKey("Employee", on_delete=models.CASCADE)
