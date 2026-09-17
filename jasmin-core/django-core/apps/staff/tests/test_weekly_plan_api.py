"""API tests for the weekly-plan grid endpoints (dense GET, replace-all POST,
copy)."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.staff.models import Employee, WeeklyPlan, WeeklyPlanCategory

pytestmark = pytest.mark.django_db

YEAR = 2026
WEEK = 30


@pytest.fixture()
def category(db):
    return WeeklyPlanCategory.objects.create(name="Harvest", max_lines=3)


@pytest.fixture()
def employees(db):
    return [
        Employee.objects.create(short_name_for_weekly_plan="Alice"),
        Employee.objects.create(short_name_for_weekly_plan="Bob"),
    ]


def _assign(category, row_index, day, employee):
    return {
        "category_id": category.id,
        "row_index": row_index,
        "day": day,
        "employee_id": employee.id,
    }


# --------------------------------------------------------------------------- #
# Dense grid GET
# --------------------------------------------------------------------------- #
def test_grid_is_dense(api_client, category, employees):
    response = api_client.get(reverse("weekly_plan-grid"), {"year": YEAR, "week": WEEK})

    assert response.status_code == status.HTTP_200_OK
    body = response.data
    assert body["year"] == YEAR and body["week"] == WEEK
    assert len(body["categories"]) == 1
    grid_cat = body["categories"][0]
    # max_lines rows, each with a cell per weekday Mon..Sun.
    assert len(grid_cat["rows"]) == category.max_lines
    assert set(grid_cat["rows"][0]["days"].keys()) == {str(d) for d in range(7)}
    assert all(v is None for v in grid_cat["rows"][0]["days"].values())
    assert {e["short_name_for_weekly_plan"] for e in body["employees"]} == {
        "Alice",
        "Bob",
    }


def test_grid_requires_year_and_week(api_client):
    assert (
        api_client.get(reverse("weekly_plan-grid"), {"year": YEAR}).status_code
        == status.HTTP_400_BAD_REQUEST
    )


# --------------------------------------------------------------------------- #
# Replace-all
# --------------------------------------------------------------------------- #
def test_replace_all_persists_and_reflects_in_grid(api_client, category, employees):
    alice, bob = employees
    response = api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK,
            "assignments": [
                _assign(category, 0, 0, alice),
                _assign(category, 1, 2, bob),
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert WeeklyPlan.objects.filter(year=YEAR, week=WEEK).count() == 2
    # The returned grid already reflects the write.
    grid_cat = response.data["categories"][0]
    assert grid_cat["rows"][0]["days"]["0"] == alice.id
    assert grid_cat["rows"][1]["days"]["2"] == bob.id


def test_replace_all_is_whole_week_replace(api_client, category, employees):
    alice, bob = employees
    api_client.post(
        reverse("weekly_plan-list"),
        {"year": YEAR, "week": WEEK, "assignments": [_assign(category, 0, 0, alice)]},
        format="json",
    )
    # Second write with a different (single) assignment wipes the first.
    api_client.post(
        reverse("weekly_plan-list"),
        {"year": YEAR, "week": WEEK, "assignments": [_assign(category, 2, 5, bob)]},
        format="json",
    )

    rows = WeeklyPlan.objects.filter(year=YEAR, week=WEEK)
    assert rows.count() == 1
    assert rows.first().employee_id == bob.id


def test_same_employee_may_occupy_many_cells(api_client, category, employees):
    alice, _ = employees
    response = api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK,
            "assignments": [
                _assign(category, 0, 0, alice),
                _assign(category, 0, 1, alice),
                _assign(category, 1, 0, alice),
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert WeeklyPlan.objects.filter(employee=alice).count() == 3


def test_row_index_out_of_range_is_rejected(api_client, category, employees):
    alice, _ = employees
    response = api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK,
            "assignments": [_assign(category, 99, 0, alice)],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "staff.invalid_weekly_plan_assignment"
    # Nothing persisted (validation is before the write, in one transaction).
    assert not WeeklyPlan.objects.filter(year=YEAR, week=WEEK).exists()


def test_duplicate_cell_is_rejected(api_client, category, employees):
    alice, bob = employees
    response = api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK,
            "assignments": [
                _assign(category, 0, 0, alice),
                _assign(category, 0, 0, bob),
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "staff.invalid_weekly_plan_assignment"


def test_unknown_employee_is_rejected(api_client, category):
    response = api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK,
            "assignments": [
                {
                    "category_id": category.id,
                    "row_index": 0,
                    "day": 0,
                    "employee_id": "nonexistent",
                }
            ],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["code"] == "staff.employee_not_found"


# --------------------------------------------------------------------------- #
# Copy
# --------------------------------------------------------------------------- #
def test_copy_into_empty_week(api_client, category, employees):
    alice, _ = employees
    api_client.post(
        reverse("weekly_plan-list"),
        {"year": YEAR, "week": WEEK, "assignments": [_assign(category, 0, 0, alice)]},
        format="json",
    )

    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK + 1},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert WeeklyPlan.objects.filter(year=YEAR, week=WEEK + 1).count() == 1
    assert response.data["categories"][0]["rows"][0]["days"]["0"] == alice.id


def test_copy_into_nonempty_week_conflicts(api_client, category, employees):
    alice, bob = employees
    api_client.post(
        reverse("weekly_plan-list"),
        {"year": YEAR, "week": WEEK, "assignments": [_assign(category, 0, 0, alice)]},
        format="json",
    )
    api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK + 1,
            "assignments": [_assign(category, 0, 0, bob)],
        },
        format="json",
    )

    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK + 1},
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["code"] == "staff.weekly_plan_copy_target_not_empty"
    # The target's own plan is untouched.
    assert WeeklyPlan.objects.get(year=YEAR, week=WEEK + 1).employee_id == bob.id


def test_copy_carries_the_last_rendered_row(api_client, category, employees):
    alice, _ = employees
    # row_index max_lines - 1 is the last row the grid renders — it copies.
    api_client.post(
        reverse("weekly_plan-list"),
        {
            "year": YEAR,
            "week": WEEK,
            "assignments": [_assign(category, category.max_lines - 1, 3, alice)],
        },
        format="json",
    )

    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK + 1},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    copied = WeeklyPlan.objects.get(year=YEAR, week=WEEK + 1)
    assert copied.row_index == category.max_lines - 1
    assert copied.employee_id == alice.id


def test_copy_refuses_source_rows_past_the_category_row_count(
    api_client, category, employees
):
    alice, _ = employees
    WeeklyPlan.objects.create(
        year=YEAR,
        week=WEEK,
        day=0,
        weekly_plan_category=category,
        employee=alice,
        row_index=0,
    )
    WeeklyPlan.objects.create(
        year=YEAR,
        week=WEEK,
        day=1,
        weekly_plan_category=category,
        employee=alice,
        row_index=2,
    )
    # The count drops under the second row, which the shrink guard allows once
    # the week holding it is past.
    category.max_lines = 2
    category.save(update_fields=["max_lines"])

    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK + 1},
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["code"] == "staff.weekly_plan_copy_source_rows_out_of_range"
    assert response.data["field"] == "from_week"
    assert response.data["details"]["categories"] == [
        {
            "category_id": category.id,
            "category_name": "Harvest",
            "max_lines": 2,
            "row_indexes": [2],
        }
    ]
    # Neither week moved: the target stays empty and the source keeps both rows.
    assert not WeeklyPlan.objects.filter(year=YEAR, week=WEEK + 1).exists()
    assert WeeklyPlan.objects.filter(year=YEAR, week=WEEK).count() == 2


def test_one_blocking_category_refuses_the_whole_copy(api_client, category, employees):
    alice, _ = employees
    fitting = WeeklyPlanCategory.objects.create(name="Packing", max_lines=4)
    WeeklyPlan.objects.create(
        year=YEAR,
        week=WEEK,
        day=0,
        weekly_plan_category=fitting,
        employee=alice,
        row_index=3,
    )
    WeeklyPlan.objects.create(
        year=YEAR,
        week=WEEK,
        day=0,
        weekly_plan_category=category,
        employee=alice,
        row_index=2,
    )
    category.max_lines = 1
    category.save(update_fields=["max_lines"])

    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK + 1},
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    blocked = response.data["details"]["categories"]
    assert [entry["category_id"] for entry in blocked] == [category.id]
    # The category that fits is not copied either — a partial copy would fill
    # the target week and block the retry.
    assert not WeeklyPlan.objects.filter(year=YEAR, week=WEEK + 1).exists()


def test_copy_ignores_a_row_at_no_grid_position(api_client, category, employees):
    alice, _ = employees
    # A NULL row_index sits at no position, so no row count applies to it.
    WeeklyPlan.objects.create(
        year=YEAR,
        week=WEEK,
        day=0,
        weekly_plan_category=category,
        employee=alice,
        row_index=None,
    )

    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK + 1},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert WeeklyPlan.objects.filter(year=YEAR, week=WEEK + 1).count() == 1


def test_copy_same_week_is_rejected(api_client, category):
    response = api_client.post(
        reverse("weekly_plan-copy"),
        {"year": YEAR, "from_week": WEEK, "to_week": WEEK},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def test_member_only_user_cannot_read_grid(member_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=member_user)
    response = client.get(reverse("weekly_plan-grid"), {"year": YEAR, "week": WEEK})
    assert response.status_code == status.HTTP_403_FORBIDDEN
