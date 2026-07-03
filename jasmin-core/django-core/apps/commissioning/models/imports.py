"""Models for the weekly external share-demand import pipeline.

A tenant whose ``Tenant.features['commissioning']['demand_source']`` is
``"external_csv"`` does not use ``Subscription`` / ``ShareDelivery`` as the
source of truth for "how many share_type_variations do we need". Instead,
an office user
uploads a CSV/XLSX once a week, the file is parsed, validated, previewed
and finally applied. The applied demand lives in :class:`ExternalShareDemand`
and is consumed by :class:`apps.commissioning.services.ShareDemandService`.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .base import JasminModel
from .mixin import CreatedMixin


class ExternalCodeMapping(JasminModel):
    """Maps stable codes from the upstream system to internal nanoids.

    The CSV must reference variations / stations / days by *external codes*
    (whatever the upstream system uses). This decouples the file format
    from our internal IDs and lets office staff re-map without re-issuing
    files.
    """

    KIND_VARIATION = "variation"
    KIND_STATION = "station"
    KIND_DAY = "day"
    KIND_CHOICES = [
        (KIND_VARIATION, "ShareTypeVariation"),
        (KIND_STATION, "DeliveryStation"),
        (KIND_DAY, "SharesDeliveryDay"),
    ]

    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    external_code = models.CharField(max_length=128)
    internal_id = models.CharField(max_length=12)
    note = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "external_code"],
                name="extcodemap_unique_kind_code",
            ),
        ]
        indexes = [models.Index(fields=["kind", "internal_id"])]

    def __str__(self) -> str:
        return f"{self.kind}: {self.external_code} -> {self.internal_id}"


class ShareImportBatch(JasminModel, CreatedMixin):
    """One uploaded file = one batch. Lifecycle is status-driven."""

    STATUS_UPLOADED = "uploaded"
    STATUS_VALIDATED = "validated"
    STATUS_PREVIEW_READY = "preview_ready"
    STATUS_APPLIED = "applied"
    STATUS_FAILED = "failed"
    STATUS_SUPERSEDED = "superseded"
    STATUS_CHOICES = [
        (STATUS_UPLOADED, "Uploaded"),
        (STATUS_VALIDATED, "Validated"),
        (STATUS_PREVIEW_READY, "Preview ready"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SUPERSEDED, "Superseded"),
    ]

    file = models.FileField(upload_to="share_imports/%Y/%m/")
    file_checksum = models.CharField(max_length=64, db_index=True)  # sha256 hex
    original_filename = models.CharField(max_length=255, blank=True, null=True)

    year = models.PositiveSmallIntegerField()
    delivery_week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_UPLOADED, db_index=True
    )
    row_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)

    # Per-row errors: ``{ "<row_number>": ["msg", ...], ... }``
    validation_report = models.JSONField(default=dict, blank=True)
    # ``{"added": [...], "updated": [...], "removed": [...]}``
    diff_report = models.JSONField(default=dict, blank=True)

    applied_at = models.DateTimeField(blank=True, null=True)
    applied_by = models.ForeignKey(
        "accounts.JasminUser",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="+",
    )

    class Meta:
        constraints = [
            # Re-uploading the exact same bytes for the same week is a no-op.
            models.UniqueConstraint(
                fields=["year", "delivery_week", "file_checksum"],
                name="shareimport_idempotent",
            ),
        ]
        indexes = [
            models.Index(fields=["year", "delivery_week", "status"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ImportBatch W{self.delivery_week}/{self.year} ({self.status})"


class ExternalShareDemand(JasminModel):
    """The applied truth: how many share_type_variations of variation V are
    needed at station-day SD in week W of year Y, according to the upstream
    system.

    Aggregated rows (one per ``(year, week, station_day, variation)``) keep
    the table small and match what every consumer actually asks for.
    """

    batch = models.ForeignKey(
        "ShareImportBatch", on_delete=models.PROTECT, related_name="demand_rows"
    )
    year = models.PositiveSmallIntegerField(db_index=True)
    delivery_week = models.PositiveSmallIntegerField(
        db_index=True,
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    delivery_station_day = models.ForeignKey(
        "DeliveryStationDay", on_delete=models.PROTECT
    )
    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField()
    external_ref = models.CharField(max_length=128, blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    # True when this row was auto-seeded as a forward estimate (a copy of
    # the prior week's applied amounts) rather than uploaded for this week
    # directly. Lets the next real upload — and any consumer that cares —
    # tell an estimate apart from confirmed demand. Estimates are still
    # included in demand aggregation so planning has a number to work with.
    is_estimate = models.BooleanField(
        default=False, db_index=True
    )  # this flag is not yet used anywhere

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "delivery_station_day",
                    "share_type_variation",
                ],
                name="extdemand_unique_yws_var",
            ),
        ]
        indexes = [
            models.Index(
                fields=["year", "delivery_week", "share_type_variation"],
                name="extdemand_yw_var_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"ExtDemand W{self.delivery_week}/{self.year} "
            f"{self.share_type_variation_id}@{self.delivery_station_day_id} "
            f"x{self.quantity}"
        )
