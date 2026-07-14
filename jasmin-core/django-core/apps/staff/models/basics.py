from django.core.exceptions import ValidationError
from django.db import models
from nanoid import generate

from apps.accounts.models import JasminUser
from apps.shared.model_fields import day_of_week_field, iso_week_field

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

    class Meta:
        ordering = ["short_name_for_weekly_plan"]

    def __str__(self) -> str:
        if self.user:
            return f"Employee: {self.user.get_full_name()}"
        return f"Employee: {self.short_name_for_weekly_plan or self.id}"


class Employment(JasminModel):
    employee = models.ForeignKey(
        "Employee", on_delete=models.CASCADE, related_name="jobs"
    )
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ["-valid_from"]

    def __str__(self) -> str:
        until = self.valid_until or "open"
        return f"{self.employee}: {self.valid_from} - {until}"

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
    # Optional manual ordering for the weekly plan. Nullable for backward
    # compatibility: existing rows stay NULL and — since Postgres sorts NULLs
    # last in ASC — fall to the end (alphabetically) until an order is assigned.
    sort_order = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "weekly plan categories"

    def __str__(self) -> str:
        return self.name


class WeeklyPlan(JasminModel):
    year = models.PositiveSmallIntegerField()
    week = iso_week_field()
    day = day_of_week_field()
    weekly_plan_category = models.ForeignKey(
        "WeeklyPlanCategory", on_delete=models.CASCADE
    )
    employee = models.ForeignKey("Employee", on_delete=models.CASCADE)
    row_index = models.IntegerField(blank=True, null=True)  # just inside the category

    class Meta:
        ordering = ["year", "week", "day", "row_index"]
        constraints = [
            # One employee per grid cell: a (week, day, category, row) slot holds
            # at most one assignment. Employees may still appear in many cells.
            # nulls_distinct=False so a null row_index can't slip duplicate cells
            # past the constraint (Postgres 15 / Django 5).
            models.UniqueConstraint(
                fields=["year", "week", "day", "weekly_plan_category", "row_index"],
                name="weeklyplan_one_employee_per_cell",
                nulls_distinct=False,
            ),
        ]
        # The unique constraint's index leads with (year, week), so the grid's
        # per-week fetch is already covered — no separate index needed here.

    def __str__(self) -> str:
        return (
            f"{self.year} W{self.week} D{self.day} - "
            f"{self.employee} ({self.weekly_plan_category})"
        )


class AbsenceCategory(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["year", "name"]
        verbose_name_plural = "absence categories"

    def __str__(self) -> str:
        return f"{self.name} ({self.year})"


class Absence(JasminModel):
    year = models.PositiveSmallIntegerField()
    week = iso_week_field()
    day = day_of_week_field()
    absence_category = models.ForeignKey("AbsenceCategory", on_delete=models.CASCADE)
    employee = models.ForeignKey("Employee", on_delete=models.CASCADE)

    class Meta:
        ordering = ["year", "week", "day"]
        constraints = [
            # One absence per employee per day: a person is either absent on a
            # given day or not. The constraint's index leads with (year, week),
            # so the absence-matrix / "who's absent this week" lookups are
            # covered too — no separate index needed.
            models.UniqueConstraint(
                fields=["year", "week", "day", "employee"],
                name="absence_one_per_employee_per_day",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.year} W{self.week} D{self.day} - "
            f"{self.employee} ({self.absence_category})"
        )
