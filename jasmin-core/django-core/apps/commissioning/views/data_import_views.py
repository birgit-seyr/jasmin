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

from apps.accounts.permissions import RequiresStepUp
from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice
from apps.shared.query_params import parse_body_bool
from apps.shared.request_utils import body
from core.serializers import ErrorResponseSerializer

from ..errors import DataImportInvalid, RequiredFieldMissing
from ..serializers.imports_serializer import DataImportResponseSerializer
from ..services.data_import import (
    MODEL_IMPORT_REGISTRY,
    bank_data_columns_in_csv,
    get_serializer_for_model,
    import_rows_from_csv,
)
from ..services.onboarding_policy import onboarding_mode_enabled

# Cap the upload before a byte of it is read. The import's row cap bounds
# PARSING, not memory: by the time it applies, the whole file plus its decoded
# copy are resident. A 5000-row data list is well under a megabyte, so this
# only ever catches a runaway export (nginx's 50 MB body limit is far too
# coarse for a worker handling several uploads at once).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_UPLOAD_TOO_LARGE = (
    f"file exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit — "
    "split the list into smaller files."
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
        model_name = (body(request).get("model_name") or "").strip().lower()
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

        # Accepts a boolean or true/false, 1/0, yes/no, on/off (the form part
        # arrives as a string); absent means a real run.
        dry_run = parse_body_bool(body(request), "dry_run")

        # ``size`` is what the multipart parser recorded; the bounded read is
        # what actually holds, for an upload whose size is unknown or wrong.
        if (upload.size or 0) > _MAX_UPLOAD_BYTES:
            raise DataImportInvalid(_UPLOAD_TOO_LARGE, field="file")
        file_bytes = upload.read(_MAX_UPLOAD_BYTES + 1)
        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            raise DataImportInvalid(_UPLOAD_TOO_LARGE, field="file")

        if not dry_run:
            self._require_step_up_for_bank_columns(request, model_name, file_bytes)

        # ``import_rows_from_csv`` raises ``DataImportInvalid`` directly for
        # whole-file problems; the global handler renders it. Per-row failures
        # come back on ``result`` and never raise.
        result = import_rows_from_csv(
            model_name,
            file_bytes,
            importing_user=request.user,
            dry_run=dry_run,
            # In onboarding mode a linked member stays unconfirmed so the office
            # can confirm it with its historical date and without an email.
            confirm_active_users=not onboarding_mode_enabled(),
        )

        return Response(result.to_dict(), status=status.HTTP_200_OK)

    def _require_step_up_for_bank_columns(
        self, request: Request, model_name: str, file_bytes: bytes
    ) -> None:
        """Refuse a real import that writes bank data without fresh step-up auth.

        IBANs, account holders and SEPA mandates need a fresh step-up claim on
        every interactive write, so a bulk upload must not be the way around
        that. Only a real import is gated: a dry run persists nothing, so the
        office can still preview a bank-data file without re-authenticating.
        """
        # An unknown model gets its 400 before any step-up prompt.
        get_serializer_for_model(model_name)
        if not bank_data_columns_in_csv(file_bytes):
            return
        # Raises ``StepUpRequired`` (403 ``auth.step_up_required``, the code the
        # frontend interceptor answers with the step-up modal and a retry) when
        # the access token carries no fresh step-up claim.
        RequiresStepUp().has_permission(request, self)
