"""Weekly-plan grid operations.

The grid is a dense matrix the client stays dumb about: for each active
``WeeklyPlanCategory`` there are ``max_lines`` rows, each with a cell per weekday
(Mon=0 .. Sun=6) holding at most one employee. The database stores only the
*filled* cells as sparse ``WeeklyPlan`` rows keyed by
``(year, week, day, category, row_index)`` (the model's unique constraint).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ..errors import (
    EmployeeNotFound,
    InvalidWeeklyPlanAssignment,
    WeeklyPlanCategoryNotFound,
    WeeklyPlanCopySourceCategoryInactive,
    WeeklyPlanCopySourceRowsOutOfRange,
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
        # ``build_week_grid`` renders active categories only, so a row written
        # into a deactivated one sits at no position the office can see or edit,
        # and the next whole-week replace deletes it. A grid rendered before the
        # category was switched off still posts its cells, so refuse them here
        # rather than store rows nobody can reach.
        if not category.is_active:
            raise InvalidWeeklyPlanAssignment(
                f"Category '{category.name}' is deactivated, so the weekly plan "
                "does not show it. Reactivate it, or drop its assignments.",
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


def _per_category(
    rows: Iterable[Mapping[str, Any]], *, carry: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    """Collapse ``values()`` rows into one entry per category, each carrying the
    ``row_indexes`` that named it, in the order the query returned them.

    ``carry`` names further category columns to copy onto the entry, given
    without their ``weekly_plan_category__`` prefix. The two callers report
    different reasons and so answer with different keys — only a refusal about
    ``max_lines`` can say what that count is.
    """
    per_category: dict[str, dict[str, Any]] = {}
    for row in rows:
        category_id = row["weekly_plan_category_id"]
        entry = per_category.setdefault(
            category_id,
            {
                "category_id": category_id,
                "category_name": row["weekly_plan_category__name"],
                **{key: row[f"weekly_plan_category__{key}"] for key in carry},
                "row_indexes": [],
            },
        )
        entry["row_indexes"].append(row["row_index"])
    return list(per_category.values())


def rows_in_inactive_categories(year: int, week: int) -> list[dict[str, Any]]:
    """Rows of ``(year, week)`` belonging to a deactivated category, grouped per
    category, categories by name.

    :func:`build_week_grid` renders active categories only, so every row of a
    deactivated category sits at no position the grid shows, whatever its
    ``row_index`` — the category's ``max_lines`` says nothing about those rows
    and is left out of the answer. A NULL ``row_index`` occupies no grid
    position under any category, so it is left out here as everywhere else.
    """
    hidden = (
        WeeklyPlan.objects.filter(
            year=year,
            week=week,
            weekly_plan_category__is_active=False,
            row_index__isnull=False,
        )
        .values(
            "weekly_plan_category_id",
            "weekly_plan_category__name",
            "row_index",
        )
        .distinct()
        .order_by("weekly_plan_category__name", "row_index")
    )

    return _per_category(hidden)


def rows_beyond_category_rows(year: int, week: int) -> list[dict[str, Any]]:
    """Rows of ``(year, week)`` in an ACTIVE category, sitting at a ``row_index``
    at or past that category's ``max_lines``, grouped per category, categories by
    name.

    Each row is compared against the count of the category it belongs to, in the
    join, so one category's size never judges another's — and it stays one query.
    A NULL ``row_index`` occupies no grid position at all, so no count applies to
    it and it never matches. A deactivated category is out of scope: no count
    gives its rows a position either, and :func:`rows_in_inactive_categories`
    names them under that reason instead, so no category is reported by both.
    """
    offending = (
        WeeklyPlan.objects.filter(
            year=year, week=week, weekly_plan_category__is_active=True
        )
        .filter(row_index__gte=F("weekly_plan_category__max_lines"))
        .values(
            "weekly_plan_category_id",
            "weekly_plan_category__name",
            "weekly_plan_category__max_lines",
            "row_index",
        )
        .distinct()
        .order_by("weekly_plan_category__name", "row_index")
    )

    return _per_category(offending, carry=("max_lines",))


@transaction.atomic
def copy_week(year: int, from_week: int, to_week: int) -> int:
    """Copy every cell of ``from_week`` into an EMPTY ``to_week`` (same year).

    Refuses if the target week already holds rows (would silently merge). The
    reference's "skip Saturday / skip absent employees" refinement is deferred
    until the Saturday-shift and absence surfaces exist. Returns the copied count.

    Refuses too while the source week holds a row past its category's current
    ``max_lines``. Lowering that count is allowed over weeks nobody edits any
    more, so a past week may legitimately carry such rows; the grid renders only
    ``range(max_lines)``, so carrying them into an editable week hides them
    there and the next whole-week replace — which rebuilds the week from the
    cells the client was served — deletes them. Skipping just those rows would
    lose the same data, so the whole copy is refused even when only one of
    several categories is blocking: a partial copy would fill the target week,
    and the retry after raising the count would then hit the target-not-empty
    refusal. All-or-nothing keeps the copy repeatable once the office has acted.

    A row in a deactivated category is refused on the same ground — the grid
    renders active categories only, so that row reaches no position in the
    target week either — under its own code, because the remedy differs:
    switch the category back on, rather than give it more rows.
    """
    if from_week == to_week:
        raise InvalidWeeklyPlanAssignment(
            "from_week and to_week must differ", field="to_week"
        )
    if WeeklyPlan.objects.filter(year=year, week=to_week).exists():
        raise WeeklyPlanCopyTargetNotEmpty(
            f"Week {to_week} already has a weekly plan", field="to_week"
        )

    hidden = rows_in_inactive_categories(year, from_week)
    if hidden:
        listed = "; ".join(
            "'{name}' rows {rows}".format(
                name=entry["category_name"],
                rows=", ".join(str(index) for index in entry["row_indexes"]),
            )
            for entry in hidden
        )
        raise WeeklyPlanCopySourceCategoryInactive(
            f"Week {from_week} holds weekly-plan rows in deactivated "
            f"categories: {listed}",
            field="from_week",
            details={"categories": hidden},
        )

    blocking = rows_beyond_category_rows(year, from_week)
    if blocking:
        listed = "; ".join(
            "'{name}' rows {rows} (max_lines {max_lines})".format(
                name=entry["category_name"],
                rows=", ".join(str(index) for index in entry["row_indexes"]),
                max_lines=entry["max_lines"],
            )
            for entry in blocking
        )
        raise WeeklyPlanCopySourceRowsOutOfRange(
            f"Week {from_week} holds weekly-plan rows beyond the current row "
            f"count of their category: {listed}",
            field="from_week",
            details={"categories": blocking},
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
