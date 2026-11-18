from __future__ import annotations

from datetime import date, timedelta

from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.shared.iso_week_filters import iso_week_bound

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


def before_day_q(day: date) -> Q:
    """The documentation rows (``year``, ``delivery_week``, ``day_number``, an
    ISO year and week) of a day before ``day``. A row without a day counts as
    before it only from an earlier week."""
    iso = day.isocalendar()
    return iso_week_bound((iso.year, iso.week), "lt") | Q(
        year=iso.year, delivery_week=iso.week, day_number__lt=iso.weekday - 1
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

    Subclasses say what "older" means in ``_recent_q``.
    """

    def __init__(self, archive_months: int = CUT_OFF_MONTHS) -> None:
        super().__init__()
        self.archive_months: int = archive_months

    def _recent_q(self) -> Q:
        raise NotImplementedError

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().filter(self._recent_q())

    def for_period(self, is_past: bool = False) -> QuerySet:
        """Single entry point for views/services.

        ``is_past=False`` (default) → fast, recent-only queryset.
        ``is_past=True`` → unfiltered queryset, including archived records.
        """
        if is_past:
            return super().get_queryset()
        return self.get_queryset()


class DeliveryWeekActiveOnlyManager(_ArchiveCutoffManager):
    """Default queryset = records of a delivery week no older than the cutoff.

    The week a record is for decides, not when it was written: share contents,
    forecasts and the amounts planned from them are entered months ahead and
    must still be in their week's lists when that week comes. The model names
    the relation that carries ``year`` / ``delivery_week`` in
    ``archive_week_of`` (empty when it carries them itself).
    """

    def _recent_q(self) -> Q:
        week_of: str = getattr(self.model, "archive_week_of", "")
        prefix = f"{week_of}__" if week_of else ""
        return iso_week_bound(
            archive_cutoff_week(self.archive_months), "gte", prefix=prefix
        )


def archive_cutoff_week(archive_months: int = CUT_OFF_MONTHS) -> tuple[int, int]:
    """The ISO year and week of the oldest delivery week still current."""
    cutoff = timezone.localdate() - timedelta(days=CUT_OFF_DAYS * archive_months)
    iso = cutoff.isocalendar()
    return iso.year, iso.week


class DateActiveOnlyManager(_ArchiveCutoffManager):
    """Default queryset = records with ``date`` newer than the cutoff."""

    def _recent_q(self) -> Q:
        cutoff = timezone.now() - timedelta(days=CUT_OFF_DAYS * self.archive_months)
        return Q(date__gte=cutoff)
