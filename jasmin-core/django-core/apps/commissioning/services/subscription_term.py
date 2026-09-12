"""ISO-week-anchored subscription term-end computation.

Backend mirror of the frontend ``computeValidUntil`` (``endOfTerm.ts``), used by
the auto-renewal path so a renewal RE-ANCHORS its term end to an ISO WEEK rather
than preserving the predecessor's raw timedelta. Anchoring to a week (not a fixed
+52 weeks / +364 days) keeps the yearly restart week stable across 52- and
53-week ISO years: a 53-week year yields a 53-delivery term instead of silently
shifting the next term's start back by one week.
"""

from __future__ import annotations

import datetime

from isoweek import Week


def _sunday_before_iso_week(year: int, week: int) -> datetime.date:
    """The Sunday immediately before Monday of ISO ``week`` in ``year`` — a term
    ending the day before that week opens.

    A ``week`` beyond the year's last ISO week (e.g. week 53 in a 52-week year)
    rolls forward into the following year, IDENTICALLY to the frontend dayjs
    construction ``.isoWeek(week).isoWeekday(1).subtract(1, "day")`` (both the
    ``isoweek`` library and dayjs overflow the same way), so create (frontend)
    and renewal (here) stay in lock-step on that rare edge.
    """
    return Week(year, week).monday() - datetime.timedelta(days=1)


def _sunday_of_iso_week(year: int, week: int) -> datetime.date:
    """The Sunday (last day) of ISO ``week`` in ``year``."""
    return Week(year, week).sunday()


def compute_term_valid_until(
    valid_from: datetime.date,
    *,
    end_at_end_of_season: bool,
    end_after_one_year: bool,
    season_start_week: int | None,
) -> datetime.date | None:
    """ISO-week-anchored ``valid_until`` for a term starting on ``valid_from``
    (always a Monday), mirroring the frontend ``computeValidUntil`` season +
    one-year branches. The trial branch is intentionally omitted — renewals are
    never trials (``find_renewable_subscriptions`` excludes ``is_trial``).

    Returns ``None`` when neither mode is configured; the caller then keeps the
    predecessor's term length (unchanged legacy behaviour for such tenants).
    """
    iso_year, iso_week, _ = valid_from.isocalendar()

    if (
        end_at_end_of_season
        and season_start_week is not None
        and 1 <= int(season_start_week) <= 53
    ):
        season_week = int(season_start_week)
        # Joined in / after this year's season -> end just before NEXT year's
        # season opens. For a normal renewal ``valid_from`` IS the season Monday
        # (predecessor ended the day before), so this is the branch taken.
        if iso_week >= season_week:
            return _sunday_before_iso_week(iso_year + 1, season_week)
        # Late join in the prior season's window -> end on this year's season
        # Sunday. Mirrors the frontend's ``validFromWeek < seasonStartWeek`` case.
        return _sunday_of_iso_week(iso_year, season_week)

    if end_after_one_year:
        # Same ISO week, next ISO year, minus a day.
        return _sunday_before_iso_week(iso_year + 1, iso_week)

    return None
