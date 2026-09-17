"""Serializer-level validation for the staff basics endpoints."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.staff.models import WeeklyPlanCategory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("value", [0, -3])
def test_non_positive_max_lines_carries_the_staff_error_code(api_client, value):
    # The refusal travels as a JasminError, so the client keys off the stable
    # code and renders its own localized text instead of the wire message.
    response = api_client.post(
        reverse("weekly_plan_categories-list"),
        {"name": "Harvest", "max_lines": value},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "staff.invalid"
    assert response.data["field"] == "max_lines"
    assert "max_lines" in response.data["details"]
    assert not WeeklyPlanCategory.objects.filter(name="Harvest").exists()


def test_lowering_max_lines_below_one_carries_the_staff_error_code(api_client):
    category = WeeklyPlanCategory.objects.create(name="Kitchen", max_lines=3)

    response = api_client.patch(
        reverse("weekly_plan_categories-detail", args=[category.id]),
        {"max_lines": 0},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "staff.invalid"
    category.refresh_from_db()
    assert category.max_lines == 3


def test_a_stored_non_positive_max_lines_stays_editable(api_client):
    # The list page echoes every column back on save, so the refusal keys on the
    # count changing — a row that already carries a non-positive count stays
    # editable as long as that count is left alone.
    category = WeeklyPlanCategory.objects.create(name="Legacy", max_lines=0)

    response = api_client.patch(
        reverse("weekly_plan_categories-detail", args=[category.id]),
        {"name": "Legacy renamed", "max_lines": 0, "is_active": True},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    category.refresh_from_db()
    assert category.name == "Legacy renamed"
    assert category.max_lines == 0
