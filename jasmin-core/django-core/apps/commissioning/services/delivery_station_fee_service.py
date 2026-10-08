"""Station-fee billing: what the farm owes a pickup station for a period.

A per-box fee bills the boxes delivered in the range. A monthly fee bills each
month the range touches by the share of that month's days inside it, a yearly
fee each calendar year by the share of its 365 or 366 days, so a week bills
about a quarter of a month and a whole year exactly 12 months or one year.

All amounts are NET (no VAT) and Decimal end-to-end, rounded to the cent once
per station and range, and sent on the wire as 2-decimal strings per the money
hygiene rule.
"""

from __future__ import annotations

import calendar
import datetime
import math
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.db.models import Q, QuerySet

from apps.shared.money import round_money, to_decimal

from ..models import DeliveryStation, ExternalShareDemand, ShareDelivery
from ..utils.iso_week_utils import delivery_date_from_fields
from .share_demand_service import ExternalDemandBackend, _resolve_backend

# The billed quantity is sent at this precision; the total is computed from the
# exact day fraction, so it can differ from rate × the sent quantity by a cent.
QUANTITY_PLACES = Decimal("0.0001")


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def _prorated_months(start: datetime.date, end: datetime.date) -> Fraction:
    """The months [start, end] covers, each month weighed by the share of its
    days inside the range: 5–11 October is 7/31, a whole year 12."""
    months = Fraction(0)
    month_start = start.replace(day=1)
    while month_start <= end:
        days = _days_in_month(month_start.year, month_start.month)
        month_end = month_start.replace(day=days)
        covered = (min(end, month_end) - max(start, month_start)).days + 1
        months += Fraction(covered, days)
        month_start = month_end + datetime.timedelta(days=1)
    return months


def _prorated_years(start: datetime.date, end: datetime.date) -> Fraction:
    """The calendar years [start, end] covers, each weighed by the share of its
    days (365 or 366) inside the range."""
    years = Fraction(0)
    for year in range(start.year, end.year + 1):
        year_start = max(start, datetime.date(year, 1, 1))
        year_end = min(end, datetime.date(year, 12, 31))
        years += Fraction((year_end - year_start).days + 1, _days_in_year(year))
    return years


def _times(rate: Decimal, quantity: Fraction) -> Decimal:
    """``rate × quantity`` as one Decimal division. The quantity stays an exact
    fraction until here — summing per-month Decimal quotients could land a
    hair off an exact half cent and round the wrong way."""
    product = Fraction(rate) * quantity
    return Decimal(product.numerator) / Decimal(product.denominator)


class DeliveryStationFeeService:
    @staticmethod
    def stations_with_fees() -> QuerySet[DeliveryStation]:
        """Stations that carry any non-zero net fee — the entries that appear in
        the billing (and the gate for whether the feature is shown at all)."""
        return DeliveryStation.objects.filter(
            Q(fee_per_box_net__gt=0)
            | Q(fee_per_month_net__gt=0)
            | Q(fee_per_year_net__gt=0)
        ).order_by("number", "short_name")

    @staticmethod
    def _delivered_box_lines(
        station: DeliveryStation, start: datetime.date, end: datetime.date
    ) -> list[dict]:
        """Per-(year, week) count of boxes actually delivered to ``station`` in
        [start, end]. Coarse week filter in SQL, exact-date refine in Python.

        External-CSV (import) tenants have NO ``ShareDelivery`` rows — box
        demand lives in ``ExternalShareDemand`` — so route to the aggregated
        counterpart there. Without this the per-box fee always counts 0 for a
        fee-charging import tenant."""
        if isinstance(_resolve_backend(), ExternalDemandBackend):
            return DeliveryStationFeeService._delivered_box_lines_external(
                station, start, end
            )

        years: set[int] = set()
        weeks: set[int] = set()
        day = start
        while day <= end:
            iso_year, iso_week, _ = day.isocalendar()
            years.add(iso_year)
            weeks.add(iso_week)
            day += datetime.timedelta(days=7)
        iso_year, iso_week, _ = end.isocalendar()
        years.add(iso_year)
        weeks.add(iso_week)

        counts: dict[tuple[int, int], int] = {}
        # Pull only the columns the date refine + quantity weighting need via
        # ``.values()`` — instantiating full ShareDelivery models (with two
        # joins) for a whole year's rows is the DB cost this report can't afford.
        for row in (
            ShareDelivery.objects.shippable()
            .filter(
                delivery_station_day__delivery_station=station,
                share__year__in=years,
                share__delivery_week__in=weeks,
                # Only STANDALONE (non-additional) boxes drive the per-box
                # station fee — the exact shares that consume station-day
                # capacity. An additional share (is_additional_share_type) is
                # packed into another share's box, so it occupies no slot and
                # must not be billed here either. Same gate as
                # ``get_occupied_capacity`` / the reservation service, so the fee
                # count stays in lock-step with capacity/occupancy.
                subscription__share_type_variation__share_type__is_additional_share_type=False,
            )
            .values(
                "share__year",
                "share__delivery_week",
                "share__changed_day_number",
                "share__delivery_day__day_number",
                "subscription__quantity",
            )
        ):
            date = delivery_date_from_fields(
                row["share__year"],
                row["share__delivery_week"],
                row["share__changed_day_number"],
                row["share__delivery_day__day_number"],
            )
            if date is None or not (start <= date <= end):
                continue
            # A quantity=N subscription materialises ONE ShareDelivery per week
            # but N boxes physically pass through the station — weight by
            # quantity to match demand / capacity / billing (all quantity-
            # weighted). Row-counting silently underpays multi-quantity subs.
            quantity = row["subscription__quantity"] or 1
            key = (row["share__year"], row["share__delivery_week"])
            counts[key] = counts.get(key, 0) + quantity

        return [
            {"year": year, "delivery_week": week, "boxes": boxes}
            for (year, week), boxes in sorted(counts.items())
        ]

    @staticmethod
    def _delivered_box_lines_external(
        station: DeliveryStation, start: datetime.date, end: datetime.date
    ) -> list[dict]:
        """Import-mode counterpart of :meth:`_delivered_box_lines`: box counts
        come from ``ExternalShareDemand`` (aggregated, member-less) since import
        tenants have zero ``ShareDelivery`` rows. Same standalone-only gate,
        exact-date refine, and quantity weighting — so a fee tenant on the CSV
        import bills its per-box fee instead of always 0. External demand has no
        per-share ``changed_day_number``, so the day comes from the station-day's
        delivery day. Locked by ``test_delivery_station_fee_service.py``."""
        years: set[int] = set()
        weeks: set[int] = set()
        day = start
        while day <= end:
            iso_year, iso_week, _ = day.isocalendar()
            years.add(iso_year)
            weeks.add(iso_week)
            day += datetime.timedelta(days=7)
        iso_year, iso_week, _ = end.isocalendar()
        years.add(iso_year)
        weeks.add(iso_week)

        counts: dict[tuple[int, int], int] = {}
        for row in ExternalShareDemand.objects.filter(
            delivery_station_day__delivery_station=station,
            year__in=years,
            delivery_week__in=weeks,
            # Same standalone-only gate as the subscription path: an
            # additional (packed-along) share rides in another box, takes no
            # station slot, and must not be billed per-box.
            share_type_variation__share_type__is_additional_share_type=False,
        ).values(
            "year",
            "delivery_week",
            "delivery_station_day__delivery_day__day_number",
            "quantity",
        ):
            date = delivery_date_from_fields(
                row["year"],
                row["delivery_week"],
                None,
                row["delivery_station_day__delivery_day__day_number"],
            )
            if date is None or not (start <= date <= end):
                continue
            key = (row["year"], row["delivery_week"])
            counts[key] = counts.get(key, 0) + row["quantity"]

        return [
            {"year": year, "delivery_week": week, "boxes": boxes}
            for (year, week), boxes in sorted(counts.items())
        ]

    @staticmethod
    def compute_fees(
        station: DeliveryStation, start: datetime.date, end: datetime.date
    ) -> dict:
        """Owed-amount breakdown for one station over [start, end]."""
        box_rate = station.fee_per_box_net
        month_rate = station.fee_per_month_net
        year_rate = station.fee_per_year_net

        lines: list[dict] = []
        quantity = Fraction(0)
        if box_rate > 0:
            lines = DeliveryStationFeeService._delivered_box_lines(station, start, end)
            quantity = Fraction(sum(line["boxes"] for line in lines))
            fee_type, rate, unit = "per_box", box_rate, "boxes"
        elif month_rate > 0:
            quantity = _prorated_months(start, end)
            fee_type, rate, unit = "per_month", month_rate, "months"
        elif year_rate > 0:
            quantity = _prorated_years(start, end)
            fee_type, rate, unit = "per_year", year_rate, "years"
        else:
            rate, fee_type, unit = Decimal("0"), "none", ""

        rate = to_decimal(rate)
        return {
            "delivery_station": station.id,
            "delivery_station_name": station.short_name,
            "start_date": start,
            "end_date": end,
            "fee_type": fee_type,
            # Whole units for clients that read an integer count: the prorated
            # quantity rounded up, so a part of a month reads as one month.
            "quantity": math.ceil(quantity),
            "billed_quantity": _times(Decimal(1), quantity).quantize(
                QUANTITY_PLACES, rounding=ROUND_HALF_UP
            ),
            "quantity_unit": unit,
            "rate_net": str(round_money(rate)),
            "total_net": str(round_money(_times(rate, quantity))),
            "lines": lines,
        }

    @staticmethod
    def compute_all(
        start: datetime.date, end: datetime.date, station_id: str | None = None
    ) -> list[dict]:
        """Billing for every fee-carrying station (or a single one)."""
        stations = DeliveryStationFeeService.stations_with_fees()
        if station_id:
            stations = stations.filter(id=station_id)
        return [
            DeliveryStationFeeService.compute_fees(station, start, end)
            for station in stations
        ]
