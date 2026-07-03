from __future__ import annotations

from django.db import models

from .base import JasminModel
from .choices_text import PaymentCycleOptions


# the models here store the tenant specific parameters:
class PaymentCycle(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    choice = models.CharField(
        max_length=20, choices=PaymentCycleOptions.choices, null=False, unique=True
    )

    def __str__(self) -> str:
        return self.get_choice_display()
