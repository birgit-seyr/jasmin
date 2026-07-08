from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin
from core.serializers import ErrorResponseSerializer

from ..errors import ShareContentError
from ..schemas import (
    get_day_number_parameter,
    get_delivery_station_parameter,
    get_delivery_week_parameter,
    get_is_past_parameter,
    get_packing_station_parameter,
    get_share_article_parameter,
    get_share_option_parameter,
    get_share_type_parameter,
    get_tour_parameter,
    get_year_parameter,
)
from ..serializers import (
    HarvestSharePlanningBackupRequestSerializer,
    HarvestSharePlanningCreateRequestSerializer,
    HarvestSharePlanningUpdateRequestSerializer,
)
from ..serializers.shares_serializer import (
    HarvestSharePlanningRowSerializer,
    PackingBoxesMatrixSerializer,
    PackingListRowSerializer,
)
from ..services import (
    PackingListBoxesMatrixService,
    PackingListService,
    ShareContentService,
)
from ..utils.composite_id_utils import parse_composite_pk
from ..utils.query_params import validate_query_params

logger = logging.getLogger(__name__)

# Composite pk schema for a harvest-share-planning slot:
# ``{year}_{delivery_week}_{share_article}_{unit}_{size}``.
_PLANNING_PK_FIELDS = [
    ("year", int),
    ("delivery_week", int),
    ("share_article", str),
    ("unit", str),
    ("size", str),
]


class HarvestSharePlanningViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """ViewSet for managing harvest share planning data."""

    read_permission = IsStaff
    write_permission = IsOffice
    # Empty placeholder: this is a pure ViewSet (no auto-generated CRUD
    # routes), every action below has its own @extend_schema. The class
    # attr silences spectacular's "unable to guess serializer" warning
    # without affecting the actual generated schema. ``inline_serializer``
    # gives the placeholder a unique name — using plain
    # ``drf_serializers.Serializer`` produces a "" component name + warning.
    serializer_class = inline_serializer(
        name="HarvestSharePlanningPlaceholder", fields={}
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.service = ShareContentService()

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_share_article_parameter(required=False),
            get_share_option_parameter(required=True),
            get_is_past_parameter(),
        ],
        responses={200: HarvestSharePlanningRowSerializer(many=True)},
        description="List share content data for a given week.",
    )
    def list(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "share_option"],
            optional=["share_article", "is_past"],
        )

        data = self.service.get_share_content_for_week(
            year=params["year"],
            delivery_week=params["delivery_week"],
            share_article=params["share_article"],
            share_option=params["share_option"],
            is_past=params["is_past"],
        )

        return Response(data)

    @extend_schema(
        request=HarvestSharePlanningCreateRequestSerializer,
        # Returns the default 200 (not the usual create 201) — the action
        # responds with the recomputed group row, not a created resource.
        responses={
            200: HarvestSharePlanningRowSerializer,
            # DRF field validation (is_valid) / ``ShareContentError`` below.
            400: ErrorResponseSerializer,
        },
        description="Create new share content from planning data.",
    )
    def create(self, request: Request) -> Response:
        serializer = HarvestSharePlanningCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # ``validated_data`` carries the dynamic ``day_<id>_variation_<id>`` cells:
        # ``DynamicAmountKeysMixin`` validates and merges them back in (coerced
        # Decimals under their original keys), so ``_extract_day_variations``
        # reads them straight from the validated payload — no second walk of the
        # raw request.
        share_contents = self.service.process_share_planning_data(
            serializer.validated_data
        )
        # CREATE with no amounts is a malformed request — the user has to
        # plan at least one cell to create a slot. ``process_share_planning
        # _data`` itself no longer raises on empty input (UPDATE relies on
        # empty meaning "clear this slot"); enforce the create-specific
        # rule here instead.
        if not share_contents:
            raise ShareContentError("Please enter at least one amount.")
        group_data = self.service.get_group_data(share_contents)
        return Response(group_data)

    @extend_schema(
        request=HarvestSharePlanningUpdateRequestSerializer,
        responses={200: HarvestSharePlanningRowSerializer},
        description="Update share content. PK format: {year}_{delivery_week}_{share_article}_{unit}_{size}",
    )
    def update(self, request: Request, pk: str | None = None) -> Response:
        parsed = parse_composite_pk(
            pk, fields=_PLANNING_PK_FIELDS, code="share_content.invalid_pk"
        )
        year = parsed["year"]
        delivery_week = parsed["delivery_week"]
        share_article = parsed["share_article"]
        unit = parsed["unit"]
        size = parsed["size"]
        serializer = HarvestSharePlanningUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # ``validated_data`` carries the dynamic ``day_<id>_variation_<id>`` cells
        # (merged by ``DynamicAmountKeysMixin``). The empty-clear semantics still
        # hold: a slot the user cleared has no usable cells, so the extraction is
        # empty and ``replace_share_planning`` takes its clear path.
        share_contents = self.service.replace_share_planning(
            year=int(year),
            delivery_week=int(delivery_week),
            share_article_id=share_article,
            unit=unit,
            size=size,
            data=serializer.validated_data,
        )
        group_data = self.service.get_group_data(share_contents)
        if group_data is None:
            # The slot ended the request with zero rows — an ad-hoc row
            # whose user cleared every cell, with no forecast scaffold
            # to keep around. Send a minimal placeholder carrying the
            # slot identity so the EditableTable can replace the row
            # in-place without choking on a null payload; the next list
            # refetch (invalidated by the frontend's save success
            # handler) will drop the row entirely.
            group_data = {
                "id": pk,
                "year": int(year),
                "delivery_week": int(delivery_week),
                "share_article": share_article,
                "unit": unit,
                "size": size,
                "variations": {},
                "basic_variations": {},
                "tour_variations": {},
            }
        return Response(group_data)

    @extend_schema(
        request=HarvestSharePlanningUpdateRequestSerializer,
        responses={200: HarvestSharePlanningRowSerializer},
        description=(
            "Partially update share content (same behaviour as PUT). "
            "PK format: {year}_{delivery_week}_{share_article}_{unit}_{size}"
        ),
    )
    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        return self.update(request, pk)

    @extend_schema(
        # Returns 200 with a message body, not the usual destroy 204.
        responses={
            200: inline_serializer(
                name="HarvestSharePlanningDeleteResponse",
                fields={"message": drf_serializers.CharField()},
            )
        },
        description="Delete share content. PK format: {year}_{delivery_week}_{share_article}_{unit}_{size}",
    )
    def destroy(self, request: Request, pk: str | None = None) -> Response:
        parsed = parse_composite_pk(
            pk, fields=_PLANNING_PK_FIELDS, code="share_content.invalid_pk"
        )
        year = parsed["year"]
        delivery_week = parsed["delivery_week"]
        share_article = parsed["share_article"]
        unit = parsed["unit"]
        size = parsed["size"]
        # ``delete_share_planning`` raises ``ShareContentNotFound`` (404) when no
        # rows match; the central exception handler maps it to the canonical body.
        deleted_count = self.service.delete_share_planning(
            year=int(year),
            delivery_week=int(delivery_week),
            share_article_id=share_article,
            unit=unit,
            size=size,
        )
        return Response(
            {
                "message": f"Successfully deleted {deleted_count} share content entries",
            }
        )

    @extend_schema(
        request=HarvestSharePlanningBackupRequestSerializer,
        responses={200: HarvestSharePlanningRowSerializer},
        description=(
            "Update backup fields on existing ShareContent rows. "
            "PK format: {year}_{delivery_week}_{share_article}_{unit}_{size}. "
            "Payload: backup_share_article, backup_unit, backup_size, "
            "and day_{day_id}_variation_{var_id} amounts."
        ),
    )
    @action(detail=True, methods=["put"], url_path="backup")
    def backup(self, request: Request, pk: str | None = None) -> Response:
        parsed = parse_composite_pk(
            pk, fields=_PLANNING_PK_FIELDS, code="share_content.invalid_pk"
        )
        year = parsed["year"]
        delivery_week = parsed["delivery_week"]
        share_article_id = parsed["share_article"]
        unit = parsed["unit"]
        size = parsed["size"]
        serializer = HarvestSharePlanningBackupRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # ``update_backup_fields`` raises typed errors — ``ShareContentNotFound``
        # (404) for a missing slot, ``ShareArticleNotFound`` (404) for an invalid
        # backup article — which the central handler maps to the canonical body.
        # ``validated_data`` carries the dynamic ``day_<id>_variation_<id>`` backup
        # amounts (merged by ``DynamicAmountKeysMixin``).
        share_contents = self.service.update_backup_fields(
            year=int(year),
            delivery_week=int(delivery_week),
            share_article_id=share_article_id,
            unit=unit,
            size=size,
            data=serializer.validated_data,
        )
        return Response(self.service.get_group_data(share_contents))


class PackingListViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    # See HarvestSharePlanningViewSet for the rationale.
    serializer_class = inline_serializer(name="PackingListPlaceholder", fields={})

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_share_type_parameter(required=True),
            get_is_past_parameter(),
            get_delivery_station_parameter(),
            get_tour_parameter(),
            get_packing_station_parameter(),
            OpenApiParameter(
                name="is_packed_bulk",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "Restrict to variations with this is_packed_bulk value. "
                    "Used in MIXED packing mode to split the list into "
                    "boxes (False) and bulk (True). Omit to include all."
                ),
            ),
        ],
        responses={200: PackingListRowSerializer(many=True)},
        description="Get packing list for a given week + delivery day (day_number).",
    )
    def list(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number", "share_type"],
            optional=[
                "is_past",
                "delivery_station",
                "tour",
                "packing_station",
                "is_packed_bulk",
            ],
        )

        packing_list = PackingListService.get_packing_list(
            year=params["year"],
            delivery_week=params["delivery_week"],
            day_number=params["day_number"],
            share_type=params["share_type"],
            is_past=params["is_past"],
            delivery_station=params["delivery_station"],
            tour=params["tour"],
            packing_station=params["packing_station"],
            is_packed_bulk=params["is_packed_bulk"],
        )

        return Response(packing_list, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_is_past_parameter(),
            get_delivery_station_parameter(),
            get_tour_parameter(),
            OpenApiParameter(
                name="is_packed_bulk",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "Restrict to variations with this is_packed_bulk value. "
                    "Used in MIXED packing mode to split the matrix into boxes "
                    "(False) and bulk (True). Omit to include all."
                ),
            ),
        ],
        responses={200: PackingBoxesMatrixSerializer},
        description=(
            "Packing boxes MATRIX for a week + delivery day: one column per box "
            "combination (a base box plus the additional shares packed into it, "
            "derived from actual subscriptions), one row per share_article, and "
            "each cell the per-box quantity. Unlike the per-variation packing "
            "list there is no share_type filter — every share type is included."
        ),
    )
    @action(detail=False, methods=["get"], url_path="boxes_matrix")
    def boxes_matrix(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number"],
            optional=[
                "is_past",
                "delivery_station",
                "tour",
                "is_packed_bulk",
            ],
        )

        matrix = PackingListBoxesMatrixService.get_boxes_matrix(
            year=params["year"],
            delivery_week=params["delivery_week"],
            day_number=params["day_number"],
            is_past=params["is_past"],
            delivery_station=params["delivery_station"],
            tour=params["tour"],
            is_packed_bulk=params["is_packed_bulk"],
        )

        return Response(matrix, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_is_past_parameter(),
            get_delivery_station_parameter(),
            get_tour_parameter(),
            OpenApiParameter(
                name="is_packed_bulk",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "Restrict to variations with this is_packed_bulk value. "
                    "Omit to include all."
                ),
            ),
        ],
        responses={200: PackingBoxesMatrixSerializer},
        description=(
            '"Was ihr nehmen könnt" — the per-SHARE amount matrix for a week + '
            "delivery day: one column per active share_type_variation (grouped "
            "by share type), one row per share_article, each cell the amount a "
            "member of that variation may take (ShareContent.amount, NOT summed "
            "by demand). ShareContent-based, so it also works for external-CSV "
            "tenants. Reuses the packing-boxes matrix response shape — add_ons "
            "are always empty and count is 0."
        ),
    )
    @action(detail=False, methods=["get"], url_path="member_amounts")
    def member_amounts(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number"],
            optional=[
                "is_past",
                "delivery_station",
                "tour",
                "is_packed_bulk",
            ],
        )

        matrix = PackingListService.get_member_amounts_matrix(
            year=params["year"],
            delivery_week=params["delivery_week"],
            day_number=params["day_number"],
            is_past=params["is_past"],
            delivery_station=params["delivery_station"],
            tour=params["tour"],
            is_packed_bulk=params["is_packed_bulk"],
        )

        return Response(matrix, status=status.HTTP_200_OK)


class PackingListBulkViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    # See HarvestSharePlanningViewSet for the rationale.
    serializer_class = inline_serializer(name="PackingListBulkPlaceholder", fields={})

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_share_type_parameter(required=False),
            get_is_past_parameter(),
            get_delivery_station_parameter(),
            OpenApiParameter(
                name="is_packed_bulk",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "Restrict to variations with this is_packed_bulk value. "
                    "Used in MIXED packing mode to limit the bulk list to "
                    "variations actually packed in bulk. Omit to include all."
                ),
            ),
        ],
        responses={
            200: inline_serializer(
                name="PackingListBulkRow",
                fields={
                    "id": drf_serializers.CharField(),
                    "delivery_station": drf_serializers.CharField(),
                    "delivery_station_name": drf_serializers.CharField(),
                    "share_article": drf_serializers.CharField(),
                    "share_article_name": drf_serializers.CharField(),
                    "unit": drf_serializers.CharField(),
                    "size": drf_serializers.CharField(),
                    "total_amount": drf_serializers.FloatField(),
                    "note": drf_serializers.CharField(allow_blank=True),
                },
                many=True,
            )
        },
        description=(
            "Per-delivery-station bulk packing list. For each "
            "(delivery_station, share_article) returns the total physical "
            "amount needed (amount_per_share × physical_share_type_variation"
            "_count summed across every variation, with virtual "
            "share_type_variations resolved into their physical components). "
            "Rows are summed across ALL share_types by default — the bulk list "
            "is a per-article warehouse total that ignores share_type; pass "
            "share_type to scope to one. Pass delivery_station to scope the "
            "result to a single station; omit it to get rows for every station."
        ),
    )
    def list(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number"],
            optional=["share_type", "is_past", "delivery_station", "is_packed_bulk"],
        )

        packing_list_bulk = PackingListService.get_packing_list_bulk(
            year=params["year"],
            delivery_week=params["delivery_week"],
            day_number=params["day_number"],
            share_type=params["share_type"],
            is_past=params["is_past"],
            delivery_station=params["delivery_station"],
            is_packed_bulk=params["is_packed_bulk"],
        )

        return Response(packing_list_bulk, status=status.HTTP_200_OK)
