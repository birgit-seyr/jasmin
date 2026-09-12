from django.db.models import Q, Sum
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsStaff
from core.serializers import ErrorResponseSerializer

from ..errors import InvalidQueryParam
from ..models import Harvest, Purchase, Waste
from ..schemas import (
    catalogue_param,
    get_delivery_day_parameter,
    get_delivery_week_parameter,
    get_share_article_parameter,
    get_year_parameter,
)
from ..serializers import DocumentationAggregationItemSerializer
from ..utils.query_params import validate_query_params

SOURCE_MODEL_MAP = {
    "HARVEST": Harvest,
    "PURCHASE": Purchase,
    "WASTE": Waste,
}


class DocumentationOverviewView(APIViewRolePermissionsMixin, APIView):
    """Get aggregated documentation data based on source type."""

    read_permission = IsStaff
    write_permission = IsStaff

    @extend_schema(
        summary="Documentation Aggregation Overview",
        description="""
        Aggregates documentation data (harvest, purchase, or waste) by share article.
        
        Returns sum of amounts grouped by:
        - Share article name
        - Unit (kg, pieces, etc.)
        - Size specification
        
        Can be filtered by year, week, and day_number.
        """,
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(required=False),
            get_delivery_day_parameter(required=False),
            get_share_article_parameter(),
            catalogue_param(
                "source",
                required=False,
                description="Documentation source type (defaults to HARVEST)",
                enum=list(SOURCE_MODEL_MAP.keys()),
            ),
        ],
        responses={
            200: DocumentationAggregationItemSerializer(many=True),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        """Get aggregated documentation data."""
        # Validate year (required) + optional week/day_number + required
        # share_article through the central catalogue.
        params = validate_query_params(
            request,
            required=["year", "share_article"],
            optional=["delivery_week", "day_number"],
        )

        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        share_article = params["share_article"]

        source = request.query_params.get("source", "HARVEST")

        model = SOURCE_MODEL_MAP.get(source.upper())
        if not model:
            raise InvalidQueryParam(
                f"Invalid source. Must be one of: {', '.join(SOURCE_MODEL_MAP.keys())}",
                field="source",
            )

        # Build query filters
        filters = Q(year=year, share_article=share_article)

        if delivery_week is not None:
            filters &= Q(delivery_week=delivery_week)

        if day_number is not None:
            filters &= Q(day_number=day_number)

        # Query and aggregate
        results = (
            model.objects.filter(filters)
            .values("share_article__name", "unit", "size")
            .annotate(sum_amount=Sum("amount"))
            .filter(sum_amount__gt=0)
            .order_by("share_article__name", "unit", "size")
        )

        # Format response THROUGH the declared serializer: its
        # DecimalField turns the ``Sum()`` Decimal into the canonical
        # decimal string the schema promises — a raw ``Response(data)``
        # would let DRF's JSONEncoder ship the amount as a float,
        # violating the money/quantity-as-string rule.
        data = [
            {
                "share_article_name": result["share_article__name"],
                "unit": result["unit"],
                "size": result["size"],
                "amount": result["sum_amount"] or 0,
            }
            for result in results
        ]
        serializer = DocumentationAggregationItemSerializer(data, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)
