from __future__ import annotations

from django.core.validators import FileExtensionValidator
from rest_framework import serializers

from ..errors import ExternalCodeMappingTargetMissing
from ..models import (
    ExternalCodeMapping,
    ExternalShareDemand,
    ShareImportBatch,
)


class ExternalCodeMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalCodeMapping
        fields = ["id", "kind", "external_code", "internal_id", "note"]

    def validate(self, attrs):
        """Refuse an ``internal_id`` with no object of the mapping's kind: a
        mistyped id would otherwise only surface weeks later, as a feed row
        that fails for a reason that names something else."""
        attrs = super().validate(attrs)
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        internal_id = attrs.get(
            "internal_id", getattr(self.instance, "internal_id", None)
        )
        if kind not in dict(ExternalCodeMapping.KIND_CHOICES):
            return attrs
        target = ExternalCodeMapping.target_model(kind)
        if not target.objects.filter(pk=internal_id).exists():
            raise ExternalCodeMappingTargetMissing(
                f"No {target.__name__} has the id {internal_id!r}.",
                field="internal_id",
                details={"kind": kind, "internal_id": internal_id},
            )
        return attrs


class ShareImportBatchSerializer(serializers.ModelSerializer):
    # The uploaded CSV itself is deliberately NOT exposed. Reading ``.url`` on
    # the FileField mints a signed capability token for it (the default storage
    # signs every media URL), and that file holds a tenant's per-station demand
    # for the week — so a bare attribute access would hand out a bearer link to
    # member data on every list call. Nothing consumes it: the page renders
    # ``original_filename``.
    class Meta:
        model = ShareImportBatch
        fields = [
            "id",
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
    """One row that failed, with its reason and the parsed row echoed back.

    ``error`` is the reason in the server's words. ``code`` is the stable error
    code the frontend translates, with ``details`` as the translation's values:
    a ``JasminError``'s own code, or ``data_import.row_invalid`` (values that
    failed validation), ``data_import.row_unreadable`` (a line the CSV parser
    refused) or ``data_import.row_failed`` (any other failure). ``field`` names
    the column at fault when there is exactly one.
    """

    row = serializers.IntegerField()
    error = serializers.CharField()
    data = serializers.DictField()
    code = serializers.CharField()
    field = serializers.CharField(required=False)
    details = serializers.DictField(required=False)


class DataImportResponseSerializer(serializers.Serializer):
    """Outcome of one data-list CSV import call."""

    model_name = serializers.CharField()
    total_rows = serializers.IntegerField()
    successful = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = DataImportResultItemSerializer(many=True)
    errors = DataImportErrorItemSerializer(many=True)
