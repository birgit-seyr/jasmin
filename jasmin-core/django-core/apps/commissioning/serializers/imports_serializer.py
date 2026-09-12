from __future__ import annotations

from django.core.validators import FileExtensionValidator
from rest_framework import serializers

from ..models import (
    ExternalCodeMapping,
    ExternalShareDemand,
    ShareImportBatch,
)


class ExternalCodeMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalCodeMapping
        fields = ["id", "kind", "external_code", "internal_id", "note"]


class ShareImportBatchSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ShareImportBatch
        fields = [
            "id",
            "file",
            "file_url",
            "original_filename",
            "file_checksum",
            "year",
            "delivery_week",
            "status",
            "row_count",
            "error_count",
            "validation_report",
            "diff_report",
            "created_at",
            "created_by",
            "applied_at",
            "applied_by",
        ]
        read_only_fields = [
            "id",
            "file",
            "file_url",
            "original_filename",
            "file_checksum",
            "status",
            "row_count",
            "error_count",
            "validation_report",
            "diff_report",
            "created_at",
            "created_by",
            "applied_at",
            "applied_by",
        ]

    def get_file_url(self, obj: ShareImportBatch) -> str | None:
        try:
            return obj.file.url if obj.file else None
        except ValueError:
            return None


class ShareImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        validators=[FileExtensionValidator(allowed_extensions=["csv"])],
    )
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    delivery_week = serializers.IntegerField(min_value=1, max_value=53)


class ExternalShareDemandSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalShareDemand
        fields = [
            "id",
            "batch",
            "year",
            "delivery_week",
            "delivery_station_day",
            "share_type_variation",
            "quantity",
            "external_ref",
            "note",
            "is_estimate",
        ]
        read_only_fields = fields


# ── Data-list CSV import (POST /commissioning/data_import/) ──────────────────
# Response shape for the generic data-list upload. Mirrors
# ``services.data_import.DataImportResult.to_dict()`` — the single source of
# truth for the JSON — so keep the two in sync. The class names deliberately
# yield the ``DataImport*`` OpenAPI component names the frontend already
# consumes (drf-spectacular strips the ``Serializer`` suffix).


class DataImportResultItemSerializer(serializers.Serializer):
    """One successfully-imported (or dry-run-previewed) row.

    ``id`` is the created instance's primary key, or ``null`` for a dry-run
    preview (nothing is persisted).
    """

    row = serializers.IntegerField()
    id = serializers.CharField(allow_null=True)


class DataImportErrorItemSerializer(serializers.Serializer):
    """One row that failed, with its reason and the parsed row echoed back."""

    row = serializers.IntegerField()
    error = serializers.CharField()
    data = serializers.DictField()


class DataImportResponseSerializer(serializers.Serializer):
    """Outcome of one data-list CSV import call."""

    model_name = serializers.CharField()
    total_rows = serializers.IntegerField()
    successful = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = DataImportResultItemSerializer(many=True)
    errors = DataImportErrorItemSerializer(many=True)
