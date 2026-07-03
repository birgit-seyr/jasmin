from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice, IsStaff
from core.serializers import ErrorResponseSerializer

from ..errors import CommissioningError
from ..models import (
    DeliveryStationDay,
    ShareTypeVariation,
)
from ..schemas import (
    get_day_number_parameter,
    get_delivery_station_parameter,
    get_delivery_week_parameter,
    get_end_date_parameter,
    get_start_date_parameter,
    get_year_parameter,
)
from ..serializers import (
    DeliveryStationFeesSerializer,
    DeliveryStationsToursOverviewResponseSerializer,
)
from ..services.delivery_station_fee_service import DeliveryStationFeeService
from ..utils import (
    get_active_share_type_variations,
    get_delivery_station_days_from_shares_delivery_day,
    get_shares_delivery_day_from_day_number,
    get_variation_quantities_by_station_day,
)
from ..utils.query_params import validate_query_params


class DeliveryStationsToursOverviewView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsStaff
    """Get delivery stations overview with share counts organized by tours and stations."""

    @extend_schema(
        summary="Delivery Stations and Tours Overview",
        description="""
        Provides an overview of all delivery stations with share counts,
        organized by tours and stations.
        
        The response includes:
        - List of tours with their stations

        - For each station: number of shares by type-variation
        - Metadata about available share-type variations
        """,
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            get_day_number_parameter(),
        ],
        responses={
            200: DeliveryStationsToursOverviewResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        """Main endpoint handler."""
        # Validate parameters
        params = validate_query_params(
            request, required=["year", "delivery_week", "day_number"]
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]

        # Get delivery day (raises SharesDeliveryDayNotFound → 404)
        shares_delivery_day, active_at_date = get_shares_delivery_day_from_day_number(
            year, delivery_week, day_number
        )

        # Get related data
        delivery_station_days = get_delivery_station_days_from_shares_delivery_day(
            shares_delivery_day, active_at_date
        )
        share_type_variations = get_active_share_type_variations(
            year, delivery_week, shares_delivery_day, delivery_station_days
        )

        # Build response
        tours_list = self._build_tours_data(
            delivery_station_days, share_type_variations, year, delivery_week
        )
        variations_metadata = self._build_variations_metadata(share_type_variations)

        response_data = {
            "year": year,
            "delivery_week": delivery_week,
            "day_number": day_number,
            "delivery_day_id": shares_delivery_day.id,
            "number_of_tours": shares_delivery_day.number_of_tours or 1,
            "tours": tours_list,
            "variations": variations_metadata,
        }

        serializer = DeliveryStationsToursOverviewResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _build_station_data(
        self,
        station_day: DeliveryStationDay,
        share_type_variations: QuerySet[ShareTypeVariation],
        demand_by_cell: dict[tuple[str, str], int],
    ) -> dict[str, Any]:
        """Build data dictionary for a single station including variation counts."""
        station_data = {
            "delivery_station_day_id": station_day.id,
            "delivery_station_id": station_day.delivery_station.id,
            "delivery_station_name": (
                station_day.delivery_station.contact.name
                if station_day.delivery_station.contact
                else None
            ),
            "delivery_station_short_name": station_day.delivery_station.short_name,
            "stop_order": station_day.stop_order,
            "capacity": station_day.capacity,
            "pickup_time_begin": station_day.pickup_time_begin,
            "pickup_time_end": station_day.pickup_time_end,
        }

        # Variation counts come from the pre-batched grid (one query for the
        # whole overview) instead of a per-cell aggregate.
        for variation in share_type_variations:
            station_data[f"variation_{variation.id}"] = demand_by_cell.get(
                (station_day.id, variation.id), 0
            )

        return station_data

    def _build_tours_data(
        self,
        delivery_station_days: QuerySet[DeliveryStationDay],
        share_type_variations: QuerySet[ShareTypeVariation],
        year: int,
        delivery_week: int,
    ) -> list[dict[str, Any]]:
        """Build the tours data structure with stations grouped by tour number."""
        # One batched query for the whole (station_day, variation) grid instead
        # of a per-cell aggregate (the old S×V N+1).
        demand_by_cell = get_variation_quantities_by_station_day(
            year=year,
            delivery_week=delivery_week,
            variation_ids=[variation.id for variation in share_type_variations],
        )
        tours_dict: dict[int, list[dict[str, Any]]] = {}

        for station_day in delivery_station_days:
            tour_number = station_day.tour_number

            if tour_number not in tours_dict:
                tours_dict[tour_number] = []

            station_data = self._build_station_data(
                station_day, share_type_variations, demand_by_cell
            )
            tours_dict[tour_number].append(station_data)

        return [
            {"tour_number": tour_num, "stations": stations}
            for tour_num, stations in sorted(tours_dict.items())
        ]

    def _build_variations_metadata(
        self, share_type_variations: QuerySet[ShareTypeVariation]
    ) -> list[dict[str, Any]]:
        """Build metadata for share type variations."""
        return [
            {
                "id": variation.id,
                "share_type_id": variation.share_type.id,
                "share_type_name": variation.share_type.name,
                "size": variation.size,
                "display_name": f"{variation.share_type.name} - {variation.size}",
                "key": f"variation_{variation.id}",
            }
            for variation in share_type_variations
        ]


class DeliveryStationFeesView(APIViewRolePermissionsMixin, APIView):
    """What the solawi owes each pickup station carrying a net fee, over an
    office-chosen ``[start_date, end_date]`` range. Read-only report; money is
    NET (no VAT) and returned as 2-decimal strings. Office-only (billing)."""

    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Delivery station fee billing",
        description=(
            "Per-station amount the solawi owes its pickup stations over a date "
            "range. Only stations with a non-zero net fee are returned; pass "
            "delivery_station to scope to one."
        ),
        parameters=[
            get_start_date_parameter(required=True),
            get_end_date_parameter(required=True),
            get_delivery_station_parameter(required=False),
        ],
        responses={
            200: DeliveryStationFeesSerializer(many=True),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request):
        params = validate_query_params(
            request,
            required=["start_date", "end_date"],
            optional=["delivery_station"],
        )
        start = params["start_date"]
        end = params["end_date"]
        if start > end:
            raise CommissioningError(
                "start_date must be on or before end_date.",
                code="delivery_station_fee.invalid_range",
            )
        data = DeliveryStationFeeService.compute_all(
            start, end, station_id=params["delivery_station"]
        )
        serializer = DeliveryStationFeesSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
