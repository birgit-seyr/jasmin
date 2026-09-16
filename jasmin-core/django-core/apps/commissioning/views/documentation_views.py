import logging
from typing import Any

from django.db.models import Q, Sum
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsStaff
from apps.shared.query_params import coerce_param
from core.serializers import ErrorResponseSerializer

from ..errors import InvalidQueryParam
from ..models import Harvest, Purchase, Waste
from ..schemas import (
    catalogue_param,
    get_day_number_parameter,
    get_delivery_week_parameter,
    get_share_article_parameter,
    get_year_parameter,
)
from ..serializers import DocumentationAggregationItemSerializer
from ..utils.query_params import PARAM_CATALOGUE, validate_query_params

logger = logging.getLogger(__name__)

# One entry per catalogued ``source`` value (DOCUMENTATION_SOURCES): the
# catalogue validates the parameter against that same tuple, so every value
# that reaches here has a model.
SOURCE_MODEL_MAP = {
    "HARVEST": Harvest,
    "PURCHASE": Purchase,
    "WASTE": Waste,
}


class DocumentationOverviewView(APIViewRolePermissionsMixin, APIView):
    """Get aggregated documentation data based on source type."""

    read_permission = IsStaff
    write_permission = IsStaff

    @staticmethod
    def _resolve_day_number(params: dict[str, Any]) -> int | None:
        """The weekday to filter on, from ``day_number`` or its ``delivery_day``
        alias.

        Clients built against the earlier spelling send the weekday number as
        ``delivery_day``, a name the catalogue types as a SharesDeliveryDay id
        (a string) elsewhere. An alias value that isn't a 0-6 weekday is
        therefore ignored rather than rejected — integrations written against
        that string shape used to get an unfiltered 200 here, and a 400 would
        break them. ``day_number`` itself stays strictly validated.
        """
        if params["day_number"] is not None:
            return params["day_number"]
        alias = params["delivery_day"]
        if alias is None:
            return None
        try:
            return coerce_param(alias, "delivery_day", PARAM_CATALOGUE["day_number"])
        except InvalidQueryParam:
            logger.info(
                "documentation_overview: ignoring delivery_day=%r (not a 0-6 weekday)",
                alias,
            )
            return None

    @extend_schema(
        summary="Documentation Aggregation Overview",
        description="""
        Aggregates documentation data (harvest, purchase, or waste) by share article.
        
        Returns sum of amounts grouped by:
        - Share article name
        - Unit (kg, pieces, etc.)
        - Size specification
        
        Can be filtered by year, week, and day_number.

        ``delivery_day`` is accepted as an alias for ``day_number``, carrying
        the same 0-6 weekday number, for clients built against the earlier
        spelling.

        The weekday filter applies to HARVEST and WASTE only: PURCHASE rows are
        week-scoped and carry no meaningful weekday, so they are aggregated over
        the whole week.
        """,
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(required=False),
            get_day_number_parameter(required=False),
            catalogue_param(
                "delivery_day",
                required=False,
                description=(
                    "Alias for day_number (0=Monday, 6=Sunday), kept for older "
                    "clients. Ignored when day_number is also sent, and ignored "
                    "when the value is not a 0-6 weekday."
                ),
            ),
            get_share_article_parameter(),
            catalogue_param(
                "source",
                required=False,
                description="Documentation source type (defaults to HARVEST)",
            ),
        ],
        responses={
            200: DocumentationAggregationItemSerializer(many=True),
            400: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        """Get aggregated documentation data.

        ``delivery_day`` is accepted as an alias for ``day_number`` so clients
        built against the earlier spelling keep filtering by weekday.
        """
        # Validate year + share_article (required) and the optional
        # week / day_number / source filters through the central catalogue.
        params = validate_query_params(
            request,
            required=["year", "share_article"],
            optional=["delivery_week", "day_number", "delivery_day", "source"],
        )

        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = self._resolve_day_number(params)
        share_article = params["share_article"]
        # The catalogue matches ``source`` case-insensitively and hands back
        # its own spelling, so this lookup always hits.
        model = SOURCE_MODEL_MAP[params["source"]]

        # Build query filters
        filters = Q(year=year, share_article=share_article)

        if delivery_week is not None:
            filters &= Q(delivery_week=delivery_week)

        # Purchases are week-scoped: an office-entered row carries no weekday at
        # all and the automated writers stamp the PURCHASE_DAY sentinel, so a
        # weekday filter empties the source instead of narrowing it. The CSV
        # export keeps purchases on WEEK overlap for the same reason.
        if day_number is not None and model is not Purchase:
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
