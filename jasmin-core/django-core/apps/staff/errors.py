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
