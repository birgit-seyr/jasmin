from django.db import models

from .base import JasminModel
from .choices_text import DayNumberOptions


# also a market on the farm itself is included here:
class Market(JasminModel):
    """Reserved for a future markets feature — intentionally unwired.

    Model (+ factory) only: there is no serializer, viewset, service or read
    path exposing this yet. Kept on purpose until the feature is built or
    deliberately dropped — don't assume it's live.
    """

    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=300)
    day_number = models.PositiveSmallIntegerField(choices=DayNumberOptions.choices)

    def __str__(self) -> str:
        return self.name
