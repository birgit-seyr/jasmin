from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import F, QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
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

from ..errors import CommissioningError, ForecastNotFound, RequiredFieldMissing
from ..models import (
    Forecast,
    Plot,
)
from ..schemas import (
    EXPORT_DATE_RANGE_PARAMETERS,
    get_day_number_parameter,
    get_delivery_week_parameter,
    get_include_next_week_parameter,
    get_is_active_parameter,
    get_is_past_parameter,
    get_is_preparation_lists_parameter,
    get_model_parameter,
    get_seller_parameter,
    get_year_parameter,
)
from ..serializers import (
    DocumentationSummaryRowSerializer,
    ForecastSerializer,
    HarvestBulkSetAsExpectedRequestSerializer,
    HarvestSerializer,
    PlotSerializer,
    PurchaseBulkSetAsExpectedRequestSerializer,
    PurchaseSerializer,
    WasteSerializer,
)
from ..serializers.documentation_serializer import ForecastRowSerializer
from ..services import (
    DocumentationExportService,
    DocumentationSummaryService,
    ForecastService,
    GenericDocumentationService,
)
from ..utils.query_params import DOCUMENTATION_MODELS, validate_query_params
from .base_viewsets import BaseArchivableViewSet

# Single source: the query-param catalogue owns the documentation model keys.
VALID_MODELS = list(DOCUMENTATION_MODELS)

_EXPORT_DATE_PARAMETERS = [
    *EXPORT_DATE_RANGE_PARAMETERS,
    OpenApiParameter(
        name="summed",
        type=bool,
        required=False,
        description="If true, sum amounts by share article instead of listing individual rows.",
    ),
]

# Shared schema for create/update endpoints that echo the freshly written
# row in documentation-summary shape instead of the model serializer.
_SUMMARY_ROW_RESPONSE = OpenApiResponse(
    response=DocumentationSummaryRowSerializer,
    description=(
        "The freshly written row echoed in documentation-summary shape "
        "(see the summary action). May be ``{}`` when the row no longer "
        "matches the summary filters. Note: two seeded harvest storages add "
        "dynamic ``storage_<id>`` boolean keys not listed here."
    ),
)

_CSV_EXPORT_RESPONSES = {
    (200, "text/csv"): OpenApiTypes.BINARY,
    400: ErrorResponseSerializer,
}

# Request body of the two additional-theoretical-amount actions:
# ``model`` discriminates the documentation model; the remaining keys are
# that model's row fields, consumed verbatim by the service.
_ADDITIONAL_THEORETICAL_REQUEST = {
    "application/json": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "enum": VALID_MODELS,
                "description": "Documentation model the row belongs to.",
            },
        },
        "required": ["model"],
        "additionalProperties": {},
    }
}


def _csv_export_response(request: Request, model: str) -> HttpResponse:
    """Thin wrapper that delegates to :class:`DocumentationExportService`.

    ``InvalidExportDates`` (a ``BadRequestError`` subclass) is translated to
    a 400 by ``core.exception_handler``.
    """
    # ``date_from``/``date_to`` are read raw: the export service consumes them
    # as strings (its own ``date.fromisoformat`` range check → InvalidExportDates
    # 400, plus the literal strings in the download filename). The catalogue's
    # ``date`` kind returns ``date`` objects, which would break ``fromisoformat``.
    params = validate_query_params(request, optional=["summed"])
    return DocumentationExportService.export_csv(
        model=model,
        date_from=request.query_params.get("date_from"),
        date_to=request.query_params.get("date_to"),
        summed=bool(params["summed"]),
    )


def _validated_model(request: Request) -> str:
    """Return the lowercased ``model`` discriminator from the request body.

    Raises :class:`CommissioningError` (rendered as 400) when it isn't one of
    :data:`VALID_MODELS`. Used by the two additional-theoretical-amount
    actions, whose body uses ``model`` to pick the documentation model.
    """
    model = str(request.data.get("model") or "").lower()
    if model not in VALID_MODELS:
        raise CommissioningError(
            f"Invalid model '{model}'. Must be one of: {VALID_MODELS}",
            field="model",
            code="documentation.invalid_model",
        )
    return model


def _optional_summary_scope(instance: Any) -> dict[str, Any]:
    """``day_number``/``seller`` summary filters for an additional-theoretical row.

    The four discriminated models don't all carry both fields, so each is
    included only when the instance has a non-null value — mirroring the
    summary action's "filter only when provided" semantics.
    """
    scope: dict[str, Any] = {}
    if getattr(instance, "day_number", None) is not None:
        scope["day_number"] = instance.day_number
    if getattr(instance, "seller", None) is not None:
        scope["seller"] = instance.seller
    return scope


def _summary_echo_response(
    instance: Any,
    model: str,
    status_code: int,
    *,
    extra: dict[str, Any] | None = None,
) -> Response:
    """Echo a freshly written documentation row in documentation-summary shape.

    Re-reads just the mutated row through ``get_summary`` so the client gets
    the same computed/stock fields the summary grid shows for it, then returns
    it with ``status_code`` — ``201`` on create, ``200`` on update (the latter
    is the contract the PATCH/PUT callers must honour). ``extra`` carries the
    per-model scope filters: ``seller`` for purchases, ``day_number`` for
    harvests, or the conditional pair from :func:`_optional_summary_scope` for
    the additional-theoretical models. Returns ``{}`` when the row no longer
    matches the summary filters.
    """
    summary_data = DocumentationSummaryService.get_summary(
        year=instance.year,
        delivery_week=instance.delivery_week,
        model=model,
        is_past=False,
        single_id=instance.id,
        **(extra or {}),
    )
    row = summary_data[0] if summary_data else {}
    return Response(row, status=status_code)


class PlotViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = PlotSerializer

    @extend_schema(parameters=[get_is_active_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Plot]:
        queryset = Plot.objects.all()
        is_active = validate_query_params(self.request, optional=["is_active"])[
            "is_active"
        ]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset


class ForecastViewSet(BaseArchivableViewSet):
    serializer_class = ForecastSerializer

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.forecast_service = ForecastService()

    @transaction.atomic
    def perform_destroy(self, instance: Forecast) -> None:
        # Deleting a Forecast cascade-deletes its ShareContent rows + the
        # forecast-linked TheoreticalHarvest rows, and with them their stock
        # movements — but the plain DRF destroy never recomputes. Capture those
        # movements first, then re-cascade snapshots + re-derive actual
        # corrections so the stock projection isn't left permanently too high
        # (mirrors delete_share_planning; the create/update paths warn about
        # exactly this strand).
        from django.db.models import Q

        from ..models import MovementShareArticle, ShareContent
        from ..models.movements import share_content_movement_q
        from ..services.snapshot_service import SnapshotService
        from ..services.theoretical_objects import recalculate_actual_corrections

        share_contents = ShareContent.objects.filter(forecast=instance)
        # Wide capture (both movement halves) plus this Forecast's own
        # theoretical-harvest movements: TheoreticalHarvest rows linked directly
        # via the ``forecast`` FK carry ``share_content=NULL``, so the
        # share-content-based helper alone wouldn't reach them.
        affected_movements = list(
            MovementShareArticle.objects.filter(
                share_content_movement_q(share_contents)
                | Q(theoretical_harvest__forecast=instance)
            )
        )

        super().perform_destroy(instance)

        if affected_movements:
            SnapshotService.cascade_for_movements(affected_movements)
            recalculate_actual_corrections(affected_movements)

    def apply_filters(self, queryset: QuerySet[Forecast]) -> QuerySet[Forecast]:
        params = validate_query_params(self.request, optional=["year", "delivery_week"])
        year = params["year"]
        delivery_week = params["delivery_week"]

        if year is not None and delivery_week is not None:
            queryset = (
                queryset.filter(year=year, delivery_week=delivery_week)
                .select_related("share_article", "plot")
                .prefetch_related(
                    "forecastsharetypevariation_set__share_type_variation",
                    "forecastoffergroup_set__offer_group",
                )
            )

        return queryset

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_is_past_parameter(),
        ],
        description="List forecasts. When year and delivery_week are provided, "
        "returns flattened data with variation and offer group flags.",
        responses={200: ForecastRowSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # year + delivery_week are REQUIRED (the @extend_schema documents them
        # as such, and the only caller always sends both). Enforcing it keeps
        # every list call on the prefetched ``get_forecasts_with_relations``
        # path — the previous ``optional`` validation let a no-param request
        # fall through to an unfiltered, unprefetched ``super().list()`` over
        # every forecast row (N+1 on share_article / plot + variation/offer
        # reverse relations).
        params = validate_query_params(
            request, required=["year", "delivery_week"], optional=["is_past"]
        )
        forecasts_data = self.forecast_service.get_forecasts_with_relations(
            year=params["year"],
            delivery_week=params["delivery_week"],
            is_past=params["is_past"],
        )
        return Response(forecasts_data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Create a forecast with related variation and offer group objects."
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        forecast = self.forecast_service.create_forecast_with_related_objects(
            validated_data=serializer.validated_data
        )

        response_serializer = self.get_serializer(forecast)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description="Update a forecast and its related variation and offer group objects."
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        forecast = self.forecast_service.update_forecast_with_related_objects(
            instance=instance, validated_data=serializer.validated_data
        )

        response_serializer = self.get_serializer(forecast)
        return Response(response_serializer.data)

    @extend_schema(
        description="Copy selected forecasts to the next delivery week.",
        request={
            "application/json": {
                "type": "object",
                "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
            }
        },
        responses={
            201: inline_serializer(
                name="ForecastBulkCopyResponse",
                fields={"success": drf_serializers.BooleanField()},
            ),
            # ``RequiredFieldMissing`` — empty/missing ``ids``.
            400: ErrorResponseSerializer,
            # ``ForecastNotFound`` — collection POST, no auto-404.
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"])
    @transaction.atomic
    def bulk_copy_to_next_week(
        self, request: Request, *args: Any, **kwargs: Any
    ) -> Response:
        selected_ids: list[str] = request.data.get("ids", [])

        if not selected_ids:
            raise RequiredFieldMissing("No forecast IDs provided", field="ids")

        # Prefetch the variation / offer-group relations the per-forecast copy
        # walks (bulk_copy_forecast_to_next_week reads
        # forecastsharetypevariation_set / forecastoffergroup_set .all()), so a
        # multi-forecast copy doesn't fan out into per-instance relation queries.
        forecast_instances = Forecast.objects.filter(
            id__in=selected_ids
        ).prefetch_related("forecastsharetypevariation_set", "forecastoffergroup_set")

        if not forecast_instances.exists():
            raise ForecastNotFound("No valid forecasts found")

        for instance in forecast_instances:
            self.forecast_service.bulk_copy_forecast_to_next_week(
                instance=instance,
                validated_data={},
            )

        return Response({"success": True}, status=status.HTTP_201_CREATED)


class _MovementSourceDestroyMixin:
    """``perform_destroy`` that re-cascades stock snapshots after deleting a
    movement-source row (Harvest/Purchase/Waste).

    Deleting the row cascade-deletes its ``MovementShareArticle`` (the source FK
    is ``on_delete=CASCADE``); the plain DRF destroy never recomputes, so capture
    the movement BEFORE the delete and re-cascade the affected entity. Mirrors
    ``ForecastViewSet.perform_destroy`` — but no ``recalculate_actual_corrections``
    is needed because the deleted movement IS the actual correction.
    """

    movement_source_fk: str  # "harvest" / "purchase" / "waste"

    @transaction.atomic
    def perform_destroy(self, instance) -> None:
        from ..models import MovementShareArticle
        from ..services.snapshot_service import SnapshotService

        affected_movements = list(
            MovementShareArticle.objects.filter(**{self.movement_source_fk: instance})
        )
        super().perform_destroy(instance)
        if affected_movements:
            SnapshotService.cascade_for_movements(affected_movements)


class WasteViewSet(_MovementSourceDestroyMixin, BaseArchivableViewSet):
    movement_source_fk = "waste"
    serializer_class = WasteSerializer

    def apply_filters(self, queryset: QuerySet) -> QuerySet:
        params = validate_query_params(
            self.request, optional=["year", "delivery_week", "day_number"]
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]

        if year is not None:
            queryset = queryset.filter(year=year)
        if delivery_week is not None:
            queryset = queryset.filter(delivery_week=delivery_week)
        if day_number is not None:
            queryset = queryset.filter(day_number=day_number)

        queryset = queryset.select_related("share_article").annotate(
            share_article_name=F("share_article__name")
        )

        return queryset

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_is_past_parameter(),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(description="Create a waste record with related objects.")
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        waste = GenericDocumentationService.create_waste_with_related_objects(
            validated_data=serializer.validated_data
        )

        response_serializer = self.get_serializer(waste)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(description="Update a waste record with related objects.")
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        waste = GenericDocumentationService.update_waste_with_related_objects(
            instance=instance, validated_data=serializer.validated_data
        )

        response_serializer = self.get_serializer(waste)
        return Response(response_serializer.data)


class PurchaseViewSet(_MovementSourceDestroyMixin, BaseArchivableViewSet):
    movement_source_fk = "purchase"
    serializer_class = PurchaseSerializer

    @extend_schema(
        description="Create a purchase with related objects and return its summary.",
        responses={201: _SUMMARY_ROW_RESPONSE},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purchase = GenericDocumentationService.create_purchase_with_related_objects(
            validated_data=serializer.validated_data
        )

        return _summary_echo_response(
            purchase,
            "purchase",
            status.HTTP_201_CREATED,
            extra={"seller": purchase.seller},
        )

    @extend_schema(
        description="Update a purchase and return its updated summary.",
        responses={200: _SUMMARY_ROW_RESPONSE},
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        purchase = GenericDocumentationService.update_purchase_with_related_objects(
            instance=instance, validated_data=serializer.validated_data
        )

        return _summary_echo_response(
            purchase,
            "purchase",
            status.HTTP_200_OK,
            extra={"seller": purchase.seller},
        )

    @extend_schema(
        description="Set theoretical/expected purchase amounts as actual purchases.",
        request=PurchaseBulkSetAsExpectedRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def bulk_set_as_expected(self, request: Request) -> Response:
        serializer = PurchaseBulkSetAsExpectedRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DocumentationSummaryService.bulk_set_purchase_as_expected(
            serializer.validated_data
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        description="Export purchase data as CSV for a date range.",
        parameters=_EXPORT_DATE_PARAMETERS,
        responses=_CSV_EXPORT_RESPONSES,
    )
    @action(detail=False, methods=["get"])
    def export_csv(self, request: Request) -> HttpResponse:
        return _csv_export_response(request, model="purchase")


class DocumentationSummaryViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """
    Shared endpoints for documentation summaries across all models
    (harvest, purchase, washamount, cleanamount).
    """

    read_permission = IsStaff
    write_permission = IsStaff
    # Pure ViewSet — every @action below has its own @extend_schema.
    # Class-level placeholder silences spectacular's "unable to guess
    # serializer" warning without affecting the actual schema.
    # ``inline_serializer`` gives the placeholder a unique component
    # name (plain ``serializers.Serializer`` would produce "" + warning).
    serializer_class = inline_serializer(
        name="DocumentationSummaryPlaceholder", fields={}
    )

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=False),
            get_is_past_parameter(),
            get_model_parameter(required=True),
            get_seller_parameter(),
            get_include_next_week_parameter(),
            get_is_preparation_lists_parameter(),
        ],
        description="Get documentation summary grouped by share article, unit, and size.",
        responses={
            200: OpenApiResponse(
                response=DocumentationSummaryRowSerializer(many=True),
                description=(
                    "Summary rows in documentation-summary shape. Per-model "
                    "amount keys are prefixed with the requested model; two "
                    "seeded harvest storages add dynamic ``storage_<id>`` "
                    "boolean keys not listed in the schema."
                ),
            )
        },
    )
    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "model"],
            optional=[
                "day_number",
                "is_past",
                "seller",
                "include_next_week",
                "is_preparation_lists",
            ],
        )

        results = DocumentationSummaryService.get_summary(
            params["year"],
            params["delivery_week"],
            params["model"],
            params["day_number"],
            params["is_past"],
            include_next_week=params["include_next_week"],
            seller=params["seller"],
            is_preparation_lists=params["is_preparation_lists"],
        )
        return Response(results, status=status.HTTP_200_OK)

    @extend_schema(
        description="Add an additional theoretical amount for any documentation model.",
        # Not HarvestSerializer: ``model`` is the load-bearing discriminator
        # and the remaining keys are the per-model row fields the service
        # consumes — a model serializer can't express that.
        request=_ADDITIONAL_THEORETICAL_REQUEST,
        responses={
            201: _SUMMARY_ROW_RESPONSE,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"])
    def add_additional_theoretical_amount(self, request: Request) -> Response:
        model = _validated_model(request)

        instance = DocumentationSummaryService.add_additional_theoretical_amount(
            request.data, model
        )

        return _summary_echo_response(
            instance,
            model,
            status.HTTP_201_CREATED,
            extra=_optional_summary_scope(instance),
        )

    @extend_schema(
        description="Update an existing additional theoretical amount for any documentation model.",
        request=_ADDITIONAL_THEORETICAL_REQUEST,
        responses={200: _SUMMARY_ROW_RESPONSE},
    )
    @action(
        detail=False,
        methods=["patch", "put"],
        url_path="update_additional_theoretical_amount/(?P<pk>[^/.]+)",
    )
    def update_additional_theoretical_amount(
        self, request: Request, pk: str
    ) -> Response:
        model = _validated_model(request)

        instance = DocumentationSummaryService.update_additional_theoretical_amount(
            request.data, pk, model
        )

        # 200, not 201 — this PATCH/PUT action updates an existing row.
        return _summary_echo_response(
            instance,
            model,
            status.HTTP_200_OK,
            extra=_optional_summary_scope(instance),
        )


class HarvestViewSet(_MovementSourceDestroyMixin, BaseArchivableViewSet):
    movement_source_fk = "harvest"
    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = HarvestSerializer

    @extend_schema(
        description="Create a harvest with related objects and return its summary.",
        responses={201: _SUMMARY_ROW_RESPONSE},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        harvest = GenericDocumentationService.create_harvest_with_related_objects(
            validated_data=serializer.validated_data
        )

        return _summary_echo_response(
            harvest,
            "harvest",
            status.HTTP_201_CREATED,
            extra={"day_number": harvest.day_number},
        )

    @extend_schema(
        description="Update a harvest and return its updated summary.",
        responses={200: _SUMMARY_ROW_RESPONSE},
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        harvest = GenericDocumentationService.update_harvest_with_related_objects(
            instance=instance, validated_data=serializer.validated_data
        )

        return _summary_echo_response(
            harvest,
            "harvest",
            status.HTTP_200_OK,
            extra={"day_number": harvest.day_number},
        )

    @extend_schema(
        description="Set theoretical/expected harvest amounts as actual harvests.",
        request=HarvestBulkSetAsExpectedRequestSerializer,
        responses={204: None},
    )
    @action(detail=False, methods=["post"])
    def bulk_set_as_expected(self, request: Request) -> Response:
        serializer = HarvestBulkSetAsExpectedRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DocumentationSummaryService.bulk_set_as_expected(serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        description="Export harvest data as CSV for a date range.",
        parameters=_EXPORT_DATE_PARAMETERS,
        responses=_CSV_EXPORT_RESPONSES,
    )
    @action(detail=False, methods=["get"])
    def export_csv(self, request: Request) -> HttpResponse:
        return _csv_export_response(request, model="harvest")
