"""Domain errors raised by the staff app.

Translated to HTTP responses by ``core.exception_handler`` — viewsets do not
need to catch them. Subclass the closest ``core.errors`` base; add new ones
freely when a new failure mode appears.
"""

from __future__ import annotations

from core.errors import BadRequestError, ConflictError, NotFoundError


class StaffError(BadRequestError):
    """Base for any staff-domain validation failure (400)."""

    code = "staff.invalid"


class EmployeeNotFound(NotFoundError):
    """An assignment referenced an employee id that does not exist."""

    code = "staff.employee_not_found"


class WeeklyPlanCategoryNotFound(NotFoundError):
    """An assignment referenced a weekly-plan category id that does not exist."""

    code = "staff.weekly_plan_category_not_found"


class InvalidWeeklyPlanAssignment(BadRequestError):
    """A weekly-plan assignment is malformed — row_index out of the category's
    range, or two assignments target the same (category, row, day) cell."""

    code = "staff.invalid_weekly_plan_assignment"


class WeeklyPlanCopyTargetNotEmpty(ConflictError):
    """Copy refused because the target week already holds weekly-plan rows —
    copying would silently merge two plans. Clear the target week first."""

    code = "staff.weekly_plan_copy_target_not_empty"


class WeeklyPlanCopySourceRowsOutOfRange(ConflictError):
    """Copy refused because the source week holds rows at a ``row_index`` at or
    beyond their category's ``max_lines``. Such rows sit at no position the grid
    renders, so copying them into an editable week hides them there and the next
    whole-week replace deletes them. Raise the category's ``max_lines`` or clear
    the rows in the source week."""

    code = "staff.weekly_plan_copy_source_rows_out_of_range"


class WeeklyPlanCopySourceCategoryInactive(ConflictError):
    """Copy refused because the source week holds rows in a category that is
    deactivated. The grid renders active categories only, so every row of such
    a category sits at no position the target week shows and the next
    whole-week replace deletes it. Reactivate the category or clear its rows in
    the source week."""

    code = "staff.weekly_plan_copy_source_category_inactive"


class WeeklyPlanCategoryShrinkBlocked(ConflictError):
    """``max_lines`` cannot be lowered while weekly-plan entries sit in the rows
    that would disappear. Those rows stay in the database, vanish from the grid
    and are still carried along by a week copy, so the lowering is refused until
    they are cleared."""

    code = "staff.weekly_plan_category_shrink_blocked"


class EmployeeInUse(ConflictError):
    """An employee cannot be deleted while weekly-plan cells, absences or
    employments still reference them — a delete would CASCADE all of those
    away. Deactivate the employee instead."""

    code = "staff.employee_in_use"


class WeeklyPlanCategoryInUse(ConflictError):
    """A weekly-plan category cannot be deleted while weekly-plan cells use it
    — a delete would CASCADE them away. Deactivate the category instead."""

    code = "staff.weekly_plan_category_in_use"


class AbsenceCategoryInUse(ConflictError):
    """An absence category cannot be deleted while absences use it — a delete
    would CASCADE them away. Deactivate the category instead."""

    code = "staff.absence_category_in_use"
