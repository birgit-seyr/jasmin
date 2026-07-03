from collections import defaultdict
from decimal import Decimal

from django.db.models import Q

from ..models import ShareContent


def _compute_variation_averages(
    share_type_variation_ids, year, delivery_week, years_back=2
):
    """
    Calculate statistical averages of share content (in kg) for one or more
    variations in a single ShareContent scan. Every result key embeds its
    ``variation_{id}`` so multiple variations never collide.
    Returns averages at three levels:
    1. Station level: day_X_variation_Y_station_ABC (most granular)
    2. Tour level: day_X_variation_Y_tour_Z (aggregated from stations)
    3. Day level: day_X_variation_Y (aggregated from stations)

    Args:
        share_type_variation: ShareTypeVariation instance
        year: Current year
        delivery_week: Current week number
        years_back: Number of years to look back (default: 2)

    Returns:
        Dictionary with structure:
        {
            'day_abc_variation_xyz_station_123': 4.2,  # Station level average
            'day_abc_variation_xyz_tour_1': 8.3,  # Tour level average (sum of stations)
            'day_abc_variation_xyz': 12.5,  # Day level average (sum of stations)
        }
    """
    # Calculate date range
    start_year = year - years_back

    # Get all relevant planning records - ONLY include data BEFORE the current week
    queryset = ShareContent.objects.filter(
        share__share_type_variation_id__in=share_type_variation_ids,
        share__year__gte=start_year,
    ).filter(
        # Include all years before current year
        Q(share__year__lt=year)
        |
        # OR current year but before current week
        Q(share__year=year, share__delivery_week__lt=delivery_week)
    )

    # Structure to hold sums PER WEEK at station level
    # Key: (week, year, station_key) -> amount
    # Quantities (amount, kg-per-piece/bunch) are DecimalFields — keep the
    # aggregation in Decimal end-to-end and float only at the response
    # boundary (return), so intermediate sums don't accrue binary-fp drift.
    weekly_station_amounts = defaultdict(lambda: defaultdict(Decimal))

    # Track all unique station keys
    all_station_keys = set()

    # Track station to tour/day mappings - key is (station_id, day_id)
    station_day_to_tour = {}

    # Get all records with their related data
    records = queryset.select_related(
        "share_article",
        "share",
        "share__delivery_day",
        "delivery_station",
    ).values(
        "id",
        "unit",
        "size",
        "amount",
        "share_article__kg_per_piece_S",
        "share_article__kg_per_piece_M",
        "share_article__kg_per_piece_L",
        "share_article__kg_per_bunch_S",
        "share_article__kg_per_bunch_M",
        "share_article__kg_per_bunch_L",
        "share__delivery_day__id",
        "share__delivery_week",
        "share__year",
        "share__share_type_variation_id",
        "delivery_station__id",
    )

    processed_count = 0

    # Process each record - aggregate by week first
    for record_data in records:
        amount = record_data.get("amount") or 0

        variation_id = record_data["share__share_type_variation_id"]
        day_id = record_data["share__delivery_day__id"]
        station_id = record_data.get("delivery_station__id")
        week = record_data["share__delivery_week"]
        record_year = record_data["share__year"]

        if not station_id:
            continue

        # Convert to kg. ``amount`` and the ``kg_per_*`` columns are all
        # DecimalFields — coerce via ``Decimal(str(...))`` (never
        # ``Decimal(float)``) and multiply in Decimal.
        amount_dec = Decimal(str(amount))
        kg_amount = Decimal("0")
        unit = record_data["unit"]
        size = record_data["size"]

        _kg_per_field = {
            ("PCS", "S"): "share_article__kg_per_piece_S",
            ("PCS", "M"): "share_article__kg_per_piece_M",
            ("PCS", "L"): "share_article__kg_per_piece_L",
            ("BUNCH", "S"): "share_article__kg_per_bunch_S",
            ("BUNCH", "M"): "share_article__kg_per_bunch_M",
            ("BUNCH", "L"): "share_article__kg_per_bunch_L",
        }.get((unit, size))

        if unit == "KG":
            kg_amount = amount_dec
        elif _kg_per_field is not None:
            kg_amount = amount_dec * Decimal(str(record_data[_kg_per_field] or 0))

        # Station level aggregation: day_X_variation_Y_station_Z
        station_key = f"day_{day_id}_variation_{variation_id}_station_{station_id}"
        week_key = (record_year, week)

        # Sum up amounts per week per station (even if kg_amount is 0)
        weekly_station_amounts[week_key][station_key] += kg_amount
        all_station_keys.add(station_key)
        processed_count += 1

    # Now calculate averages: sum of weekly totals / number of weeks
    station_totals = defaultdict(lambda: {"sum": Decimal("0"), "count": 0})

    for _week_key, station_amounts in weekly_station_amounts.items():
        for station_key, amount in station_amounts.items():
            station_totals[station_key]["sum"] += amount
            station_totals[station_key]["count"] += 1

    # Get tour information from DeliveryStationDay
    from ..models import DeliveryStationDay

    # Get all unique (station_id, day_id) combinations from station_totals
    station_day_combinations = set()
    for station_key in all_station_keys:
        # Parse: day_{day_id}_variation_{variation_id}_station_{station_id}
        parts = station_key.split("_")
        day_id = parts[1]
        station_id = parts[5]
        station_day_combinations.add((station_id, day_id))

    # Fetch tour numbers for all combinations in one query
    delivery_station_days = DeliveryStationDay.objects.filter(
        delivery_station_id__in=[
            station_id for station_id, _ in station_day_combinations
        ],
        delivery_day_id__in=[
            delivery_day_id for _, delivery_day_id in station_day_combinations
        ],
    ).values("delivery_station_id", "delivery_day_id", "tour_number")

    # Build the lookup dictionary
    for delivery_station_day in delivery_station_days:
        key = (
            delivery_station_day["delivery_station_id"],
            delivery_station_day["delivery_day_id"],
        )
        station_day_to_tour[key] = delivery_station_day["tour_number"]

    # Calculate station-level averages
    station_averages = {}
    for field_name, data in station_totals.items():
        if data["count"] > 0:
            avg = round(data["sum"] / (data["count"]), 2)
            station_averages[field_name] = avg

    # Now aggregate from station level to tour and day levels
    tour_totals = defaultdict(Decimal)
    day_totals = defaultdict(Decimal)

    for station_key, avg_value in station_averages.items():
        # Parse the station key to get day_id, variation_id, station_id
        # Format: day_{day_id}_variation_{variation_id}_station_{station_id}
        parts = station_key.split("_")
        day_id = parts[1]
        var_id = parts[3]
        station_id = parts[5]

        # Aggregate to day level
        day_key = f"day_{day_id}_variation_{var_id}"
        day_totals[day_key] += avg_value

        # Aggregate to tour level if tour mapping exists
        lookup_key = (station_id, day_id)
        if lookup_key in station_day_to_tour:
            tour_number = station_day_to_tour[lookup_key]
            tour_key = f"day_{day_id}_variation_{var_id}_tour_{tour_number}"
            tour_totals[tour_key] += avg_value

    # Combine all averages
    averages = {}

    # Station level (already calculated)
    averages.update(station_averages)

    # Tour level (rounded)
    for tour_key, total in tour_totals.items():
        averages[tour_key] = round(total, 2)

    # Day level (rounded)
    for day_key, total in day_totals.items():
        averages[day_key] = round(total, 2)

    # Float only at the response boundary — the values were accumulated in
    # Decimal above; ``float`` here keeps the wire contract (JSON numbers)
    # without re-introducing intermediate drift.
    return {key: float(value) for key, value in averages.items()}


def calculate_historical_share_variation_averages(
    share_type_variation_ids, year, delivery_week, years_back=2
):
    """
    Calculate statistical averages for multiple variations at once.

    Args:
        share_type_variation_ids: List of ShareTypeVariation IDs
        year: Current year
        delivery_week: Current week number
        years_back: Number of years to look back (default: 2)

    Returns:
        Merged dictionary with all variation averages at all levels
    """
    # One ShareContent scan for every variation (no per-id point-lookup, no
    # per-variation scan). Unknown ids simply contribute no records.
    return _compute_variation_averages(
        list(share_type_variation_ids), year, delivery_week, years_back
    )
