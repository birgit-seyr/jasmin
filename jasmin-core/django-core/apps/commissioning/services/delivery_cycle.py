"""Delivery-cycle cadence — which delivery weeks a ``ShareType.delivery_cycle``
actually keeps.

Until now ``delivery_cycle`` was descriptive/UI-only: subscriptions materialised
a ``ShareDelivery`` EVERY delivery week regardless of the configured cycle, so an
ODD_WEEKS / every-4-weeks share still got a weekly delivery (and weekly billing,
since billing is delivery-driven). This module is the single place that reduces
the full weekly cadence to the cycle's real delivery weeks.

Every cycle is **calendar-anchored** on the ISO week NUMBER — ``week % N == R`` —
so the schedule is identical for every subscription (no per-subscription phase),
which is what lets a farm split members across weeks:

    WEEKLY          → every week
    ODD_WEEKS       → week % 2 == 1   (weeks 1, 3, 5, …)
    EVEN_WEEKS      → week % 2 == 0   (weeks 2, 4, 6, …)
    ALL_THREE_WEEKS → week % 3 == 1   (weeks 1, 4, 7, …)
    ALL_FOUR_WEEKS  → week % 4 == 1   (weeks 1, 5, 9, …)

Year-boundary caveat: ISO years have 52 OR 53 weeks, and neither divides evenly
by 3. So the rhythm can shorten by a week across New Year — ALL_FOUR_WEEKS only in
a 53-week year (like odd/even already do), ALL_THREE_WEEKS every year (52 % 3 = 1,
so weeks …49, 52 then next year's 1 land one week apart). A *perfectly* regular
3-week rhythm would need a continuous week count off a fixed epoch, at the cost of
this intuitive "weeks 1, 4, 7" alignment; the calendar anchoring is the deliberate
trade-off. (Month-based cycles were dropped — "monthly" needs its own
day-of-month field to reflect a tenant's business logic; see docs/todos.)
"""

from apps.commissioning.models.choices import DeliveryCycleOptions

YearWeek = tuple[int, int]

# ISO-week-number modulo: keep weeks where ``isoweek % divisor == remainder``.
# ODD/EVEN are the 2-week split; ALL_THREE/ALL_FOUR extend the same idea.
_WEEK_MODULO: dict[str, tuple[int, int]] = {
    DeliveryCycleOptions.ODD_WEEKS: (2, 1),
    DeliveryCycleOptions.EVEN_WEEKS: (2, 0),
    DeliveryCycleOptions.ALL_THREE_WEEKS: (3, 1),
    DeliveryCycleOptions.ALL_FOUR_WEEKS: (4, 1),
}


def filter_weeks_by_delivery_cycle(
    weeks: list[YearWeek], delivery_cycle: str | None
) -> list[YearWeek]:
    """Reduce the full weekly delivery-week list to the weeks *delivery_cycle*
    keeps, by ISO-week-number modulo.

    ``weeks`` is the full weekly cadence — a list of ``(iso_year, iso_week)`` — as
    produced by ``SubscriptionService._get_delivery_weeks``.

    - ``WEEKLY`` / ``None`` / ``""`` / unknown → every week (safe default; legacy
      rows without an explicit cycle keep today's weekly behaviour).
    - ``ODD_WEEKS`` / ``EVEN_WEEKS`` / ``ALL_THREE_WEEKS`` / ``ALL_FOUR_WEEKS`` →
      ``isoweek % N == R`` per ``_WEEK_MODULO`` (weeks 1,3,…/2,4,…/1,4,…/1,5,…).
    """
    if not weeks:
        return weeks
    modulo = _WEEK_MODULO.get(delivery_cycle or "")
    if modulo is None:
        return weeks  # WEEKLY, None, "", or any unrecognised value → weekly.
    divisor, remainder = modulo
    return [year_week for year_week in weeks if year_week[1] % divisor == remainder]
