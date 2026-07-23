"""Unit tests for the ISO-week-anchored term-end computation.

Pure function — no DB / tenant needed. Mirrors the frontend
``endOfTerm.test.ts`` assertions so create (frontend) and renewal (backend) stay
in lock-step.
"""

from __future__ import annotations

import datetime

from isoweek import Week

from apps.commissioning.services.subscription_term import compute_term_valid_until

_ONE_YEAR = dict(
    end_at_end_of_season=False,
    end_after_one_year=True,
    season_start_week=None,
)


class TestOneYearMode:
    def test_anchors_to_same_iso_week_next_year(self):
        # 2026-04-06 is ISO 2026-W15 → ends the day before Monday of W15 2027.
        result = compute_term_valid_until(datetime.date(2026, 4, 6), **_ONE_YEAR)
        assert result == datetime.date(2027, 4, 11)
        assert result.isoweekday() == 7  # Sunday

    def test_restart_week_stable_across_53_week_year(self):
        # 2026 is a 53-week ISO year. Start ISO 2026-W26; the next term must
        # restart on W26 — a fixed +364 days would drift it to W25.
        valid_from = datetime.date(2026, 6, 22)  # Monday, ISO 2026-W26
        result = compute_term_valid_until(valid_from, **_ONE_YEAR)
        assert result == datetime.date(2027, 6, 27)
        next_start = result + datetime.timedelta(days=1)
        assert next_start.isocalendar()[1] == 26  # same ISO week
        assert next_start.isoweekday() == 1  # Monday

    def test_iso_week_53_start_overflows_to_next_year(self):
        # 2026-12-28 is ISO 2026-W53; 2027 has no W53 → rolls to 2028-01-02,
        # identical to the frontend dayjs construction.
        result = compute_term_valid_until(datetime.date(2026, 12, 28), **_ONE_YEAR)
        assert result == datetime.date(2028, 1, 2)
        assert result.isoweekday() == 7

    def test_none_when_no_mode_configured(self):
        assert (
            compute_term_valid_until(
                datetime.date(2026, 6, 22),
                end_at_end_of_season=False,
                end_after_one_year=False,
                season_start_week=None,
            )
            is None
        )


class TestEndOfSeasonMode:
    def test_join_in_season_ends_before_next_season(self):
        # valid_from is the season Monday (W26) → ends the day before next
        # year's season opens.
        result = compute_term_valid_until(
            datetime.date(2026, 6, 22),
            end_at_end_of_season=True,
            end_after_one_year=False,
            season_start_week=26,
        )
        assert result == datetime.date(2027, 6, 27)
        assert result.isoweekday() == 7

    def test_late_join_ends_on_this_year_season_sunday(self):
        # valid_from BEFORE the season week → ends on THIS year's season Sunday.
        result = compute_term_valid_until(
            datetime.date(2026, 3, 2),  # ISO 2026-W10
            end_at_end_of_season=True,
            end_after_one_year=False,
            season_start_week=26,
        )
        assert result == Week(2026, 26).sunday()
        assert result.isoweekday() == 7

    def test_season_takes_priority_over_one_year(self):
        result = compute_term_valid_until(
            datetime.date(2026, 6, 22),
            end_at_end_of_season=True,
            end_after_one_year=True,
            season_start_week=26,
        )
        assert result == datetime.date(2027, 6, 27)

    def test_invalid_season_week_falls_through_to_one_year(self):
        # An out-of-range season week is ignored; the one-year branch wins.
        result = compute_term_valid_until(
            datetime.date(2026, 6, 22),
            end_at_end_of_season=True,
            end_after_one_year=True,
            season_start_week=0,
        )
        assert result == datetime.date(2027, 6, 27)
