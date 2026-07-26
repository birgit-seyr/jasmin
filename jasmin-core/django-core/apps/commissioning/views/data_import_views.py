"""HTTP layer for the CSV data-list upload feature.

Pure HTTP plumbing — the import logic lives in
:mod:`apps.commissioning.services.data_import`.

Endpoint: ``POST /api/commissioning/data_import/``

Request (multipart/form-data):
    model_name  registry key naming the target model
                (``share_article``, ``crate``, ``member``,
                ``delivery_station``, ``reseller``)
    file        the filled-in CSV (template format: row 0 titles,
                row 1 field names, row 2 type hints; two-row hand-rolled
                CSVs also work)

Response (200): see :class:`DataImportResult` for the shape.
Response (400): unknown ``model_name``, undecodable file, missing data row.
"""

from __future__ import annotations

import os

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice
from core.serializers import ErrorResponseSerializer

from ..errors import DataImportInvalid, RequiredFieldMissing
from ..serializers.imports_serializer import DataImportResponseSerializer
from ..services.data_import import (
    MODEL_IMPORT_REGISTRY,
    import_rows_from_csv,
)


class DataImportView(APIViewRolePermissionsMixin, APIView):
    """POST a CSV → run it through the registered serializer row by row."""

    read_permission = IsOffice
    write_permission = IsOffice
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="Bulk import data list rows from CSV",
        description=(
            "Upload a filled-in CSV template. The endpoint reads row 1 "
            "(``dataIndex`` field names) as the schema, validates each "
            "data row through the registered serializer, and continues "
            "past any individual row failure."
        ),
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": (
                            "Registry key for the target model. Allowed: "
                            + ", ".join(
                                f"``{k}``" for k in sorted(MODEL_IMPORT_REGISTRY)
                            )
                        ),
                    },
                    "file": {"type": "string", "format": "binary"},
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "Validate every row (including FK resolution) "
                            "without persisting anything — the preview pass for "
                            "many-FK imports like subscriptions."
                        ),
                    },
                },
                "required": ["model_name", "file"],
            }
        },
        responses={
            200: DataImportResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        model_name = (request.data.get("model_name") or "").strip().lower()
        upload = request.FILES.get("file")

        if not model_name:
            raise RequiredFieldMissing("model_name is required", field="model_name")
        if upload is None:
            raise RequiredFieldMissing("file is required", field="file")

        # Reject non-CSV uploads early. The .csv extension isn't a
        # security boundary (an attacker could rename anything), but it
        # cuts off the accidental "I uploaded the wrong file" case and
        # documents the contract.
        if os.path.splitext(upload.name)[1].lower() != ".csv":
            raise DataImportInvalid("file must be a .csv", field="file")

        dry_run = str(request.data.get("dry_run", "")).strip().lower() in {
            "true",
            "1",
            "yes",
            "on",
        }

        # ``import_rows_from_csv`` raises ``DataImportInvalid`` directly for
        # whole-file problems; the global handler renders it. Per-row failures
        # come back on ``result`` and never raise.
        result = import_rows_from_csv(
            model_name, upload.read(), importing_user=request.user, dry_run=dry_run
        )

        return Response(result.to_dict(), status=status.HTTP_200_OK)
