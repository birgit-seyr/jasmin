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
    ShareContentService,
    calculate_historical_share_type_variation_averages,
    calculate_member_dashboard_statistics,
    calculate_member_growth_statistics,
)
from ..utils.query_params import validate_query_params

# The purchase-cost report walks one iteration per ISO week in the range and
# widens its year/week IN-clauses to match, so the span is bounded here: an
# ``end_date`` of 9999-12-31 would otherwise ask for ~400 000 weeks. Five
# years is past the longest comparison the statistics page offers.
_MAX_PURCHASE_COST_SPAN_YEARS = 5
_MAX_PURCHASE_COST_SPAN_DAYS = _MAX_PURCHASE_COST_SPAN_YEARS * 366


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
    params = validate_query_params(request, optional=["period", "start_date", "year"])
    start_date: date | None = params["start_date"]
    year: int | None = params["year"]
    period: str = params["period"]

    result = calculate_member_growth_statistics(
        period=period, year=year, start_date=start_date
    )
    serializer = MemberGrowthStatisticSerializer(result, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    summary="Get purchase cost per week",
    description=f"""
    Total money spent buying in purchased ("Zukauf") share articles, per ISO
    week over a date range. Mirrors the harvest-share-planning page's per-week
    purchase figure (price_per_unit × amount × variation demand), aggregated
    server-side so only the per-week points cross the wire. Office only.

    The range is bounded: `start_date` must be on or before `end_date`, and
    the two may span at most {_MAX_PURCHASE_COST_SPAN_YEARS} years.
    """,
    parameters=[
        get_start_date_parameter(required=True),
        get_end_date_parameter(
            required=True,
            description=(
                "Inclusive range end (YYYY-MM-DD). At most "
                f"{_MAX_PURCHASE_COST_SPAN_YEARS} years after `start_date`."
            ),
        ),
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
    # The order of the pair is the catalogue's rule; the SPAN is this
    # endpoint's, because the week walk below is what the cap protects.
    if (end_date - start_date).days > _MAX_PURCHASE_COST_SPAN_DAYS:
        raise InvalidQueryParam(
            f"The range must not exceed {_MAX_PURCHASE_COST_SPAN_YEARS} years.",
            field="end_date",
            details={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
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
            "(e.g. HARVEST_SHARE). Use this to avoid a client-side waterfall.",
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
        # The raw values, not the parsed ones: a blank ``?share_option=`` parses
        # to the same ``None`` as an omitted one, so only the wire text separates
        # "sent empty" (echoed as "") from "never sent" (echoed as null).
        raise InvalidQueryParam(
            "Provide either 'share_type_variation_ids' or 'share_option' "
            "to identify which variations to compute averages for",
            field="share_type_variation_ids",
            details={
                "share_type_variation_ids": request.query_params.get(
                    "share_type_variation_ids"
                ),
                "share_option": request.query_params.get("share_option"),
            },
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
        # Name the parameter the caller actually supplied, so the client can
        # attach the message to the input the user can still change.
        raise InvalidQueryParam(
            "No matching share-type-variations for the given parameters",
            field=("share_type_variation_ids" if variation_ids_str else "share_option"),
            details={
                "share_type_variation_ids": variation_ids_str or None,
                "share_option": share_option,
                "active_at_date": (
                    active_at_date.isoformat() if active_at_date else None
                ),
            },
        )

    return {
        "year": year,
        "delivery_week": delivery_week,
        "variation_ids": variation_ids,
        "years_back": years_back,
    }
