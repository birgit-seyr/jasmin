from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework.request import Request
from rest_framework.views import APIView, Response

from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice, IsStaff
from core.serializers import ErrorResponseSerializer

from ..models import DeliveryStationDay, ShareContent, ShareTypeVariation
from ..schemas import (
    get_day_number_parameter,
    get_delivery_day_parameter,
    get_delivery_station_parameter,
    get_delivery_week_parameter,
    get_share_option_parameter,
    get_share_type_parameter,
    get_year_parameter,
)
from ..serializers.shares_serializer import (
    ShareTypeVariationsTotalsResponseSerializer,
)
from ..utils import (
    batch_get_physical_variation_totals_for_week,
    get_physical_share_type_variation_totals,
    get_total_quantity_of_share_type_variations,
)
from ..utils.iso_week_utils import saturday_of_iso_week
from ..utils.query_params import validate_query_params


class ShareContentGranularityView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsOffice
    """Check if ShareContent data supports day-level and tour-level granularity."""

    @extend_schema(
        summary="Check ShareContent Granularity",
        description="""
        Check if ShareContent data for a given year and week supports:
        - Day-level granularity (same amounts per day)
        - Tour-level granularity (same amounts per tour)
        
        Returns:
        - days_ok: true if all items have same amount per day
        - tours_ok: true if all items have same amount per tour
        """,
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            get_share_option_parameter(required=False),
            get_day_number_parameter(required=False),
        ],
        responses={
            200: inline_serializer(
                name="GranularityCheckResponse",
                fields={
                    "days_ok": drf_serializers.BooleanField(),
                    "tours_ok": drf_serializers.BooleanField(),
                },
            ),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        # Granularity is a per-share_type property: a simple share (honey,
        # delivered uniformly to every station) is day-consistent even when
        # the complex harvest share in the same week varies per station/tour.
        # Without this scoping the packing UI judged honey by the harvest
        # share's granularity and showed the wrong selectors. share_type wins
        # when both are present (it's the narrower, displayed scope).
        params = validate_query_params(
            request,
            required=["year", "delivery_week"],
            optional=["share_option", "day_number"],
        )

        content_data = list(
            self._get_content_data(
                params["year"],
                params["delivery_week"],
                share_option=params["share_option"],
                # Optional: scope the consistency check to a SINGLE delivery day
                # (the packing list passes this so it gets per-delivery-day
                # granularity). Omitted by PlanningHarvestSharesBase, which wants
                # the across-all-delivery-days result.
                delivery_day=params["day_number"],
            )
        )

        if not content_data:
            return Response({"days_ok": True, "tours_ok": True})

        days_ok, tours_ok = self._check_granularity(content_data)

        return Response({"days_ok": days_ok, "tours_ok": tours_ok})

    @staticmethod
    def _get_content_data(
        year: int,
        delivery_week: int,
        share_option: str | None = None,
        delivery_day: int | None = None,
    ) -> QuerySet:
        queryset = ShareContent.objects.filter(
            share__year=year,
            share__delivery_week=delivery_week,
        )
        if share_option:
            queryset = queryset.filter(
                share__share_type_variation__share_type__share_option=share_option
            )
        if delivery_day is not None:
            queryset = queryset.filter(share__delivery_day__day_number=delivery_day)
        return queryset.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "delivery_station",
        ).values(
            "share_article_id",
            "share__share_type_variation_id",
            "share__delivery_day_id",
            "amount",
            "delivery_station_id",
            "unit",
            "size",
        )

    @staticmethod
    def _build_tour_number_map(
        content_data: list[dict],
    ) -> dict[tuple[str, str], int | None]:
        """Prefetch all tour numbers in one query instead of N+1."""
        pairs = {
            (item["delivery_station_id"], item["share__delivery_day_id"])
            for item in content_data
            if item["delivery_station_id"]
        }
        if not pairs:
            return {}

        from django.db.models import Q

        q = Q()
        for station_id, day_id in pairs:
            q |= Q(delivery_station_id=station_id, delivery_day_id=day_id)

        return {
            (
                delivery_station_day.delivery_station_id,
                delivery_station_day.delivery_day_id,
            ): delivery_station_day.tour_number
            for delivery_station_day in DeliveryStationDay.objects.filter(q)
        }

    def _check_granularity(self, content_data: list[dict]) -> tuple[bool, bool]:
        tour_map = self._build_tour_number_map(content_data)

        day_grouped = self._group_by_day(content_data)
        tour_grouped = self._group_by_tour(content_data, tour_map)

        days_ok = self._check_amounts_consistency(day_grouped)
        tours_ok = self._check_amounts_consistency(tour_grouped)

        return days_ok, tours_ok

    @staticmethod
    def _group_by_day(
        content_data: list[dict],
    ) -> dict[tuple, list[dict]]:
        grouped: dict[tuple, list[dict]] = defaultdict(list)

        for item in content_data:
            key = (
                item["share_article_id"],
                item["share__share_type_variation_id"],
                item["share__delivery_day_id"],
                item["unit"],
                item["size"],
            )
            grouped[key].append(item)

        return grouped

    @staticmethod
    def _group_by_tour(
        content_data: list[dict],
        tour_map: dict[tuple[str, str], int | None],
    ) -> dict[tuple, list[dict]]:
        grouped: dict[tuple, list[dict]] = defaultdict(list)

        for item in content_data:
            station_id = item["delivery_station_id"]
            day_id = item["share__delivery_day_id"]
            tour_number = tour_map.get((station_id, day_id)) if station_id else None
            key = (
                item["share_article_id"],
                item["share__share_type_variation_id"],
                day_id,
                tour_number,
            )
            grouped[key].append(item)

        return grouped

    @staticmethod
    def _check_amounts_consistency(grouped_data: dict[tuple, list[dict]]) -> bool:
        # ``amount`` is ``null=True`` on ShareContent — a forecast-
        # attached row whose human plan was cleared sits at ``None``
        # (the codebase convention puts ``NULL`` and ``0`` in the same
        # "no human plan" bucket; see
        # ``forecast_service._delete_orphaned_share_contents``). Coerce
        # to ``0`` here so ``Decimal(str(None))`` doesn't blow up the
        # granularity check.
        for records in grouped_data.values():
            normalized_amounts = {
                Decimal(
                    str(record["amount"] if record["amount"] is not None else 0)
                ).normalize()
                for record in records
            }
            if len(normalized_amounts) > 1:
                return False
        return True


class ShareTypeVariationsTotalsView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsStaff
    """
    Get share_type_variation totals for a specific delivery scenario.

    Returns the count/quantity of different share_type_variations
    (small, large, etc.) for a given delivery week, day, tour, and station
    combination.
    """

    @extend_schema(
        summary="Get share_type_variation totals",
        description="""
        Get the total count/quantity of share_type_variations for a specific
        delivery scenario. Returns variation counts filtered by the provided
        parameters.

        Use this endpoint to get share_type_variation counts for a specific
        tour, station, or day.
        """,
        parameters=[
            get_share_option_parameter(required=False),
            get_share_type_parameter(required=False),
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_delivery_day_parameter(required=True),
            OpenApiParameter(
                name="tour",
                type=OpenApiTypes.INT,
                required=False,
            ),
            get_delivery_station_parameter(required=False),
            OpenApiParameter(
                name="physical_share_type_variations",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "If true, return physical share_type_variation totals "
                    "resolving virtual subscriptions into their physical "
                    "components."
                ),
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=ShareTypeVariationsTotalsResponseSerializer,
                description="Variation totals",
            ),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        params = self._extract_and_validate_params(request)

        physical_share_type_variations = validate_query_params(
            request, optional=["physical_share_type_variations"]
        )["physical_share_type_variations"]

        if physical_share_type_variations:
            variations_data = get_physical_share_type_variation_totals(
                share_type=params["share_type"],
                share_option=params["share_option"],
                year=params["year"],
                delivery_week=params["delivery_week"],
                delivery_day=params["delivery_day"],
                tour=params["tour"],
                delivery_station=params["delivery_station"],
            )
        else:
            variations_data = get_total_quantity_of_share_type_variations(
                share_option=params["share_option"],
                share_type=params["share_type"],
                year=params["year"],
                delivery_week=params["delivery_week"],
                delivery_day=params["delivery_day"],
                tour=params["tour"],
                delivery_station=params["delivery_station"],
            )

        return Response({"variations": variations_data})

    @staticmethod
    def _extract_and_validate_params(request: Request) -> dict[str, object]:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "delivery_day"],
            optional=["share_option", "share_type", "tour", "delivery_station"],
        )

        return {
            "share_option": params["share_option"],
            "share_type": params["share_type"],
            "year": params["year"],
            "delivery_week": params["delivery_week"],
            "delivery_day": params["delivery_day"],
            "tour": params["tour"],
            "delivery_station": params["delivery_station"],
        }


class ShareTypeVariationAmountsForPlanningView(APIViewRolePermissionsMixin, APIView):
    read_permission = IsStaff
    write_permission = IsOffice
    """
    Get comprehensive variation amounts for planning across all scenarios.

    Generates keys for basic, tour-level, and station-level planning modes,
    providing a complete overview of share_type_variation requirements for
    the week.
    """

    @extend_schema(
        summary="Get all share variation amounts for planning",
        description="""
        Get comprehensive planning data for all variations, days, tours, and stations
        for a given week. Returns a dictionary with keys for different planning modes:
        
        - **Basic mode**: `day_{day_id}_variation_{variation_id}`
        - **Tour mode**: `day_{day_id}_variation_{variation_id}_tour_{tour_number}`
        - **Station mode**: `day_{day_id}_variation_{variation_id}_station_{station_id}`
        
        Use this endpoint to get a complete overview for weekly planning across all
        delivery scenarios.
        """,
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_share_option_parameter(required=True),
        ],
        responses={
            200: OpenApiResponse(
                description="Planning data with variation counts for all combinations",
                response={
                    "type": "object",
                    "additionalProperties": {
                        "type": "integer",
                        "description": "Variation count for this key combination",
                    },
                    "example": {
                        "day_monday-id_variation_small-id": 15,
                        "day_monday-id_variation_small-id_tour_1": 10,
                        "day_monday-id_variation_small-id_tour_2": 5,
                        "day_monday-id_variation_small-id_station_downtown": 8,
                        "day_monday-id_variation_large-id": 8,
                    },
                },
            ),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        params = self._extract_and_validate_params(request)

        week_saturday = saturday_of_iso_week(params["year"], params["delivery_week"])

        active_delivery_station_days = self._get_active_delivery_station_days(
            week_saturday
        )
        physical_variations = self._get_physical_variations(
            week_saturday, params["share_option"]
        )

        result = self._generate_planning_data(
            active_delivery_station_days,
            physical_variations,
            params["year"],
            params["delivery_week"],
        )

        return Response(result)

    @staticmethod
    def _extract_and_validate_params(request: Request) -> dict[str, object]:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "share_option"],
        )

        return {
            "year": params["year"],
            "delivery_week": params["delivery_week"],
            "share_option": params["share_option"],
        }

    @staticmethod
    def _get_active_delivery_station_days(week_saturday) -> QuerySet:
        return DeliveryStationDay.current.active_at_date(week_saturday).select_related(
            "delivery_station", "delivery_day"
        )

    @staticmethod
    def _get_physical_variations(week_saturday, share_option: str) -> QuerySet:
        return (
            ShareTypeVariation.current.active_at_date(week_saturday)
            .filter(
                share_type__share_option=share_option,
                variation_type="physical",
            )
            .order_by("size")
        )

    def _generate_planning_data(
        self,
        active_delivery_station_days: QuerySet,
        physical_variations: QuerySet,
        year: int,
        delivery_week: int,
    ) -> dict[str, int]:
        result: dict[str, int] = {}

        # Batch-compute ALL variation totals in 2-3 queries
        totals = batch_get_physical_variation_totals_for_week(
            physical_variations, year, delivery_week
        )

        delivery_days_grouped = self._group_by_delivery_day(
            active_delivery_station_days
        )

        for delivery_day, delivery_station_days in delivery_days_grouped.items():
            day_id: str = delivery_station_days[0].delivery_day_id
            delivery_stations = [
                delivery_station_day.delivery_station
                for delivery_station_day in delivery_station_days
            ]
            used_tours: list[int] = sorted(
                {
                    delivery_station_day.tour_number
                    for delivery_station_day in delivery_station_days
                    if delivery_station_day.tour_number is not None
                }
            )

            for physical_variation in physical_variations:
                # Basic key - lookup from batch results
                basic_key = f"day_{day_id}_variation_{physical_variation.id}"
                result[basic_key] = totals["basic"].get(
                    (delivery_day.id, physical_variation.id), 0
                )

                # Tour keys
                for tour_number in used_tours:
                    tour_key = f"day_{day_id}_variation_{physical_variation.id}_tour_{tour_number}"
                    result[tour_key] = totals["tour"].get(
                        (delivery_day.id, physical_variation.id, tour_number), 0
                    )

                # Station keys
                for station in delivery_stations:
                    station_key = f"day_{day_id}_variation_{physical_variation.id}_station_{station.id}"
                    result[station_key] = totals["station"].get(
                        (delivery_day.id, physical_variation.id, station.id), 0
                    )

        return result

    @staticmethod
    def _group_by_delivery_day(
        active_delivery_station_days: QuerySet,
    ) -> dict[object, list]:
        grouped: dict[object, list] = defaultdict(list)
        for delivery_station_day in active_delivery_station_days:
            grouped[delivery_station_day.delivery_day].append(delivery_station_day)
        return grouped
