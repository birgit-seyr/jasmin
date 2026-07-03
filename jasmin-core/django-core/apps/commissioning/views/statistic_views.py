from __future__ import annotations

from collections.abc import Callable
from datetime import date

from django.db.models import Count, QuerySet
from django.db.models.functions import TruncMonth, TruncWeek, TruncYear
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff
from core.serializers import ErrorResponseSerializer

from ..errors import InvalidQueryParam
from ..models import Member
from ..schemas import get_delivery_week_parameter, get_year_parameter
from ..serializers import MemberGrowthStatisticSerializer
from ..services import calculate_historical_share_variation_averages
from ..utils.query_params import validate_query_params


@extend_schema(
    summary="Get member growth statistics",
    description="""
    Returns member growth statistics over time, showing new members per period
    and cumulative total. Can be filtered by time period and date range.
    """,
    parameters=[
        OpenApiParameter(
            name="period",
            type=OpenApiTypes.STR,
            required=False,
            description="Time period for grouping statistics",
            enum=["month", "week", "year"],
            default="month",
        ),
        OpenApiParameter(
            name="start_date",
            type=OpenApiTypes.DATE,
            required=False,
            description="Optional: Start date filter (YYYY-MM-DD). Ignored if 'year' is provided.",
        ),
        get_year_parameter(required=False),
    ],
    responses={
        200: MemberGrowthStatisticSerializer(many=True),
        400: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsOffice])
def member_growth_statistics(request: Request) -> Response:
    """
    Returns member growth statistics over time.

    Shows new members per period and cumulative totals.
    Can be grouped by month, week, or year.
    """
    # Extract and validate parameters
    params = validate_query_params(request, optional=["start_date", "year"])
    start_date: date | None = params["start_date"]
    year: int | None = params["year"]

    # period stays a raw read: the catalogue lists it as a free str, but this
    # endpoint enforces its own {month, week, year} enum (with a "month"
    # default the str-default of None would mask).
    period: str = request.query_params.get("period", "month")

    # Validate period parameter
    valid_periods = ["month", "week", "year"]
    if period not in valid_periods:
        raise InvalidQueryParam(
            f"Invalid period '{period}'. Must be one of: {', '.join(valid_periods)}",
            field="period",
        )

    # Choose truncation function based on period
    trunc_func: Callable = {
        "month": TruncMonth,
        "week": TruncWeek,
        "year": TruncYear,
    }[period]

    # Base queryset
    queryset: QuerySet[Member] = Member.objects.filter(entry_date__isnull=False)

    # Apply filters
    queryset = _apply_date_filters(queryset, year, start_date)

    # Group by period and count
    stats = (
        queryset.annotate(period=trunc_func("entry_date"))
        .values("period")
        .annotate(new_members=Count("id"))
        .order_by("period")
    )

    # Calculate cumulative totals
    result: list[dict] = _calculate_cumulative_statistics(stats)

    # Serialize and return
    serializer = MemberGrowthStatisticSerializer(result, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    summary="Get historical share variation averages",
    description="""
    Calculate historical averages for share variation amounts based on past years' data.
    Useful for predicting future share contents based on historical patterns.
    """,
    parameters=[
        get_year_parameter(required=True),
        get_delivery_week_parameter(required=True),
        OpenApiParameter(
            name="share_type_variation_ids",
            type=OpenApiTypes.STR,
            required=False,
            description=(
                "Comma-separated list of share type variation IDs. "
                "Pass this OR `share_option` (+ optional `active_at_date`)."
            ),
            examples=[
                OpenApiExample(
                    "Multiple Variations",
                    value="var-123,var-456,var-789",
                )
            ],
        ),
        OpenApiParameter(
            name="share_option",
            type=OpenApiTypes.STR,
            required=False,
            description=(
                "Resolve variation IDs server-side from share_option "
                "(e.g. 'gemuese'). Use this to avoid a client-side waterfall."
            ),
        ),
        OpenApiParameter(
            name="active_at_date",
            type=OpenApiTypes.DATE,
            required=False,
            description=(
                "When using `share_option`: only consider variations active "
                "at this date. Ignored if `share_type_variation_ids` given."
            ),
        ),
        OpenApiParameter(
            name="years_back",
            type=OpenApiTypes.INT,
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            response={"type": "object", "additionalProperties": {"type": "number"}},
            description="Flat map of 'day_<id>_variation_<id>[...]' keys to average amounts.",
        ),
        400: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsStaff])
def historical_share_variation_averages(request: Request) -> Response:
    """
    Get historical averages for share variation amounts.

    Calculates averages based on historical data from previous years
    for the same week/variation combinations.
    """
    # Parse and validate parameters (raises InvalidQueryParam on bad input)
    params = _parse_variation_average_params(request)

    year: int = params["year"]
    delivery_week: int = params["delivery_week"]
    variation_ids: list[str] = params["variation_ids"]
    years_back: int = params["years_back"]

    averages: dict = calculate_historical_share_variation_averages(
        share_type_variation_ids=variation_ids,
        year=year,
        delivery_week=delivery_week,
        years_back=years_back,
    )

    # Serialize and return
    return Response(averages, status=status.HTTP_200_OK)


def _apply_date_filters(
    queryset: QuerySet[Member],
    year: int | None,
    start_date: date | None,
) -> QuerySet[Member]:
    """
    Apply year or start_date filters to the queryset.

    Year filter takes precedence over start_date filter.

    Args:
        queryset: Base queryset to filter
        year: Catalogue-parsed year (YYYY) or None
        start_date: Catalogue-parsed start date or None

    Returns:
        The filtered queryset.
    """
    # Apply year filter if provided (takes precedence)
    if year is not None:
        return queryset.filter(entry_date__year=year)

    # Apply start_date filter if provided and no year filter
    if start_date is not None:
        return queryset.filter(entry_date__gte=start_date)

    return queryset


def _calculate_cumulative_statistics(
    stats: QuerySet,
) -> list[dict]:
    """Calculate cumulative totals from period statistics."""
    cumulative: int = 0
    result: list[dict] = []

    for item in stats:
        cumulative += item["new_members"]
        result.append(
            {
                "period": item["period"].strftime("%Y-%m-%d"),
                "new_members": item["new_members"],
                "total_members": cumulative,
            }
        )

    return result


def _parse_variation_average_params(request: Request) -> dict:
    """Parse and validate parameters for historical variation averages.

    Accepts EITHER an explicit ``share_type_variation_ids`` list OR a
    ``share_option`` (+ optional ``active_at_date``) pair that resolves to
    the same set of variation IDs server-side. The latter avoids a frontend
    waterfall where the planning page had to fetch share-type-variations
    first and only then fire this endpoint — both queries now run in
    parallel against the same filter shape.

    Raises:
        InvalidQueryParam: if a parameter is missing, malformed, out of
            range, or resolves to no variations.
    """
    params = validate_query_params(
        request,
        required=["year", "delivery_week"],
        optional=[
            "share_type_variation_ids",
            "share_option",
            "active_at_date",
            "years_back",
        ],
    )
    year: int = params["year"]
    delivery_week: int = params["delivery_week"]
    variation_ids_str: str = params["share_type_variation_ids"] or ""
    share_option: str | None = params["share_option"]
    active_at_date: date | None = params["active_at_date"]
    years_back: int = params["years_back"]

    if not variation_ids_str and not share_option:
        raise InvalidQueryParam(
            "Provide either 'share_type_variation_ids' or 'share_option' "
            "to identify which variations to compute averages for",
        )

    if variation_ids_str:
        variation_ids: list[str] = [
            variation_id.strip()
            for variation_id in variation_ids_str.split(",")
            if variation_id.strip()
        ]
    else:
        # Resolve from share_option (+ active_at_date) — mirrors the
        # ShareTypeVariationViewSet.get_queryset filter so the result set
        # is identical to what a sibling /share-type-variations/ call
        # would have returned.
        from ..models import ShareTypeVariation

        qs = ShareTypeVariation.objects.filter(share_type__share_option=share_option)
        if active_at_date:
            qs = qs.filter(
                id__in=ShareTypeVariation.current.active_at_date(
                    active_at_date
                ).values_list("id", flat=True)
            )
        variation_ids = list(qs.values_list("id", flat=True))

    if not variation_ids:
        raise InvalidQueryParam(
            "No matching share-type-variations for the given parameters"
        )

    return {
        "year": year,
        "delivery_week": delivery_week,
        "variation_ids": variation_ids,
        "years_back": years_back,
    }
