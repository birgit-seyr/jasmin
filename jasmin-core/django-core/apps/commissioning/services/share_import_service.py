"""Weekly external-demand import pipeline.

Pipeline stages:

1. ``ingest_upload``  — persist the file + checksum, create a ``ShareImportBatch``.
2. ``parse_and_validate`` — read CSV/XLSX, resolve external codes via
   :class:`ExternalCodeMapping`, run per-row validation, fill
   ``validation_report``. Status -> ``validated`` or ``failed``.
3. ``build_preview`` — diff incoming rows vs. currently applied
   ``ExternalShareDemand`` for the same ``(year, delivery_week)``.
   Status -> ``preview_ready``.
4. ``apply`` — atomic transaction:
     * mark older applied batches for the same ``(year, week)`` as superseded,
     * upsert the matching ``Share`` rows so the rest of the app finds them,
     * replace ``ExternalShareDemand`` rows for that week,
     * recompute ShareContent theoreticals + movements for every Share
       in the affected week (``recompute_shares``). A re-import that
       changes demand numbers therefore propagates downstream
       automatically — the office never has to remember to click
       "Recompute" after an import.
     * forward-seed the NEXT ISO week with a copy of the applied amounts,
       flagged ``ExternalShareDemand.is_estimate=True``, so a workflow
       running ahead of next week's real upload already has a number to
       plan against. The seed is skipped when next week already holds a
       REAL (non-estimate) upload, and is itself replaced when next week's
       real file is later applied. "Next week" steps the ISO calendar
       forward 7 days, so the year / 53-week rollover is handled.
   Status -> ``applied``.

The pipeline is **idempotent**: same checksum + same week is rejected at
ingest. A re-upload with a new file fully replaces the week's demand
inside one transaction.

CSV/XLSX columns (header row required, case-insensitive)::

    year, delivery_week, delivery_station_code, delivery_day_code,
    variation_code, quantity, [external_ref], [note]
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from ..errors import CommissioningError
from ..models import (
    DeliveryStationDay,
    ExternalCodeMapping,
    ExternalShareDemand,
    Share,
    ShareImportBatch,
)

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "year",
    "delivery_week",
    "delivery_station_code",
    "delivery_day_code",
    "variation_code",
    "quantity",
}


# --- DTOs -------------------------------------------------------------------


@dataclass
class ParsedRow:
    row_number: int  # 1-based, matches spreadsheet line excluding header
    year: int
    delivery_week: int
    variation_id: str
    delivery_station_day_id: str
    quantity: int
    external_ref: str | None = None
    note: str | None = None


@dataclass
class ValidationOutcome:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)  # {row_no: [...]}

    @property
    def is_ok(self) -> bool:
        return not self.errors


@dataclass
class DiffReport:
    added: list[dict[str, Any]] = field(default_factory=list)
    updated: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "totals": {
                "added": len(self.added),
                "updated": len(self.updated),
                "removed": len(self.removed),
            },
        }


# --- service ---------------------------------------------------------------


class ShareImportService:
    """Stateless façade. Each method advances one batch by one stage."""

    # ---- 1. ingest --------------------------------------------------------

    @classmethod
    def ingest_upload(
        cls,
        *,
        file_bytes: bytes,
        original_filename: str,
        year: int,
        delivery_week: int,
        uploaded_by,
    ) -> ShareImportBatch:
        checksum = hashlib.sha256(file_bytes).hexdigest()

        existing = ShareImportBatch.objects.filter(
            year=year, delivery_week=delivery_week, file_checksum=checksum
        ).first()
        if existing is not None:
            return existing  # idempotent: same bytes -> same batch

        batch = ShareImportBatch(
            year=year,
            delivery_week=delivery_week,
            file_checksum=checksum,
            original_filename=original_filename,
            created_by=uploaded_by,
            status=ShareImportBatch.STATUS_UPLOADED,
        )
        batch.file.save(original_filename, ContentFile(file_bytes), save=False)
        batch.save()
        return batch

    # ---- 2. parse + validate ---------------------------------------------

    @classmethod
    def parse_and_validate(cls, batch: ShareImportBatch) -> ValidationOutcome:
        outcome = ValidationOutcome()

        # Malformed file → single top-level error. Catch the realistic
        # file/parse exception families and surface as a single "file"
        # error. Anything outside this set (programmer bug, OOM, etc.)
        # propagates so it's visible.
        try:
            raw_rows = list(cls._read_rows(batch))
        except (
            csv.Error,
            UnicodeDecodeError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            IndexError,
        ) as exc:
            outcome.errors["file"] = [f"Could not parse file: {exc}"]
            cls._persist_validation(batch, outcome, ok=False)
            return outcome

        # Pre-load all mappings into memory once.
        mappings = cls._load_mappings()

        # Pre-load every DeliveryStationDay once, keyed by the
        # (station_id, day_id) pair. Without this the per-row lookup below
        # fired one query per CSV line — 800 queries for an 800-row file,
        # and parse runs at upload, preview AND apply. There are only
        # stations × delivery-days of these rows, so loading them all is
        # cheap and turns the N+1 into a single query.
        station_day_by_pair: dict[tuple[str, str], str] = {
            (station_id, day_id): share_delivery_id
            for share_delivery_id, station_id, day_id in DeliveryStationDay.objects.values_list(
                "id", "delivery_station_id", "delivery_day_id"
            )
        }

        for line_no, raw in enumerate(raw_rows, start=1):
            row_errors: list[str] = []
            data = {k.strip().lower(): (v or "").strip() for k, v in raw.items()}

            missing = REQUIRED_COLUMNS - data.keys()
            if missing:
                row_errors.append(f"Missing columns: {sorted(missing)}")
                outcome.errors[str(line_no)] = row_errors
                continue

            # Numeric fields.
            try:
                year_val = int(data["year"])
                week_val = int(data["delivery_week"])
                qty = int(data["quantity"])
            except ValueError:
                row_errors.append("year/delivery_week/quantity must be integers")
                outcome.errors[str(line_no)] = row_errors
                continue

            if qty < 0:
                row_errors.append("quantity must be >= 0")
            if year_val != batch.year or week_val != batch.delivery_week:
                row_errors.append(
                    f"row year/week ({year_val}/{week_val}) does not match "
                    f"batch ({batch.year}/{batch.delivery_week})"
                )

            variation_id = mappings["variation"].get(data["variation_code"])
            if variation_id is None:
                row_errors.append(f"unknown variation_code: {data['variation_code']!r}")

            station_id = mappings["station"].get(data["delivery_station_code"])
            if station_id is None:
                row_errors.append(
                    f"unknown delivery_station_code: "
                    f"{data['delivery_station_code']!r}"
                )

            day_id = mappings["day"].get(data["delivery_day_code"])
            if day_id is None:
                row_errors.append(
                    f"unknown delivery_day_code: {data['delivery_day_code']!r}"
                )

            station_day_id: str | None = None
            if station_id and day_id:
                station_day_id = station_day_by_pair.get((station_id, day_id))
                if station_day_id is None:
                    row_errors.append(
                        "no DeliveryStationDay links the given station and day"
                    )

            if row_errors:
                outcome.errors[str(line_no)] = row_errors
                continue

            outcome.rows.append(
                ParsedRow(
                    row_number=line_no,
                    year=year_val,
                    delivery_week=week_val,
                    variation_id=variation_id,
                    delivery_station_day_id=station_day_id,
                    quantity=qty,
                    external_ref=data.get("external_ref") or None,
                    note=data.get("note") or None,
                )
            )

        # Catch duplicates *within* the file (same key listed twice).
        seen: dict[tuple[str, str], int] = {}
        for row in outcome.rows:
            key = (row.variation_id, row.delivery_station_day_id)
            if key in seen:
                outcome.errors.setdefault(str(row.row_number), []).append(
                    f"duplicate of row {seen[key]} "
                    "(same variation + station-day in this file)"
                )
            else:
                seen[key] = row.row_number

        cls._persist_validation(batch, outcome, ok=outcome.is_ok)
        return outcome

    # ---- 3. preview / diff ----------------------------------------------

    @classmethod
    def build_preview(
        cls, batch: ShareImportBatch, parsed_rows: Iterable[ParsedRow]
    ) -> DiffReport:
        incoming = {(r.variation_id, r.delivery_station_day_id): r for r in parsed_rows}

        existing = {
            (e.share_type_variation_id, e.delivery_station_day_id): e
            for e in ExternalShareDemand.objects.filter(
                year=batch.year, delivery_week=batch.delivery_week
            )
        }

        diff = DiffReport()
        for key, row in incoming.items():
            if key not in existing:
                diff.added.append(
                    {
                        "variation_id": row.variation_id,
                        "delivery_station_day_id": row.delivery_station_day_id,
                        "quantity": row.quantity,
                    }
                )
            elif existing[key].quantity != row.quantity:
                diff.updated.append(
                    {
                        "variation_id": row.variation_id,
                        "delivery_station_day_id": row.delivery_station_day_id,
                        "old_quantity": existing[key].quantity,
                        "new_quantity": row.quantity,
                    }
                )

        for key, ext in existing.items():
            if key not in incoming:
                diff.removed.append(
                    {
                        "variation_id": ext.share_type_variation_id,
                        "delivery_station_day_id": ext.delivery_station_day_id,
                        "quantity": ext.quantity,
                    }
                )

        batch.diff_report = diff.as_dict()
        batch.status = ShareImportBatch.STATUS_PREVIEW_READY
        batch.save(update_fields=["diff_report", "status"])
        return diff

    # ---- 4. apply --------------------------------------------------------

    @classmethod
    @transaction.atomic
    def apply(
        cls,
        batch: ShareImportBatch,
        parsed_rows: Iterable[ParsedRow],
        *,
        applied_by,
    ) -> ShareImportBatch:
        if batch.status not in {
            ShareImportBatch.STATUS_PREVIEW_READY,
            ShareImportBatch.STATUS_VALIDATED,
        }:
            raise CommissioningError(
                f"Batch {batch.id} is in status {batch.status}, "
                "cannot apply (need preview_ready or validated).",
                code="share_import.invalid_status",
                details={"batch_id": batch.id, "status": batch.status},
            )

        rows = list(parsed_rows)

        # Mark all previously applied batches for the same week as superseded.
        ShareImportBatch.objects.filter(
            year=batch.year,
            delivery_week=batch.delivery_week,
            status=ShareImportBatch.STATUS_APPLIED,
        ).exclude(pk=batch.pk).update(status=ShareImportBatch.STATUS_SUPERSEDED)

        # The selected week is the real, confirmed upload.
        cls._replace_week_demand(
            batch=batch,
            year=batch.year,
            week=batch.delivery_week,
            rows=rows,
            is_estimate=False,
        )

        batch.status = ShareImportBatch.STATUS_APPLIED
        batch.applied_at = timezone.now()
        batch.applied_by = applied_by
        batch.save(update_fields=["status", "applied_at", "applied_by"])

        cls._recompute_week(batch.year, batch.delivery_week, batch=batch)

        # Forward-seed the NEXT week with a copy of these amounts as an
        # estimate, so a workflow that runs ahead of next week's real
        # upload already has a number to plan against. The real upload,
        # when it lands, replaces the estimate (apply() is a full-week
        # delete-then-insert). Done inside the same atomic block.
        cls._seed_next_week_estimate(batch=batch, rows=rows)
        return batch

    # ---- helpers ---------------------------------------------------------

    @classmethod
    def _replace_week_demand(
        cls,
        *,
        batch: ShareImportBatch,
        year: int,
        week: int,
        rows: list[ParsedRow],
        is_estimate: bool,
    ) -> None:
        """Atomically replace the entire demand for one ``(year, week)``.

        Full delete-then-insert (no per-row merge): any station-day /
        variation absent from ``rows`` is dropped. ``rows`` carry their own
        ``year`` / ``delivery_week``; pass ones already stamped to the
        target week. ``batch`` owns the created rows (the FK is non-null).
        """
        # Ensure a Share row exists for every (week, day, variation) pair
        # touched — downstream services (forecast/packing/recompute) need it.
        cls._ensure_shares(year=year, week=week, rows=rows)

        ExternalShareDemand.objects.filter(year=year, delivery_week=week).delete()
        ExternalShareDemand.objects.bulk_create(
            [
                ExternalShareDemand(
                    batch=batch,
                    year=r.year,
                    delivery_week=r.delivery_week,
                    delivery_station_day_id=r.delivery_station_day_id,
                    share_type_variation_id=r.variation_id,
                    quantity=r.quantity,
                    external_ref=r.external_ref,
                    note=r.note,
                    is_estimate=is_estimate,
                )
                for r in rows
            ]
        )

    @staticmethod
    def _recompute_week(year: int, week: int, *, batch: ShareImportBatch) -> None:
        """Propagate the week's new demand into every downstream
        ShareContent / theoretical / movement.

        Without this, a re-import that corrected wrong quantities would
        silently leave the planning view at the OLD numbers — the gap that
        motivated this wiring. ``recompute_shares`` is idempotent and
        short-circuits on an empty id set, so weeks with no live Shares
        cost nothing. Called inside ``apply``'s ``@transaction.atomic`` so a
        recompute failure rolls the whole import back rather than leaving a
        half-applied state where demand changed but planning didn't.
        """
        from .recompute import recompute_shares

        share_ids = list(
            Share.objects.filter(year=year, delivery_week=week).values_list(
                "id", flat=True
            )
        )
        logger.info(
            "share_import.apply.recompute batch=%s year=%s week=%s shares=%s",
            batch.pk,
            year,
            week,
            len(share_ids),
        )
        recompute_shares(share_ids)

    @staticmethod
    def _next_iso_week(year: int, week: int) -> tuple[int, int]:
        """The ISO ``(year, week)`` after ``(year, week)`` — delegates to the
        shared ``iso_week_utils.next_iso_week`` (handles 52/53-week rollover)."""
        from ..utils.iso_week_utils import next_iso_week

        return next_iso_week(year, week)

    @classmethod
    def _seed_next_week_estimate(
        cls, *, batch: ShareImportBatch, rows: list[ParsedRow]
    ) -> None:
        """Seed the next ISO week with an estimate copy of ``rows``.

        Skips entirely when next week already holds a REAL (non-estimate)
        applied upload — a correction or re-apply of this week must never
        clobber confirmed next-week demand. When next week is empty or holds
        only a prior estimate, that estimate is replaced with the fresh copy.
        """
        next_year, next_week = cls._next_iso_week(batch.year, batch.delivery_week)

        real_exists = ExternalShareDemand.objects.filter(
            year=next_year, delivery_week=next_week, is_estimate=False
        ).exists()
        if real_exists:
            logger.info(
                "share_import.seed.skip batch=%s next_year=%s next_week=%s "
                "reason=real_demand_present",
                batch.pk,
                next_year,
                next_week,
            )
            return

        next_rows = [
            replace(row, year=next_year, delivery_week=next_week) for row in rows
        ]
        cls._replace_week_demand(
            batch=batch,
            year=next_year,
            week=next_week,
            rows=next_rows,
            is_estimate=True,
        )
        logger.info(
            "share_import.seed.applied batch=%s next_year=%s next_week=%s rows=%s",
            batch.pk,
            next_year,
            next_week,
            len(next_rows),
        )
        cls._recompute_week(next_year, next_week, batch=batch)

    @staticmethod
    def _read_rows(batch: ShareImportBatch) -> Iterable[dict[str, str]]:
        """Yield dict rows from the uploaded file. CSV only for now;
        extend with openpyxl for .xlsx as needed."""
        with batch.file.open("rb") as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            yield from reader

    @staticmethod
    def _load_mappings() -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {
            "variation": {},
            "station": {},
            "day": {},
        }
        for m in ExternalCodeMapping.objects.all():
            out[m.kind][m.external_code] = m.internal_id
        return out

    @staticmethod
    def _persist_validation(
        batch: ShareImportBatch, outcome: ValidationOutcome, *, ok: bool
    ) -> None:
        batch.row_count = len(outcome.rows) + len(outcome.errors)
        batch.error_count = len(outcome.errors)
        batch.validation_report = outcome.errors
        batch.status = (
            ShareImportBatch.STATUS_VALIDATED if ok else ShareImportBatch.STATUS_FAILED
        )
        batch.save(
            update_fields=[
                "row_count",
                "error_count",
                "validation_report",
                "status",
            ]
        )

    @staticmethod
    def _ensure_shares(*, year: int, week: int, rows: list[ParsedRow]) -> None:
        """``Share`` is the per-week, per-day, per-variation anchor used by
        forecasting/packing/etc. Make sure one exists for each touched
        combination in ``(year, week)``.

        ``Share.delivery_day`` is a ``SharesDeliveryDay`` and we resolve it
        from the ``DeliveryStationDay``'s ``delivery_day``.
        """
        # Map station_day -> shares_delivery_day in one query.
        share_delivery_to_day: dict[str, str] = dict(
            DeliveryStationDay.objects.filter(
                id__in={r.delivery_station_day_id for r in rows}
            ).values_list("id", "delivery_day_id")
        )

        wanted = {
            (share_delivery_to_day[r.delivery_station_day_id], r.variation_id)
            for r in rows
        }

        existing = set(
            Share.objects.filter(
                year=year,
                delivery_week=week,
            ).values_list("delivery_day_id", "share_type_variation_id")
        )

        to_create = [
            Share(
                year=year,
                delivery_week=week,
                delivery_day_id=day_id,
                share_type_variation_id=var_id,
            )
            for (day_id, var_id) in wanted - existing
        ]
        # Use save() (not bulk_create) so the ``delivery_day`` defaults in
        # ``Share.save`` populate harvest/pack/wash/clean days.
        for share in to_create:
            share.save()
