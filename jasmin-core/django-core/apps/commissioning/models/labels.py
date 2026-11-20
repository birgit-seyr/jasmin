from __future__ import annotations

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .base import JasminModel


class LabelTemplate(JasminModel):
    """The layout of the labels printed for the resellers' order lines.

    A farm keeps one for now: the label page and the editor use its first
    active template. ``elements`` places each piece of information on the
    label in mm; ``LabelTemplateSerializer`` holds its shape. Printed either
    one label per page on a label printer, or on A4 sheets of labels laid out
    by the ``sheet_*`` fields.
    """

    class PrintMode(models.TextChoices):
        LABEL_PRINTER = "label_printer", "Label printer"
        SHEET = "sheet", "A4 sheet"

    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    # Physical dimensions in mm (for printing)
    width_mm = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[MinValueValidator(Decimal("10")), MaxValueValidator(300)],
    )
    height_mm = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[MinValueValidator(Decimal("5")), MaxValueValidator(200)],
    )
    elements = models.JSONField(default=list)
    print_mode = models.CharField(
        max_length=20, choices=PrintMode.choices, default=PrintMode.LABEL_PRINTER
    )
    sheet_columns = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    sheet_rows = models.PositiveSmallIntegerField(
        default=8, validators=[MinValueValidator(1), MaxValueValidator(30)]
    )
    sheet_margin_top_mm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
    )
    sheet_margin_left_mm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
    )
    sheet_gap_x_mm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
    )
    sheet_gap_y_mm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
    )

    def __str__(self) -> str:
        return self.name
