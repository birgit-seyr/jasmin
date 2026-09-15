"""Shared produce-dimension model field definitions.

The size / unit / delivery-week columns are shared by the reseller-line, share,
documentation, movement and stock-snapshot models. These factories are the
single source of truth for those field definitions. Each returns the exact
column definition those models already have (same max_length / choices /
validators / default / blank / null), so using them produces no migration.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .choices import UnitOptions, VegetableSizeOptions


def size_vegetable_field() -> models.CharField:
    """The produce ``size`` CharField (``VegetableSizeOptions``: S / M / L),
    defaulting to M."""
    return models.CharField(
        max_length=1,
        choices=VegetableSizeOptions.choices,
        default=VegetableSizeOptions.M,
    )


def unit_field(
    *, max_length: int = 10, blank: bool = False, null: bool = False
) -> models.CharField:
    """The produce ``unit`` CharField (``UnitOptions``).

    ``max_length`` is a parameter ONLY because the per-column widths differ: the
    ``DocumentationMixin`` column is 20 while every other unit column is 10.
    Normalising that width would require a migration, so that one site passes
    ``max_length=20``. ``blank`` / ``null`` default
    to the required-column case; pass both ``True`` for the nullable variant.
    """
    return models.CharField(
        max_length=max_length,
        choices=UnitOptions.choices,
        blank=blank,
        null=null,
    )


def delivery_week_field(**kwargs) -> models.PositiveSmallIntegerField:
    """The ISO ``delivery_week`` field with its 1..53 range validators. Extra
    kwargs (e.g. ``db_index=True``) pass straight through; the validators are
    the shared part."""
    return models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
        **kwargs,
    )
