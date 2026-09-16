from __future__ import annotations

from datetime import date

from drf_spectacular.utils import (
    OpenApiExample,
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
from ..schemas import (
    catalogue_param,
    get_delivery_week_parameter,
    get_end_date_parameter,
    get_start_date_parameter,
    get_year_parameter,
)
from ..serializers import (
    MemberDashboardStatisticsSerializer,
    MemberGrowthStatisticSerializer,
    PurchaseCostByWeekSerializer,
)
from ..services import (
    MEMBER_GROWTH_PERIODS,
    ShareContentService,
    calculate_historical_share_type_variation_averages,
    calculate_member_dashboard_statistics,
    calculate_member_growth_statistics,
)
from ..utils.query_params import validate_query_params


@extend_schema(
    summary="Get member growth statistics",
    description="""
    Returns confirmed members per period: entries (by entry date), exits (by
    exit date, once it has passed) and the member count at the end of each
    period. Can be filtered by year or start date; the count still includes
    members who joined before the window and hadn't left by then.
    """,
    parameters=[
        catalogue_param(
            "period",
            required=False,
            description="Time period for grouping statistics",
            enum=["month", "week", "year"],
            default="month",
        ),
        catalogue_param(
            "start_date",
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
    """Confirmed member entries, exits and counts per month, week or year."""
    params = validate_query_params(request, optional=["start_date", "year"])
    start_date: date | None = params["start_date"]
    year: int | None = params["year"]

    # period stays a raw read: the catalogue lists it as a free str, but this
    # endpoint enforces its own {month, week, year} enum (with a "month"
    # default the str-default of None would mask).
    period: str = request.query_params.get("period", "month")
    if period not in MEMBER_GROWTH_PERIODS:
        raise InvalidQueryParam(
            f"Invalid period '{period}'. Must be one of: "
            f"{', '.join(MEMBER_GROWTH_PERIODS)}",
            field="period",
        )

    result = calculate_member_growth_statistics(
        period=period, year=year, start_date=start_date
    )
    serializer = MemberGrowthStatisticSerializer(result, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    summary="Get purchase cost per week",
    description="""
    Total money spent buying in purchased ("Zukauf") share articles, per ISO
    week over a date range. Mirrors the harvest-share-planning page's per-week
    purchase figure (price_per_unit × amount × variation demand), aggregated
    server-side so only the per-week points cross the wire. Office only.
    """,
    parameters=[
        get_start_date_parameter(required=True),
        get_end_date_parameter(required=True),
    ],
    responses={
        200: PurchaseCostByWeekSerializer(many=True),
        400: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsOffice])
def purchase_cost_by_week(request: Request) -> Response:
    """Total purchase ("Zukauf") cost per ISO week within [start_date, end_date]."""
    params = validate_query_params(request, required=["start_date", "end_date"])
    start_date: date = params["start_date"]
    end_date: date = params["end_date"]
    if start_date > end_date:
        raise InvalidQueryParam(
            "`start_date` must be on or before `end_date`.",
            field="start_date",
        )

    data = ShareContentService().purchase_cost_by_week(start_date, end_date)
    serializer = PurchaseCostByWeekSerializer(data, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    summary="Get member dashboard statistics",
    description="""
    Snapshot ("today") of member and cooperative-share statistics: member counts
    (total / active / trial / confirmed / pending / cancelled), average member
    age, and cooperative-share sums (total / confirmed / pending / paid / unpaid /
    payback-due).
    """,
    responses={200: MemberDashboardStatisticsSerializer},
)
@api_view(["GET"])
@permission_classes([IsOffice])
def member_dashboard_statistics(request: Request) -> Response:
    """Return the member + cooperative-share snapshot for the office dashboard."""
    data = calculate_member_dashboard_statistics()
    return Response(
        MemberDashboardStatisticsSerializer(data).data,
        status=status.HTTP_200_OK,
    )


@extend_schema(
    summary="Get historical share variation averages",
    description="""
    Calculate historical averages for share variation amounts based on past years' data.
    Useful for predicting future share contents based on historical patterns.
    """,
    parameters=[
        get_year_parameter(required=True),
        get_delivery_week_parameter(required=True),
        catalogue_param(
            "share_type_variation_ids",
            required=False,
            description="Comma-separated list of share type variation IDs. "
            "Pass this OR `share_option` (+ optional `active_at_date`).",
            examples=[
                OpenApiExample(
                    "Multiple Variations",
                    value="var-123,var-456,var-789",
                )
            ],
        ),
        catalogue_param(
            "share_option",
            required=False,
            description="Resolve variation IDs server-side from share_option "
            "(e.g. 'gemuese'). Use this to avoid a client-side waterfall.",
        ),
        catalogue_param(
            "active_at_date",
            required=False,
            description="When using `share_option`: only consider variations active "
            "at this date. Ignored if `share_type_variation_ids` given.",
        ),
        catalogue_param("years_back", required=False),
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
def historical_share_type_variation_averages(request: Request) -> Response:
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

    averages: dict = calculate_historical_share_type_variation_averages(
        share_type_variation_ids=variation_ids,
        year=year,
        delivery_week=delivery_week,
        years_back=years_back,
    )

    # Serialize and return
    return Response(averages, status=status.HTTP_200_OK)


def _parse_variation_average_params(request: Request) -> dict:
    """Parse and validate parameters for historical variation averages.

    Accepts EITHER an explicit ``share_type_variation_ids`` list OR a
    ``share_option`` (+ optional ``active_at_date``) pair that resolves to
    the same set of variation IDs server-side. The latter avoids a frontend
    waterfall (fetching share-type-variations first and only then firing this
    endpoint) — both queries can run in parallel against the same filter
    shape.

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
