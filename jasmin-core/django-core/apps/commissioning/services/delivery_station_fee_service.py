"""Station-fee billing: what the solawi owes a pickup station for a period.



All amounts are NET (no VAT) and Decimal end-to-end; sent on the wire as
2-decimal strings per the money hygiene rule.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.db.models import Q, QuerySet

from ..models import DeliveryStation, ExternalShareDemand, ShareDelivery
from ..utils.iso_week_utils import delivery_date_from_fields
from .share_demand_service import ExternalDemandBackend, _resolve_backend

_CENT = Decimal("0.01")


def _calendar_months(start: datetime.date, end: datetime.date) -> int:
    """Distinct calendar months the range overlaps, inclusive (Jul 15 → Aug 20
    = 2). For a per-month fee the office should pick month-aligned ranges."""
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _calendar_years(start: datetime.date, end: datetime.date) -> int:
    """Distinct calendar years the range overlaps, inclusive."""
    return end.year - start.year + 1


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
        fee-charging import tenant (the box-matrix bug class, but for money)."""
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
            counts[key] = counts.get(key, 0) + (row["quantity"] or 0)

        return [
            {"year": year, "delivery_week": week, "boxes": boxes}
            for (year, week), boxes in sorted(counts.items())
        ]

    @staticmethod
    def compute_fees(
        station: DeliveryStation, start: datetime.date, end: datetime.date
    ) -> dict:
        """Owed-amount breakdown for one station over [start, end]."""
        box_rate = station.fee_per_box_net or Decimal("0")
        month_rate = station.fee_per_month_net or Decimal("0")
        year_rate = station.fee_per_year_net or Decimal("0")

        lines: list[dict] = []
        if box_rate > 0:
            lines = DeliveryStationFeeService._delivered_box_lines(station, start, end)
            quantity = sum(line["boxes"] for line in lines)
            fee_type, rate, unit = "per_box", box_rate, "boxes"
        elif month_rate > 0:
            quantity = _calendar_months(start, end)
            fee_type, rate, unit = "per_month", month_rate, "months"
        elif year_rate > 0:
            quantity = _calendar_years(start, end)
            fee_type, rate, unit = "per_year", year_rate, "years"
        else:
            quantity, rate, fee_type, unit = 0, Decimal("0"), "none", ""

        total = (rate * quantity).quantize(_CENT)
        return {
            "delivery_station": station.id,
            "delivery_station_name": station.short_name,
            "start_date": start,
            "end_date": end,
            "fee_type": fee_type,
            "quantity": quantity,
            "quantity_unit": unit,
            "rate_net": str(rate.quantize(_CENT)),
            "total_net": str(total),
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
