"""Shared finalization helpers."""

from __future__ import annotations

from django.db.models import Manager, QuerySet


def finalize_children(
    *querysets: Manager | QuerySet,
    user=None,
) -> None:
    """Finalize all un-finalized objects in the given querysets.

    No ``is_finalized`` pre-check here — that would be a check-then-call TOCTOU
    (the child can be finalized by another request between the read and the
    call). ``finalize()`` owns the decision atomically: it locks the row and
    re-checks under the lock, returning ``False`` (a no-op) for an already
    finalized child. So calling it unconditionally is both correct and
    race-safe.
    """
    for qs in querysets:
        for child in qs.all():
            child.finalize(user=user)
