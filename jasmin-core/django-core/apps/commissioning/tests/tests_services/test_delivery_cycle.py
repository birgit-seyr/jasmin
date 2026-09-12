"""Unit tests for the delivery-cycle cadence filter (pure function, no DB).

Pins which delivery weeks each ``ShareType.delivery_cycle`` keeps out of the full
weekly cadence — all calendar-anchored on the ISO week number. See
services/delivery_cycle.py.
"""

from apps.commissioning.models.choices import DeliveryCycleOptions as DC
from apps.commissioning.services.delivery_cycle import filter_weeks_by_delivery_cycle


def _weeks(year: int, start: int, n: int) -> list[tuple[int, int]]:
    return [(year, w) for w in range(start, start + n)]


class TestFilterWeeksByDeliveryCycle:
    def test_weekly_blank_and_unknown_keep_every_week(self):
        weeks = _weeks(2026, 10, 5)
        assert filter_weeks_by_delivery_cycle(weeks, DC.WEEKLY) == weeks
        assert filter_weeks_by_delivery_cycle(weeks, None) == weeks
        assert filter_weeks_by_delivery_cycle(weeks, "") == weeks
        assert filter_weeks_by_delivery_cycle(weeks, "SOMETHING_ELSE") == weeks

    def test_odd_weeks_is_iso_week_mod_2_eq_1(self):
        weeks = _weeks(2026, 1, 8)  # 1..8
        assert filter_weeks_by_delivery_cycle(weeks, DC.ODD_WEEKS) == [
            (2026, 1),
            (2026, 3),
            (2026, 5),
            (2026, 7),
        ]

    def test_even_weeks_is_iso_week_mod_2_eq_0(self):
        weeks = _weeks(2026, 1, 8)  # 1..8
        assert filter_weeks_by_delivery_cycle(weeks, DC.EVEN_WEEKS) == [
            (2026, 2),
            (2026, 4),
            (2026, 6),
            (2026, 8),
        ]

    def test_all_three_weeks_is_iso_week_mod_3_eq_1(self):
        # weeks 1, 4, 7, 10 …
        weeks = _weeks(2026, 1, 12)  # 1..12
        assert filter_weeks_by_delivery_cycle(weeks, DC.ALL_THREE_WEEKS) == [
            (2026, 1),
            (2026, 4),
            (2026, 7),
            (2026, 10),
        ]

    def test_all_four_weeks_is_iso_week_mod_4_eq_1(self):
        # weeks 1, 5, 9 …
        weeks = _weeks(2026, 1, 12)  # 1..12
        assert filter_weeks_by_delivery_cycle(weeks, DC.ALL_FOUR_WEEKS) == [
            (2026, 1),
            (2026, 5),
            (2026, 9),
        ]

    def test_cadence_is_calendar_anchored_not_from_subscription_start(self):
        # A subscription starting on a non-matching week: the first delivery is
        # the first week that satisfies the modulo (week 4 for ALL_THREE_WEEKS),
        # NOT the subscription's own first week (3).
        weeks = _weeks(2026, 3, 6)  # 3,4,5,6,7,8
        assert filter_weeks_by_delivery_cycle(weeks, DC.ALL_THREE_WEEKS) == [
            (2026, 4),
            (2026, 7),
        ]

    def test_parity_across_year_boundary(self):
        # A 53-week year: week 53 (odd) then next year's week 1 (odd) both stay.
        weeks = [(2026, 52), (2026, 53), (2027, 1), (2027, 2)]
        assert filter_weeks_by_delivery_cycle(weeks, DC.ODD_WEEKS) == [
            (2026, 53),
            (2027, 1),
        ]
        assert filter_weeks_by_delivery_cycle(weeks, DC.EVEN_WEEKS) == [
            (2026, 52),
            (2027, 2),
        ]

    def test_empty_input(self):
        assert filter_weeks_by_delivery_cycle([], DC.ODD_WEEKS) == []
