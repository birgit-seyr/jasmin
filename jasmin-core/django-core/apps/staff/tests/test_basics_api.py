"""CRUD API tests for the staff basics endpoints (Employee, WeeklyPlanCategory,
AbsenceCategory) — the ``List*`` pages' backend.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.staff.models import (
    Absence,
    AbsenceCategory,
    Employee,
    Employment,
    WeeklyPlan,
    WeeklyPlanCategory,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# List / read
# --------------------------------------------------------------------------- #
def test_employees_list_returns_rows(api_client):
    Employee.objects.create(short_name_for_weekly_plan="Alice")
    Employee.objects.create(short_name_for_weekly_plan="Bob", is_active=False)

    response = api_client.get(reverse("employees-list"))

    assert response.status_code == status.HTTP_200_OK
    names = {row["short_name_for_weekly_plan"] for row in response.data}
    assert names == {"Alice", "Bob"}


def test_employees_is_active_filter(api_client):
    Employee.objects.create(short_name_for_weekly_plan="Active")
    Employee.objects.create(short_name_for_weekly_plan="Inactive", is_active=False)

    response = api_client.get(reverse("employees-list"), {"is_active": "true"})

    assert response.status_code == status.HTTP_200_OK
    names = {row["short_name_for_weekly_plan"] for row in response.data}
    assert names == {"Active"}


def test_is_active_bad_value_is_400(api_client):
    # Catalogue-driven validation: a non-boolean ``is_active`` 400s (not a 500).
    response = api_client.get(reverse("employees-list"), {"is_active": "maybe"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def test_create_employee(api_client):
    response = api_client.post(
        reverse("employees-list"),
        {"short_name_for_weekly_plan": "Carol", "first_name": "Carol"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert Employee.objects.filter(short_name_for_weekly_plan="Carol").exists()


def test_create_weekly_plan_category(api_client):
    response = api_client.post(
        reverse("weekly_plan_categories-list"),
        {"name": "Harvest", "max_lines": 5},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert WeeklyPlanCategory.objects.filter(name="Harvest").exists()


def test_create_absence_category(api_client):
    response = api_client.post(
        reverse("absence_categories-list"),
        {"year": 2026, "name": "Vacation"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert AbsenceCategory.objects.filter(year=2026, name="Vacation").exists()


def test_blank_employee_number_persists_as_null(api_client):
    # ``employee_number`` is unique + optional: a blank entry must become NULL so
    # a second blank-numbered employee doesn't collide on an empty string.
    first = api_client.post(
        reverse("employees-list"),
        {"short_name_for_weekly_plan": "One", "employee_number": ""},
        format="json",
    )
    second = api_client.post(
        reverse("employees-list"),
        {"short_name_for_weekly_plan": "Two", "employee_number": ""},
        format="json",
    )

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_201_CREATED
    assert Employee.objects.filter(employee_number__isnull=True).count() == 2


# --------------------------------------------------------------------------- #
# Delete protection (DeletableMixin) — mirrors the ``List*`` pages: a referenced
# row is flagged ``can_be_deleted=False`` so the frontend hides its delete
# button (the frontend ``permissionsWithDeletable`` reads this flag).
# --------------------------------------------------------------------------- #
def test_referenced_rows_are_flagged_not_deletable(api_client):
    category = WeeklyPlanCategory.objects.create(name="Kitchen", max_lines=3)
    employee = Employee.objects.create(short_name_for_weekly_plan="Dana")
    WeeklyPlan.objects.create(
        year=2026,
        week=1,
        day=0,
        weekly_plan_category=category,
        employee=employee,
    )

    category_row = next(
        r
        for r in api_client.get(reverse("weekly_plan_categories-list")).data
        if r["id"] == category.id
    )
    employee_row = next(
        r
        for r in api_client.get(reverse("employees-list")).data
        if r["id"] == employee.id
    )

    # Both are referenced by the WeeklyPlan → not deletable from the UI.
    assert category_row["can_be_deleted"] is False
    assert employee_row["can_be_deleted"] is False


def test_unreferenced_employee_is_deletable(api_client):
    employee = Employee.objects.create(short_name_for_weekly_plan="Solo")

    response = api_client.delete(reverse("employees-detail", args=[employee.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not Employee.objects.filter(id=employee.id).exists()


# --------------------------------------------------------------------------- #
# Permissions — read is IsStaff, write is IsOffice.
# --------------------------------------------------------------------------- #
def test_member_only_user_cannot_read(member_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=member_user)

    response = client.get(reverse("employees-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_anonymous_cannot_read(anon_client):
    response = anon_client.get(reverse("employees-list"))
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


# --------------------------------------------------------------------------- #
# Delete enforcement — DELETE honours ``can_be_deleted`` server-side. Every row
# referencing an employee / category is ON DELETE CASCADE, so an unchecked
# DELETE would silently wipe weekly-plan cells, absences and employments.
# --------------------------------------------------------------------------- #
def _weekly_plan_cell(employee, category):
    return WeeklyPlan.objects.create(
        year=2026, week=1, day=0, weekly_plan_category=category, employee=employee
    )


def _absence(employee, category):
    return Absence.objects.create(
        year=2026, week=1, day=0, absence_category=category, employee=employee
    )


_EMPLOYEE_REFERENCES = {
    "weekly_plan": lambda employee: _weekly_plan_cell(
        employee, WeeklyPlanCategory.objects.create(name="Kitchen", max_lines=3)
    ),
    "absence": lambda employee: _absence(
        employee, AbsenceCategory.objects.create(year=2026, name="Vacation")
    ),
    "employment": lambda employee: Employment.objects.create(
        employee=employee, valid_from="2026-01-05", hours_per_week="20.00"
    ),
}


@pytest.mark.parametrize("reference", sorted(_EMPLOYEE_REFERENCES))
def test_referenced_employee_delete_is_409_and_keeps_rows(api_client, reference):
    employee = Employee.objects.create(short_name_for_weekly_plan="Dana")
    dependent = _EMPLOYEE_REFERENCES[reference](employee)

    response = api_client.delete(reverse("employees-detail", args=[employee.id]))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["code"] == "staff.employee_in_use"
    assert Employee.objects.filter(id=employee.id).exists()
    assert type(dependent).objects.filter(id=dependent.id).exists()


def test_weekly_plan_category_in_use_delete_is_409_and_keeps_cells(api_client):
    category = WeeklyPlanCategory.objects.create(name="Kitchen", max_lines=3)
    cell = _weekly_plan_cell(
        Employee.objects.create(short_name_for_weekly_plan="Dana"), category
    )

    response = api_client.delete(
        reverse("weekly_plan_categories-detail", args=[category.id])
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["code"] == "staff.weekly_plan_category_in_use"
    assert WeeklyPlanCategory.objects.filter(id=category.id).exists()
    assert WeeklyPlan.objects.filter(id=cell.id).exists()


def test_unused_weekly_plan_category_is_deletable(api_client):
    category = WeeklyPlanCategory.objects.create(name="Unused", max_lines=1)

    response = api_client.delete(
        reverse("weekly_plan_categories-detail", args=[category.id])
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not WeeklyPlanCategory.objects.filter(id=category.id).exists()


def test_absence_category_in_use_delete_is_409_and_keeps_absences(api_client):
    category = AbsenceCategory.objects.create(year=2026, name="Vacation")
    absence = _absence(
        Employee.objects.create(short_name_for_weekly_plan="Dana"), category
    )

    response = api_client.delete(
        reverse("absence_categories-detail", args=[category.id])
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["code"] == "staff.absence_category_in_use"
    assert AbsenceCategory.objects.filter(id=category.id).exists()
    assert Absence.objects.filter(id=absence.id).exists()


def test_unused_absence_category_is_deletable(api_client):
    category = AbsenceCategory.objects.create(year=2026, name="Unused")

    response = api_client.delete(
        reverse("absence_categories-detail", args=[category.id])
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not AbsenceCategory.objects.filter(id=category.id).exists()
