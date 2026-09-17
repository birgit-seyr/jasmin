"""Weekly-plan grid operations.

The grid is a dense matrix the client stays dumb about: for each active
``WeeklyPlanCategory`` there are ``max_lines`` rows, each with a cell per weekday
(Mon=0 .. Sun=6) holding at most one employee. The database stores only the
*filled* cells as sparse ``WeeklyPlan`` rows keyed by
``(year, week, day, category, row_index)`` (the model's unique constraint).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..errors import (
    EmployeeNotFound,
    InvalidWeeklyPlanAssignment,
    WeeklyPlanCategoryNotFound,
    WeeklyPlanCopyTargetNotEmpty,
)
from ..models import Employee, WeeklyPlan, WeeklyPlanCategory

# Mon(0) .. Sun(6) — decided for the weekly plan (the model allows 0..6).
WEEKDAYS = range(7)


def build_week_grid(year: int, week: int) -> dict[str, Any]:
    """Materialize the dense grid for one ISO week.

    Three queries total (categories, filled cells, employees) — no N+1. Cells
    hold the employee **id** (or ``None``); the ``employees`` list carries the
    full row so the client resolves id → label once.
    """
    categories = list(
        WeeklyPlanCategory.objects.filter(is_active=True).order_by("sort_order", "name")
    )

    placed: dict[tuple[str, int, int], str] = {}
    for row in WeeklyPlan.objects.filter(year=year, week=week).values(
        "weekly_plan_category_id", "row_index", "day", "employee_id"
    ):
        placed[(row["weekly_plan_category_id"], row["row_index"], row["day"])] = row[
            "employee_id"
        ]

    category_grids = []
    for category in categories:
        rows = [
            {
                "row_index": row_index,
                "days": {
                    str(day): placed.get((category.id, row_index, day))
                    for day in WEEKDAYS
                },
            }
            for row_index in range(category.max_lines)
        ]
        category_grids.append(
            {
                "id": category.id,
                "name": category.name,
                "max_lines": category.max_lines,
                "rows": rows,
            }
        )

    employees = list(
        Employee.objects.filter(is_active=True)
        .order_by("short_name_for_weekly_plan")
        .values("id", "short_name_for_weekly_plan", "first_name", "last_name")
    )

    return {
        "year": year,
        "week": week,
        "categories": category_grids,
        "employees": employees,
    }


@transaction.atomic
def replace_week(year: int, week: int, assignments: list[dict[str, Any]]) -> None:
    """Replace ALL weekly-plan rows for ``(year, week)`` with ``assignments``.

    Whole-week last-write-wins: the client sends the full grid state, so the
    week is wiped and rebuilt in one transaction. Each assignment is validated
    (category + employee exist, ``row_index`` within the category's ``max_lines``,
    no two assignments on the same cell) before anything is written.
    """
    category_ids = {a["category_id"] for a in assignments}
    employee_ids = {a["employee_id"] for a in assignments}

    categories = {
        c.id: c for c in WeeklyPlanCategory.objects.filter(id__in=category_ids)
    }
    valid_employee_ids = set(
        Employee.objects.filter(id__in=employee_ids).values_list("id", flat=True)
    )

    seen_cells: set[tuple[str, int, int]] = set()
    rows_to_create: list[WeeklyPlan] = []
    for assignment in assignments:
        category = categories.get(assignment["category_id"])
        if category is None:
            raise WeeklyPlanCategoryNotFound(
                f"Unknown weekly-plan category: {assignment['category_id']}",
                field="category_id",
            )
        if assignment["employee_id"] not in valid_employee_ids:
            raise EmployeeNotFound(
                f"Unknown employee: {assignment['employee_id']}",
                field="employee_id",
            )
        row_index = assignment["row_index"]
        if not 0 <= row_index < category.max_lines:
            raise InvalidWeeklyPlanAssignment(
                f"row_index {row_index} out of range for category "
                f"'{category.name}' (0..{category.max_lines - 1})",
                field="row_index",
            )
        cell = (category.id, row_index, assignment["day"])
        if cell in seen_cells:
            raise InvalidWeeklyPlanAssignment(
                "Two assignments target the same cell "
                f"(category={category.id}, row={row_index}, day={assignment['day']})",
                field="assignments",
            )
        seen_cells.add(cell)
        rows_to_create.append(
            WeeklyPlan(
                year=year,
                week=week,
                day=assignment["day"],
                weekly_plan_category=category,
                employee_id=assignment["employee_id"],
                row_index=row_index,
            )
        )

    WeeklyPlan.objects.filter(year=year, week=week).delete()
    WeeklyPlan.objects.bulk_create(rows_to_create)


def weeks_stranded_by_shrink(
    category_id: str, new_max_lines: int
) -> list[dict[str, int]]:
    """ISO weeks from the current one on that hold rows a ``max_lines`` of
    ``new_max_lines`` would hide, oldest first.

    Lowering the count only hides those rows from :func:`build_week_grid`, but
    the grid is a replace-all surface: the client seeds its cell map purely from
    the grid it was served, so the next edit to ANY cell of such a week posts an
    assignment list without the hidden rows and :func:`replace_week` deletes
    them for good. Past weeks stay out of the answer — nothing edits them, and
    counting them would leave a long-lived category permanently unshrinkable.

    A row with a NULL ``row_index`` sits at no grid position at all, so the
    count it is compared against makes no difference to it; it is not reported.
    """
    # The local date, not the UTC one: east of UTC the two differ for the first
    # hours of a day, and during those hours the UTC date still sits in the week
    # that ended the night before — which would refuse a shrink over a week the
    # office can no longer edit.
    today: date = timezone.localdate()
    current_year, current_week, _ = today.isocalendar()

    stranded = (
        WeeklyPlan.objects.filter(
            weekly_plan_category_id=category_id,
            row_index__gte=new_max_lines,
        )
        .filter(Q(year__gt=current_year) | Q(year=current_year, week__gte=current_week))
        .values_list("year", "week")
        .distinct()
        .order_by("year", "week")
    )
    return [{"year": year, "week": week} for year, week in stranded]


@transaction.atomic
def copy_week(year: int, from_week: int, to_week: int) -> int:
    """Copy every cell of ``from_week`` into an EMPTY ``to_week`` (same year).

    Refuses if the target week already holds rows (would silently merge). The
    reference's "skip Saturday / skip absent employees" refinement is deferred
    until the Saturday-shift and absence surfaces exist. Returns the copied count.
    """
    if from_week == to_week:
        raise InvalidWeeklyPlanAssignment(
            "from_week and to_week must differ", field="to_week"
        )
    if WeeklyPlan.objects.filter(year=year, week=to_week).exists():
        raise WeeklyPlanCopyTargetNotEmpty(
            f"Week {to_week} already has a weekly plan", field="to_week"
        )

    copies = [
        WeeklyPlan(
            year=year,
            week=to_week,
            day=row.day,
            weekly_plan_category_id=row.weekly_plan_category_id,
            employee_id=row.employee_id,
            row_index=row.row_index,
        )
        for row in WeeklyPlan.objects.filter(year=year, week=from_week)
    ]
    WeeklyPlan.objects.bulk_create(copies)
    return len(copies)
