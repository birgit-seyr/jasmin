from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin
from apps.shared.query_params import parse_body_bool
from apps.shared.request_utils import body
from core.serializers import ErrorResponseSerializer

from ..errors import (
    MarketArticleInUse,
    MarketProductGroupInUse,
    RequiredFieldMissing,
    ScaleTaxCodeInUse,
)
from ..models import (
    MarketArticle,
    MarketPrice,
    MarketProductGroup,
    ScaleTaxCode,
)
from ..schemas import (
    get_delivery_week_parameter,
    get_is_active_parameter,
    get_year_parameter,
)
from ..serializers import (
    BulkIdsRequestSerializer,
    MarketArticleSerializer,
    MarketPriceBulkActiveRequestSerializer,
    MarketPriceCopyResultSerializer,
    MarketPriceSerializer,
    MarketProductGroupSerializer,
    ScaleTaxCodeSerializer,
)
from ..services.market_prices import (
    copy_to_next_week,
    previous_week_prices,
    set_active,
)
from ..services.market_scale_export import scale_export_workbook
from ..utils.query_params import validate_query_params
from ..utils.validation_utils import parse_bulk_ids
from .base_viewsets import CanBeDeletedDestroyMixin

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MarketProductGroupViewSet(
    CanBeDeletedDestroyMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = MarketProductGroupSerializer
    not_deletable_error = MarketProductGroupInUse

    @extend_schema(parameters=[get_is_active_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[MarketProductGroup]:
        queryset = MarketProductGroup.objects.order_by("number")
        if self.action == "list":
            is_active = validate_query_params(self.request, optional=["is_active"])[
                "is_active"
            ]
            if is_active is not None:
                queryset = queryset.filter(is_active=is_active)
        return queryset


class MarketArticleViewSet(
    CanBeDeletedDestroyMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = MarketArticleSerializer
    not_deletable_error = MarketArticleInUse

    @extend_schema(parameters=[get_is_active_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[MarketArticle]:
        queryset = MarketArticle.objects.select_related(
            "share_article", "product_group"
        ).order_by("plu_number")
        if self.action == "list":
            is_active = validate_query_params(self.request, optional=["is_active"])[
                "is_active"
            ]
            if is_active is not None:
                queryset = queryset.filter(is_active=is_active)
        return queryset


class MarketPriceViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = MarketPriceSerializer

    @extend_schema(
        parameters=[get_year_parameter(), get_delivery_week_parameter()],
        description="The week's market prices, by product group and PLU number.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[MarketPrice]:
        queryset = MarketPrice.objects.select_related("market_article__product_group")
        if self.action == "list":
            params = validate_query_params(
                self.request, required=["year", "delivery_week"]
            )
            queryset = queryset.filter(
                year=params["year"], delivery_week=params["delivery_week"]
            ).order_by(
                "market_article__product_group__number",
                "market_article__plu_number",
            )
        return queryset

    def get_serializer_context(self) -> dict[str, Any]:
        context = dict(super().get_serializer_context())
        if self.action == "list":
            params = validate_query_params(
                self.request, required=["year", "delivery_week"]
            )
            context["previous_prices"] = previous_week_prices(
                params["year"], params["delivery_week"]
            )
        return context

    @extend_schema(
        description=(
            "Copy the selected prices into the week after their own. A PLU that "
            "already has a price there keeps it, and its copy is skipped."
        ),
        request=BulkIdsRequestSerializer,
        responses={
            201: MarketPriceCopyResultSerializer,
            # ``RequiredFieldMissing`` / ``BulkIdsInvalid`` — bad ``ids``.
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"])
    def bulk_copy_to_next_week(self, request: Request) -> Response:
        result = copy_to_next_week(parse_bulk_ids(request))
        return Response(result, status=status.HTTP_201_CREATED)

    @extend_schema(
        description="Put the selected prices on sale or take them off it.",
        request=MarketPriceBulkActiveRequestSerializer,
        responses={
            204: None,
            # ``RequiredFieldMissing`` / ``BulkIdsInvalid`` / a flag that isn't
            # a boolean.
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"])
    def bulk_set_active(self, request: Request) -> Response:
        ids = parse_bulk_ids(request)
        data = body(request)
        if data.get("is_active") in (None, ""):
            raise RequiredFieldMissing("is_active is required.", field="is_active")
        set_active(ids, parse_body_bool(data, "is_active"))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        description=(
            "The XLSX the market scales import: the week's active prices by PLU "
            "number."
        ),
        parameters=[get_year_parameter(), get_delivery_week_parameter()],
        responses={
            (200, XLSX_CONTENT_TYPE): OpenApiTypes.BINARY,
            # ``ScaleUnitUnsupported``.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def scale_export(self, request: Request) -> HttpResponse:
        params = validate_query_params(request, required=["year", "delivery_week"])
        year, delivery_week = params["year"], params["delivery_week"]
        response = HttpResponse(
            scale_export_workbook(year, delivery_week), content_type=XLSX_CONTENT_TYPE
        )
        response["Content-Disposition"] = (
            f'attachment; filename="scale_export_{year}_{delivery_week:02d}.xlsx"'
        )
        return response


class ScaleTaxCodeViewSet(
    CanBeDeletedDestroyMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = ScaleTaxCodeSerializer
    not_deletable_error = ScaleTaxCodeInUse

    def get_queryset(self) -> QuerySet[ScaleTaxCode]:
        return ScaleTaxCode.objects.order_by("tax_rate")
