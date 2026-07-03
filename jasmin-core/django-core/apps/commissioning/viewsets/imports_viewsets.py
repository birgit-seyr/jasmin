from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, RolePermissionsMixin

from ..errors import CommissioningError
from ..models import (
    ExternalCodeMapping,
    ExternalShareDemand,
    ShareImportBatch,
)
from ..schemas import get_delivery_week_parameter, get_year_parameter
from ..serializers.imports_serializer import (
    ExternalCodeMappingSerializer,
    ExternalShareDemandSerializer,
    ShareImportBatchSerializer,
    ShareImportUploadSerializer,
)
from ..services.share_import_service import ShareImportService
from ..utils.query_params import validate_query_params


class ExternalCodeMappingViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """CRUD for the external-code → internal-id translation table.

    Office users maintain this manually before they can import a CSV that
    references upstream codes.
    """

    read_permission = IsOffice
    write_permission = IsOffice
    serializer_class = ExternalCodeMappingSerializer
    queryset = ExternalCodeMapping.objects.all().order_by("kind", "external_code")

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "kind",
                str,
                required=False,
                description="variation | station | day",
            ),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ExternalCodeMapping]:
        qs = super().get_queryset()
        params = validate_query_params(self.request, optional=["kind"])
        if kind := params["kind"]:
            qs = qs.filter(kind=kind)
        return qs


class ShareImportBatchViewSet(RolePermissionsMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only listing/detail for past import batches.

    Mutations (upload, validate, preview, apply) live on dedicated
    ``@action`` endpoints below — not standard CRUD.
    """

    read_permission = IsOffice
    write_permission = IsOffice
    serializer_class = ShareImportBatchSerializer
    queryset = ShareImportBatch.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        parameters=[
            OpenApiParameter("year", int, required=False),
            OpenApiParameter("delivery_week", int, required=False),
            OpenApiParameter("status", str, required=False),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ShareImportBatch]:
        qs = super().get_queryset()
        params = validate_query_params(
            self.request, optional=["year", "delivery_week", "status"]
        )
        if (year := params["year"]) is not None:
            qs = qs.filter(year=year)
        if (week := params["delivery_week"]) is not None:
            qs = qs.filter(delivery_week=week)
        if status_value := params["status"]:
            qs = qs.filter(status=status_value)
        return qs

    # ---- 1. upload + parse + validate -----------------------------------

    @extend_schema(
        request=ShareImportUploadSerializer,
        responses={201: ShareImportBatchSerializer},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload(self, request: Request) -> Response:
        serializer = ShareImportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        f = serializer.validated_data["file"]
        year = serializer.validated_data["year"]
        week = serializer.validated_data["delivery_week"]

        batch = ShareImportService.ingest_upload(
            file_bytes=f.read(),
            original_filename=f.name,
            year=year,
            delivery_week=week,
            uploaded_by=request.user,
        )
        # Run parse+validate synchronously so the user gets immediate
        # feedback. Heavy files can be moved to a Celery task later.
        ShareImportService.parse_and_validate(batch)
        batch.refresh_from_db()
        return Response(
            ShareImportBatchSerializer(batch, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ---- 2. preview -----------------------------------------------------

    @extend_schema(
        request=None,
        responses={
            200: ShareImportBatchSerializer,
            # NOT the canonical error envelope: a failed validation returns
            # the batch itself (status + validation_report) so the UI can
            # render the per-row error table.
            400: OpenApiResponse(
                response=ShareImportBatchSerializer,
                description="Validation failed — batch with validation_report.",
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="preview")
    def preview(self, request: Request, pk: str | None = None) -> Response:
        batch = self.get_object()
        outcome = ShareImportService.parse_and_validate(batch)
        if not outcome.is_ok:
            batch.refresh_from_db()
            return Response(
                ShareImportBatchSerializer(batch, context={"request": request}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )
        ShareImportService.build_preview(batch, outcome.rows)
        batch.refresh_from_db()
        return Response(
            ShareImportBatchSerializer(batch, context={"request": request}).data
        )

    # ---- 3. apply -------------------------------------------------------

    @extend_schema(
        request=None,
        responses={
            200: ShareImportBatchSerializer,
            # Validation-failed shape (``detail`` + ``batch``) — the frontend
            # surfaces ``detail`` and the batch carries the per-row report.
            # The defensive ``CommissioningError`` path below maps to the
            # canonical error envelope instead (rare).
            400: inline_serializer(
                name="ShareImportApplyValidationFailedResponse",
                fields={
                    "detail": drf_serializers.CharField(),
                    "batch": ShareImportBatchSerializer(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="apply")
    def apply(self, request: Request, pk: str | None = None) -> Response:
        batch = self.get_object()
        outcome = ShareImportService.parse_and_validate(batch)
        if not outcome.is_ok:
            batch.refresh_from_db()
            return Response(
                {
                    "detail": "Validation failed; cannot apply.",
                    "batch": ShareImportBatchSerializer(
                        batch, context={"request": request}
                    ).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ShareImportService.apply(batch, outcome.rows, applied_by=request.user)
        except ValueError as exc:
            # Defensive: any remaining low-level numeric/parsing failure from
            # the import pipeline. Domain failures (wrong status etc.) are
            # raised as ``CommissioningError`` by the service directly; this
            # re-raise keeps the stray ``ValueError`` on the same canonical
            # envelope instead of a hand-built body.
            raise CommissioningError(
                str(exc), code="share_import.apply_failed"
            ) from exc
        batch.refresh_from_db()
        return Response(
            ShareImportBatchSerializer(batch, context={"request": request}).data
        )


class ExternalShareDemandViewSet(RolePermissionsMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only access to the applied weekly demand."""

    read_permission = IsOffice
    write_permission = IsOffice
    serializer_class = ExternalShareDemandSerializer
    queryset = ExternalShareDemand.objects.all()

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ExternalShareDemand]:
        qs = super().get_queryset()
        # year/delivery_week are optional filters here (the list is "all demands",
        # narrowable by week) — validated as ints when present.
        params = validate_query_params(self.request, optional=["year", "delivery_week"])
        if (year := params["year"]) is not None:
            qs = qs.filter(year=year)
        if (week := params["delivery_week"]) is not None:
            qs = qs.filter(delivery_week=week)
        return qs
