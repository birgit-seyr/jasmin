"""Tests for the staff query-param catalogue.

The catalogue declares the QUERY parameters staff endpoints validate by. The
copy endpoint takes its weeks in the request body instead, where
``WeeklyPlanCopySerializer`` bounds them.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.staff.query_params import STAFF_PARAM_CATALOGUE

YEAR = 2026
WEEK = 30


def test_catalogue_holds_only_the_query_params_staff_endpoints_read():
    assert set(STAFF_PARAM_CATALOGUE) == {"year", "week"}


@pytest.mark.django_db
def test_copy_weeks_are_bounded_as_body_fields(api_client):
    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": 0, "to_week": WEEK},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
