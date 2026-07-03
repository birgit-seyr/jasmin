from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone

from ..constants import CUT_OFF_DAYS, CUT_OFF_MONTHS


def active_on_date_q(target_date: date, *, prefix: str = "") -> Q:
    """The canonical time-bound "active / priced on ``target_date``" window:
    ``valid_from <= date`` AND (``valid_until`` IS NULL OR ``>= date``).

    Newest-effective-wins is the caller's job (``order_by('-valid_from')``).
    ``prefix`` targets a relation for subquery / reverse-relation callers, e.g.
    ``active_on_date_q(d, prefix="pricing")`` →
    ``pricing__valid_from__lte=…`` etc. Single source of truth for the window —
    keep it here so a future semantics change (inclusive vs exclusive
    ``valid_until``, a soft-delete flag) lands in exactly one place."""
    p = f"{prefix}__" if prefix else ""
    return Q(
        Q(**{f"{p}valid_until__isnull": True})
        | Q(**{f"{p}valid_until__gte": target_date}),
        **{f"{p}valid_from__lte": target_date},
    )


class CurrentActiveManagerMixin:
    """Mixin that adds current-active filtering to any Manager."""

    def _get_date_range_filter(self, target_date: date) -> Q:
        return active_on_date_q(target_date)

    def active_at_date(self, target_date: date) -> QuerySet:
        """Get objects active for a specific date."""
        return self.filter(self._get_date_range_filter(target_date))

    def active_at_date_or_future(self, target_date: date) -> QuerySet:
        """Get objects that are currently active OR will become active."""
        return self.filter(
            self._get_date_range_filter(target_date) | Q(valid_from__gt=target_date),
        )


class CurrentActiveManager(CurrentActiveManagerMixin, models.Manager):
    """Manager that provides active filtering methods."""

    pass


class _ArchiveCutoffManager(models.Manager):
    """Base for managers that hide records older than ``archive_months``.

    Subclasses must set ``cutoff_field`` to the model field used for the cutoff
    (e.g. ``"created_at"`` or ``"date"``).
    """

    cutoff_field: str = ""

    def __init__(self, archive_months: int = CUT_OFF_MONTHS) -> None:
        super().__init__()
        self.archive_months: int = archive_months

    def _cutoff(self) -> datetime:
        return timezone.now() - timedelta(days=CUT_OFF_DAYS * self.archive_months)

    def get_queryset(self) -> QuerySet:
        return (
            super()
            .get_queryset()
            .filter(**{f"{self.cutoff_field}__gte": self._cutoff()})
        )

    def for_period(self, is_past: bool = False) -> QuerySet:
        """Single entry point for views/services.

        ``is_past=False`` (default) → fast, recent-only queryset.
        ``is_past=True`` → unfiltered queryset, including archived records.
        """
        if is_past:
            return super().get_queryset()
        return self.get_queryset()


class ActiveOnlyManager(_ArchiveCutoffManager):
    """Default queryset = records with ``created_at`` newer than the cutoff."""

    cutoff_field = "created_at"


class DateActiveOnlyManager(_ArchiveCutoffManager):
    """Default queryset = records with ``date`` newer than the cutoff."""

    cutoff_field = "date"
