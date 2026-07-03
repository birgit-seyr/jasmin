"""Object scoping for the payments app.

Members may only see their own BillingProfile / ChargeSchedule.
BillingRun is staff-only (see viewsets.py permission classes).
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.authz.scoping import scope_by_user_attr


def scope_to_member(qs: QuerySet, request, *, path: str) -> QuerySet:
    """Restrict `qs` to rows owned by the caller's `member_profile`."""
    return scope_by_user_attr(qs, request, user_attr="member_profile", path=path)
