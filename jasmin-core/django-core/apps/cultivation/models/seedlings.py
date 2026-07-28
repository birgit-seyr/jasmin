from django.db import models

from .base import JasminModel


class SeedlingsVendor(JasminModel):
    name = models.CharField(max_length=200)
    email = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SeedsVendor(JasminModel):
    name = models.CharField(max_length=200)
    email = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
