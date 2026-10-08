"""The documentation serializers refuse a duplicate with a coded error per
unique constraint; every constraint on the model needs one, or a duplicate
falls through to the database's IntegrityError."""

from __future__ import annotations

import pytest
from django.db import models

from apps.commissioning.serializers import (
    HarvestSerializer,
    PurchaseSerializer,
    WasteSerializer,
)


@pytest.mark.parametrize(
    "serializer_class", [HarvestSerializer, PurchaseSerializer, WasteSerializer]
)
def test_every_unique_constraint_has_a_coded_error(serializer_class):
    model = serializer_class.Meta.model
    unique_constraints = {
        constraint.name
        for constraint in model._meta.constraints
        if isinstance(constraint, models.UniqueConstraint)
    }

    assert set(serializer_class.UNIQUE_CONSTRAINT_ERRORS) == unique_constraints
    assert serializer_class.Meta.validators == []
