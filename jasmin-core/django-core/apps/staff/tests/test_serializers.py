"""Serializer-level validation for the staff basics endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import time_machine
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.staff.models import Employee, WeeklyPlan, WeeklyPlanCategory

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


class TestMaxLinesShrink:
    """Lowering ``max_lines`` is refused while the rows it would hide still hold
    weekly-plan entries in the current ISO week or a later one."""

    FROZEN = datetime(2026, 9, 14, 12, 0)  # Monday of ISO 2026-W38
    CURRENT_WEEK = 38
    PAST_WEEK = 35
    FUTURE_WEEK = 41
    YEAR = 2026

    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        # The refusal compares stored weeks against "now", so the week numbers
        # below stay current/past/future no matter when the suite runs.
        with time_machine.travel(self.FROZEN, tick=False):
            yield

    @pytest.fixture()
    def employee(self):
        return Employee.objects.create(short_name_for_weekly_plan="Alice")

    def _plan(self, category, employee, week, row_index):
        return WeeklyPlan.objects.create(
            year=self.YEAR,
            week=week,
            day=0,
            weekly_plan_category=category,
            employee=employee,
            row_index=row_index,
        )

    def _patch(self, api_client, category, payload):
        return api_client.patch(
            reverse("weekly_plan_categories-detail", args=[category.id]),
            payload,
            format="json",
        )

    def test_shrink_with_no_stranded_rows_is_allowed(self, api_client, employee):
        category = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=5)
        self._plan(category, employee, self.CURRENT_WEEK, row_index=1)

        response = self._patch(api_client, category, {"max_lines": 3})

        assert response.status_code == status.HTTP_200_OK
        category.refresh_from_db()
        assert category.max_lines == 3

    def test_shrink_stranding_only_past_weeks_is_allowed(self, api_client, employee):
        # History is out of scope: nothing edits a past week's grid, and counting
        # it would leave a long-lived category permanently unshrinkable.
        category = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=5)
        self._plan(category, employee, self.PAST_WEEK, row_index=4)

        response = self._patch(api_client, category, {"max_lines": 3})

        assert response.status_code == status.HTTP_200_OK
        category.refresh_from_db()
        assert category.max_lines == 3

    def test_shrink_stranding_current_or_future_weeks_is_refused(
        self, api_client, employee
    ):
        category = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=5)
        self._plan(category, employee, self.PAST_WEEK, row_index=4)
        self._plan(category, employee, self.CURRENT_WEEK, row_index=4)
        self._plan(category, employee, self.FUTURE_WEEK, row_index=3)

        response = self._patch(api_client, category, {"max_lines": 3})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "staff.weekly_plan_category_shrink_blocked"
        assert response.data["field"] == "max_lines"
        # The per-field list is what marks the offending cell in the grid.
        assert response.data["details"]["max_lines"] == [response.data["message"]]
        # The blocking weeks travel along so the office sees what is in the way;
        # the past week is not among them.
        assert response.data["details"]["weeks"] == [
            {"year": self.YEAR, "week": self.CURRENT_WEEK},
            {"year": self.YEAR, "week": self.FUTURE_WEEK},
        ]
        category.refresh_from_db()
        assert category.max_lines == 5

    def test_raising_max_lines_is_always_allowed(self, api_client, employee):
        category = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=3)
        self._plan(category, employee, self.CURRENT_WEEK, row_index=2)

        response = self._patch(api_client, category, {"max_lines": 6})

        assert response.status_code == status.HTTP_200_OK
        category.refresh_from_db()
        assert category.max_lines == 6

    def test_an_echoed_unchanged_max_lines_is_allowed(self, api_client, employee):
        # The list page posts the whole row on every save, so a category whose
        # grid already hides rows stays editable as long as the count is untouched.
        category = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=3)
        self._plan(category, employee, self.CURRENT_WEEK, row_index=4)

        response = self._patch(
            api_client,
            category,
            {"name": "Harvest renamed", "max_lines": 3, "is_active": True},
        )

        assert response.status_code == status.HTTP_200_OK
        category.refresh_from_db()
        assert category.name == "Harvest renamed"
        assert category.max_lines == 3

    def test_only_the_edited_categorys_own_rows_block_it(self, api_client, employee):
        # Each category owns its own grid rows, so a neighbour's entries in the
        # very same week are none of this shrink's business. Without the
        # per-category filter one stranded row anywhere would freeze every
        # category in the tenant.
        kitchen = WeeklyPlanCategory.objects.create(name="Kitchen", max_lines=6)
        harvest = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=6)
        self._plan(harvest, employee, self.CURRENT_WEEK, row_index=5)
        self._plan(kitchen, employee, self.CURRENT_WEEK, row_index=1)

        response = self._patch(api_client, kitchen, {"max_lines": 4})

        assert response.status_code == status.HTTP_200_OK
        kitchen.refresh_from_db()
        assert kitchen.max_lines == 4
        harvest.refresh_from_db()
        assert harvest.max_lines == 6


class TestMaxLinesShrinkReadsTheLocalWeek:
    """Which weeks are still editable is decided by the LOCAL date."""

    def test_a_week_that_ended_locally_does_not_block_a_shrink(self, api_client):
        # 22:30 UTC on Sunday is already 00:30 Monday in Europe/Berlin, so ISO
        # week 37 is over and only week 38 onwards can block. Reading the UTC
        # date would put "now" back in week 37 and refuse the shrink over rows
        # nobody can edit any more — the same request then passing two hours
        # later.
        employee = Employee.objects.create(short_name_for_weekly_plan="Alice")
        category = WeeklyPlanCategory.objects.create(name="Harvest", max_lines=5)
        WeeklyPlan.objects.create(
            year=2026,
            week=37,
            day=0,
            weekly_plan_category=category,
            employee=employee,
            row_index=4,
        )

        with (
            timezone.override("Europe/Berlin"),
            time_machine.travel(datetime(2026, 9, 13, 22, 30, tzinfo=UTC), tick=False),
        ):
            response = api_client.patch(
                reverse("weekly_plan_categories-detail", args=[category.id]),
                {"max_lines": 3},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        category.refresh_from_db()
        assert category.max_lines == 3
