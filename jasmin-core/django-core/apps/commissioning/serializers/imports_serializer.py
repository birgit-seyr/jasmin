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
