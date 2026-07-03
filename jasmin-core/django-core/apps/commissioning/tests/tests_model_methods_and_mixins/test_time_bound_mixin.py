"""Tests for TimeBoundMixin — week boundaries, date range, overlap, succession."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.commissioning.tests.factories import (
    SharesDeliveryDayFactory,
)


# ---------------------------------------------------------------------------
# validate_week_boundaries
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidateWeekBoundaries:
    def test_valid_from_monday_passes(self, tenant):
        monday = datetime.date(2026, 4, 6)  # Monday
        sdd = SharesDeliveryDayFactory.build(day_number=2, valid_from=monday)
        sdd.validate_week_boundaries(
            sdd.valid_from, sdd.valid_until
        )  # should not raise

    def test_valid_from_non_monday_raises(self, tenant):
        tuesday = datetime.date(2026, 4, 7)  # Tuesday
        sdd = SharesDeliveryDayFactory.build(day_number=2, valid_from=tuesday)
        with pytest.raises(ValidationError, match="Monday"):
            sdd.validate_week_boundaries(sdd.valid_from, sdd.valid_until)

    def test_valid_until_sunday_passes(self, tenant):
        monday = datetime.date(2026, 4, 6)
        sunday = datetime.date(2026, 4, 12)  # Sunday
        sdd = SharesDeliveryDayFactory.build(
            day_number=2, valid_from=monday, valid_until=sunday
        )
        sdd.validate_week_boundaries(sdd.valid_from, sdd.valid_until)

    def test_valid_until_non_sunday_raises(self, tenant):
        monday = datetime.date(2026, 4, 6)
        saturday = datetime.date(2026, 4, 11)  # Saturday
        sdd = SharesDeliveryDayFactory.build(
            day_number=2, valid_from=monday, valid_until=saturday
        )
        with pytest.raises(ValidationError, match="Sunday"):
            sdd.validate_week_boundaries(sdd.valid_from, sdd.valid_until)

    def test_valid_until_none_passes(self, tenant):
        monday = datetime.date(2026, 4, 6)
        sdd = SharesDeliveryDayFactory.build(
            day_number=2, valid_from=monday, valid_until=None
        )
        sdd.validate_week_boundaries(sdd.valid_from, sdd.valid_until)


# ---------------------------------------------------------------------------
# validate_date_range
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidateDateRange:
    def test_valid_until_after_valid_from_passes(self, tenant):
        sdd = SharesDeliveryDayFactory.build(
            day_number=2,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        sdd.validate_date_range(sdd.valid_from, sdd.valid_until)

    def test_valid_until_before_valid_from_raises(self, tenant):
        sdd = SharesDeliveryDayFactory.build(
            day_number=2,
            valid_from=datetime.date(2026, 6, 1),
            valid_until=datetime.date(2026, 1, 4),
        )
        with pytest.raises(ValidationError, match="End date"):
            sdd.validate_date_range(sdd.valid_from, sdd.valid_until)

    def test_same_date_passes(self, tenant):
        d = datetime.date(2026, 4, 6)  # Monday
        sdd = SharesDeliveryDayFactory.build(day_number=2, valid_from=d, valid_until=d)
        sdd.validate_date_range(sdd.valid_from, sdd.valid_until)


# ---------------------------------------------------------------------------
# _validate_no_overlap
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidateNoOverlap:
    def test_non_overlapping_passes(self, tenant):
        SharesDeliveryDayFactory(
            day_number=2,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 3, 29),
        )
        new = SharesDeliveryDayFactory.build(
            day_number=2,
            valid_from=datetime.date(2026, 3, 30),
        )
        new._validate_no_overlap()  # should not raise

    def test_overlapping_raises(self, tenant):
        SharesDeliveryDayFactory(
            day_number=2,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        new = SharesDeliveryDayFactory.build(
            day_number=2,
            valid_from=datetime.date(2026, 3, 30),
        )
        with pytest.raises(ValidationError, match="Overlapping"):
            new._validate_no_overlap()

    def test_open_ended_overlap_detected(self, tenant):
        SharesDeliveryDayFactory(
            day_number=2,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,  # open-ended
        )
        new = SharesDeliveryDayFactory.build(
            day_number=2,
            valid_from=datetime.date(2026, 6, 1),
        )
        with pytest.raises(ValidationError, match="Overlapping"):
            new._validate_no_overlap()

    def test_different_group_allowed(self, tenant):
        SharesDeliveryDayFactory(
            day_number=2,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )
        # day_number=3 is a different group
        new = SharesDeliveryDayFactory.build(
            day_number=3,
            valid_from=datetime.date(2026, 1, 5),
        )
        new._validate_no_overlap()  # should not raise


# ---------------------------------------------------------------------------
# handle_succession
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHandleSuccession:
    def test_closes_existing_open_record(self, tenant):
        from apps.commissioning.models import SharesDeliveryDay

        existing = SharesDeliveryDayFactory(
            day_number=2,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=None,
        )

        closed = SharesDeliveryDay.handle_succession(
            {"day_number": 2, "valid_from": datetime.date(2026, 6, 1)}
        )

        assert closed is not None
        existing.refresh_from_db()
        assert existing.valid_until == datetime.date(2026, 5, 31)

    def test_returns_none_when_nothing_to_succeed(self, tenant):
        from apps.commissioning.models import SharesDeliveryDay

        result = SharesDeliveryDay.handle_succession(
            {"day_number": 5, "valid_from": datetime.date(2026, 6, 1)}
        )
        assert result is None

    def test_raises_without_valid_from(self, tenant):
        from apps.commissioning.models import SharesDeliveryDay

        with pytest.raises(ValueError, match="valid_from"):
            SharesDeliveryDay.handle_succession({"day_number": 2})

    def test_raises_when_new_starts_before_predecessor(self, tenant):
        from apps.commissioning.errors import SuccessionStartBeforePredecessor
        from apps.commissioning.models import SharesDeliveryDay

        SharesDeliveryDayFactory(
            day_number=2,
            valid_from=datetime.date(2026, 6, 1),
            valid_until=None,
        )

        # New valid_from (2026-01-05) is BEFORE the existing open record's
        # valid_from (2026-06-01) — closing the predecessor at new - 1 day would
        # give it an end date before its own start, so a clear error is raised
        # rather than the confusing predecessor-row ValidationError.
        with pytest.raises(SuccessionStartBeforePredecessor):
            SharesDeliveryDay.handle_succession(
                {"day_number": 2, "valid_from": datetime.date(2026, 1, 5)}
            )

    def test_save_rolls_back_predecessor_close_on_full_clean_failure(self, tenant):
        """SUC-1: save() closes the predecessor (handle_succession) THEN runs
        full_clean(). If full_clean fails, the close must roll back — a TimeBound
        slot must never be left with a closed predecessor and no successor."""
        from apps.commissioning.models import SharesDeliveryDay

        monday = datetime.date(2026, 4, 6)  # Monday
        pred = SharesDeliveryDayFactory(
            day_number=2, valid_from=monday, valid_until=None
        )
        assert pred.valid_until is None

        succ_from = datetime.date(2026, 4, 20)  # Monday (+2 weeks)
        bad_until = datetime.date(2026, 4, 25)  # Saturday — NOT a Sunday
        # handle_succession closes `pred` at succ_from-1 (a valid Sunday); the
        # successor's OWN full_clean then rejects the non-Sunday valid_until.
        with pytest.raises(ValidationError):
            SharesDeliveryDayFactory(
                day_number=2, valid_from=succ_from, valid_until=bad_until
            )

        pred.refresh_from_db()
        assert pred.valid_until is None, (
            "predecessor close must roll back when the successor's full_clean "
            "fails — no closed-predecessor-without-successor"
        )
        # No second row persisted either.
        assert SharesDeliveryDay.objects.filter(day_number=2).count() == 1
