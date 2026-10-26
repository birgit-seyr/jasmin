from django.db import models


# the textchoices here are given by the app, are to be chosen by the tenant, but can not be changed by the tenant:
class PlantingOptions(models.TextChoices):
    P = "PLANTING"
    S = "SOWING"


class UnitOptions(models.TextChoices):
    KG = "KG"
    PCS = "PCS"  # pieces
    BUNCH = "BUNCH"  # bunch / (dt.: Bund)


class FertilizerRequirementsOptions(models.TextChoices):
    WEAK = "WEAK"
    MIDDLE = "MIDDLE"
    STRONG = "STRONG"


class SeedType(models.TextChoices):
    G = "G", "G"  ### counted in single grains
    g = "g", "g"  ### counted in grams
