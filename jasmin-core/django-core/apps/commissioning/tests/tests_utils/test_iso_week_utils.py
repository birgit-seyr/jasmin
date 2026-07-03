"""Unit tests for the ISO-week + weekday-alignment helpers (REF-9 / REF-10).

Pure date math — no DB. The boundary cases that matter are the 52/53→1 ISO
rollover (2026 is a 53-week ISO year) and the on-target weekday no-ops.
"""

from __future__ import annotations

import datetime as dt

from apps.commissioning.utils.iso_week_utils import (
    iso_week_range,
    next_iso_week,
    next_monday,
    next_sunday,
    previous_monday,
)


class TestNextIsoWeek:
    def test_within_year(self):
        assert next_iso_week(2026, 10) == (2026, 11)

    def test_53_week_year_rollover(self):
        # 2026 is a 53-week ISO year — week 52 → 53 (NOT → next year).
        assert next_iso_week(2026, 52) == (2026, 53)
        assert next_iso_week(2026, 53) == (2027, 1)

    def test_standard_year_end(self):
        # 2024 has 52 ISO weeks.
        assert next_iso_week(2024, 52) == (2025, 1)


class TestIsoWeekRange:
    def test_simple_range(self):
        assert iso_week_range(2026, 10, 3) == [(2026, 10), (2026, 11), (2026, 12)]

    def test_crosses_53_week_year_boundary(self):
        assert iso_week_range(2026, 52, 3) == [(2026, 52), (2026, 53), (2027, 1)]

    def test_zero_weeks_is_empty(self):
        assert iso_week_range(2026, 10, 0) == []


class TestWeekdayAlignment:
    # 2026-06-24 is a Wednesday; the surrounding Monday/Sunday are 06-22 / 06-28.
    WED = dt.date(2026, 6, 24)
    MON = dt.date(2026, 6, 22)
    SUN = dt.date(2026, 6, 28)
    NEXT_MON = dt.date(2026, 6, 29)

    def test_next_monday_from_midweek(self):
        assert next_monday(self.WED) == self.NEXT_MON

    def test_next_monday_idempotent_on_monday(self):
        assert next_monday(self.MON) == self.MON

    def test_next_sunday_from_midweek(self):
        assert next_sunday(self.WED) == self.SUN

    def test_next_sunday_idempotent_on_sunday(self):
        assert next_sunday(self.SUN) == self.SUN

    def test_previous_monday_from_midweek(self):
        assert previous_monday(self.WED) == self.MON

    def test_previous_monday_idempotent_on_monday(self):
        assert previous_monday(self.MON) == self.MON
