"""Reusable Django model field factories shared across apps.

These centralize the *non-default* configuration (the validators) for fields
whose invariant is duplicated across models, so the invariant lives in one place
and reads the same everywhere. A field with no shared configuration (a plain
``year``, say) deliberately gets no factory here — that would be pure
indirection around ``PositiveSmallIntegerField()``.

Domain-neutral on purpose: ``apps/shared`` is importable by any app (including
``commissioning``), so a single definition serves every consumer.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def iso_week_field(**kwargs) -> models.PositiveSmallIntegerField:
    """An ISO week number (1..53). Extra kwargs (e.g. ``db_index=True``) pass
    straight through; the 1..53 validators are the shared part."""
    return models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
        **kwargs,
    )


def day_of_week_field(**kwargs) -> models.PositiveSmallIntegerField:
    """A weekday index (0=Monday .. 6=Sunday). Extra kwargs pass straight
    through; the 0..6 validators are the shared part."""
    return models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        **kwargs,
    )
