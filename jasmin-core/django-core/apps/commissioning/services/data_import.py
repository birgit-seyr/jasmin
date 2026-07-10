"""CSV → model import logic for the data-list upload feature.

Pure logic — no HTTP. The view in
``apps/commissioning/views/data_import_views.py`` is a thin wrapper that
extracts ``model_name`` + ``file`` from the multipart request, validates the
model name against :data:`MODEL_IMPORT_REGISTRY`, hands the raw bytes here,
and returns the structured result.

Contract
--------
The downloadable CSV template is three rows tall:

    row 0  human-readable column titles (ignored on import)
    row 1  ``dataIndex`` field names — the actual upload schema
    row 2  type hints (ignored on import)

This service expects that layout. Hand-rolled two-row CSVs (header + data)
are still accepted for callers that bypass the download template.

Per-row isolation
-----------------
One bad row never aborts the import: each row goes through its own
``try/except`` and lands in either ``results`` (success) or ``errors``
(validation or unexpected exception). The response always lists every
processed row.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import ValidationError as DRFValidationError

from ..errors import DataImportInvalid, MemberLinkConflict
from ..serializers import (
    CrateSerializer,
    DeliveryStationSerializer,
    MemberSerializer,
    ResellerSerializer,
    ShareArticleSerializer,
)

# ────────────────────────────────────────────────────────────────────────────
# Model registry — keep keys lowercase / snake-case to match what the
# frontend sends in ``model_name``. Add new entries here when a new list
# page gains upload support; the import flow is fully driven by this dict.
# ────────────────────────────────────────────────────────────────────────────
MODEL_IMPORT_REGISTRY: dict[str, type[drf_serializers.ModelSerializer]] = {
    "share_article": ShareArticleSerializer,
    "crate": CrateSerializer,
    "member": MemberSerializer,
    "delivery_station": DeliveryStationSerializer,
    "reseller": ResellerSerializer,
}


# Hard cap on data rows per upload. Each row is one serializer.save()
# (deliberately per-row, no bulk insert), so an accidental giant file
# would grind through inserts until the gunicorn request timeout kills
# it mid-import — per-row isolation means the rows before the cut-off
# would already be committed. Real imports are a few hundred rows.
_MAX_IMPORT_ROWS = 5000

# Cells that look empty after Excel/spreadsheet round-tripping. Treat all of
# these the same way (= field not provided) so the serializer's defaults /
# ``blank=True`` / ``required=False`` kick in instead of failing validation.
_EMPTY_CELL_VALUES = {"", "none", "null", "nan"}

_TRUTHY_BOOL_VALUES = {"true", "1", "yes", "y", "ja", "wahr"}
_FALSY_BOOL_VALUES = {"false", "0", "no", "n", "nein", "falsch"}


@dataclass
class DataImportResult:
    """Outcome of one import call. Mirrors the JSON shape the view returns."""

    model_name: str
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def successful(self) -> int:
        return len(self.results)

    @property
    def failed(self) -> int:
        return len(self.errors)

    @property
    def total_rows(self) -> int:
        return self.successful + self.failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "total_rows": self.total_rows,
            "successful": self.successful,
            "failed": self.failed,
            "results": self.results,
            "errors": self.errors,
        }


def _normalize_cell(value: str | None) -> str | None:
    """Return ``None`` for empty-ish cells, otherwise the stripped value."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.lower() in _EMPTY_CELL_VALUES:
        return None
    return stripped


def _parse_bool_cell(value: str) -> bool | str:
    """Best-effort CSV-friendly bool parse. Returns the original value if
    nothing canonical applies — DRF's ``BooleanField`` then rejects it on
    the failing row instead of crashing the whole import."""
    lowered = value.strip().lower()
    if lowered in _TRUTHY_BOOL_VALUES:
        return True
    if lowered in _FALSY_BOOL_VALUES:
        return False
    return value


def _row_to_payload(
    headers: list[str],
    cells: list[str],
    bool_fields: set[str],
) -> dict[str, Any]:
    """Build a serializer-ready payload from one CSV row.

    - Empty cells become ``None`` (so default / blank=True fields work).
    - Cells in boolean fields are coerced to ``bool`` when canonical.
    """
    payload: dict[str, Any] = {}
    for header, raw in zip(headers, cells, strict=False):
        if not header:
            continue
        cell = _normalize_cell(raw)
        if cell is None:
            continue
        payload[header] = _parse_bool_cell(cell) if header in bool_fields else cell
    return payload


def _collect_bool_fields(
    serializer_cls: type[drf_serializers.ModelSerializer],
) -> set[str]:
    """Field names typed as ``BooleanField`` on the serializer."""
    instance = serializer_cls()
    return {
        name
        for name, field_obj in instance.fields.items()
        if isinstance(field_obj, drf_serializers.BooleanField)
    }


def _flatten_drf_errors(errors: Any) -> str:
    """Turn a DRF error dict / list into a short single-line message.

    DRF's ``serializer.errors`` can be a dict of lists, a list of strings,
    or a nested mix. We just want something short and human-readable for
    the response payload — the frontend renders it in a table cell.
    """
    if isinstance(errors, dict):
        return "; ".join(
            f"{field_name}: {_flatten_drf_errors(msgs)}"
            for field_name, msgs in errors.items()
        )
    if isinstance(errors, list):
        return ", ".join(_flatten_drf_errors(item) for item in errors)
    return str(errors)


def _decode_csv(file_bytes: bytes) -> str:
    """Decode an uploaded CSV as utf-8 with a BOM-tolerant Latin-1 fallback
    (some Excel exports default to Latin-1)."""
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Latin-1 maps every byte 0..255 → ``.decode("latin-1")`` cannot
        # raise UnicodeDecodeError. The previous broad ``except`` was
        # dead code.
        return file_bytes.decode("latin-1")


def _split_template_rows(
    all_rows: list[list[str]],
) -> tuple[list[str], list[list[str]], int]:
    """Pick the header row + data rows out of the parsed CSV.

    Three-row download template (titles / dataIndex / type hints): row 1 is
    the schema, data rows start at row 3 (0-indexed) / row 4 (1-indexed for
    human-friendly error messages).

    Two-row hand-rolled CSV (header + data): row 0 is the schema.
    """
    if len(all_rows) >= 3:
        headers = [h.strip() for h in all_rows[1]]
        data_rows = all_rows[3:]
        first_data_row_number = 4
    else:
        headers = [h.strip() for h in all_rows[0]]
        data_rows = all_rows[1:]
        first_data_row_number = 2
    return headers, data_rows, first_data_row_number


def get_serializer_for_model(model_name: str) -> type[drf_serializers.ModelSerializer]:
    """Look up the registered serializer or raise
    :class:`~apps.commissioning.errors.DataImportInvalid`."""
    serializer_cls = MODEL_IMPORT_REGISTRY.get(model_name)
    if serializer_cls is None:
        raise DataImportInvalid(
            f"Unknown model_name '{model_name}'. "
            f"Allowed: {sorted(MODEL_IMPORT_REGISTRY)}"
        )
    return serializer_cls


def _save_imported_member(ser, payload, importing_user):
    """Save an imported Member row and preserve the Member↔JasminUser link.

    Mirrors ``MemberViewSet.create``: an email that already belongs to a user is
    linked (auto-confirms an active user), or rejected with ``MemberLinkConflict``
    BEFORE the row is saved (so a conflict never leaves an orphaned member). No
    welcome email is sent on import (``notify_user=False``).
    """
    from .member_service import MemberService

    service = MemberService()
    email = (payload.get("email") or "").strip().lower()
    existing_user = service.find_existing_user_for_email(email) if email else None
    if existing_user is not None:
        # Raises MemberLinkConflict (caught per-row) when blocked — before save.
        service.assert_user_can_be_linked(existing_user)

    member = ser.save()

    if existing_user is not None:
        service.link_to_user(
            member,
            existing_user,
            admin_user=importing_user,
            notify_user=False,
            request=None,
        )
    return member


def import_rows_from_csv(
    model_name: str, file_bytes: bytes, importing_user=None
) -> DataImportResult:
    """Run an import end-to-end. Pure logic — no HTTP.

    Raises :class:`~apps.commissioning.errors.DataImportInvalid` for
    whole-file problems (unknown model, undecodable bytes, no data rows).
    Per-row failures are collected on the returned
    :class:`DataImportResult` and never raise.

    ``importing_user`` is the office user running the import (threaded down so
    member rows can be linked to an existing JasminUser, recording the actor).
    """
    serializer_cls = get_serializer_for_model(model_name)
    raw = _decode_csv(file_bytes)

    reader = csv.reader(io.StringIO(raw))
    all_rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(all_rows) < 2:
        raise DataImportInvalid(
            "CSV must contain at least a header row and one data row."
        )

    headers, data_rows, first_data_row_number = _split_template_rows(all_rows)
    if len(data_rows) > _MAX_IMPORT_ROWS:
        raise DataImportInvalid(
            f"CSV has {len(data_rows)} data rows; imports are capped at "
            f"{_MAX_IMPORT_ROWS} rows per upload. Split the file."
        )
    reserved_member_quota_ids: list[str] = []
    if model_name == "member":
        # The interactive create path (MemberViewSet.create) is volume-capped, so
        # the bulk import must draw on the SAME weekly member budget or it is a
        # total bypass. Reserve the whole batch up front — the per-minute burst
        # cap does not apply to a legitimate bulk import — so an over-cap import
        # is refused cleanly (429) instead of partially applying. Unused
        # reservations (blank/invalid rows that create no member) are refunded
        # after the loop so a mostly-failing import doesn't burn the week's budget.
        from apps.shared.tenants.models import RateLimitedAction
        from apps.shared.tenants.rate_limits import enforce_action_quota_batch

        reserved_member_quota_ids = enforce_action_quota_batch(
            RateLimitedAction.MEMBER_CREATION,
            count=len(data_rows),
            actor=importing_user,
        )
    bool_fields = _collect_bool_fields(serializer_cls)
    result = DataImportResult(model_name=model_name)

    for offset, cells in enumerate(data_rows):
        row_number = first_data_row_number + offset
        payload = _row_to_payload(headers, cells, bool_fields)
        if not payload:
            # Blank line in the middle of the file — silently skip.
            continue
        ser = serializer_cls(data=payload)
        try:
            if ser.is_valid():
                if model_name == "member":
                    # Preserve the Member↔JasminUser linking invariant the
                    # interactive create flow enforces: link to an existing
                    # user (or report a 409-style conflict per row) instead of
                    # silently orphaning a duplicate-email member.
                    instance = _save_imported_member(ser, payload, importing_user)
                else:
                    instance = ser.save()
                result.results.append(
                    {"row": row_number, "id": getattr(instance, "id", None)}
                )
            else:
                result.errors.append(
                    {
                        "row": row_number,
                        "error": _flatten_drf_errors(ser.errors),
                        "data": payload,
                    }
                )
        except (
            DjangoValidationError,
            DRFValidationError,
            DatabaseError,
            MemberLinkConflict,
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
        ) as exc:
            # Per-row collection: one bad row must not stop the import.
            # Catch the realistic data/parse/DB exception families
            # (DatabaseError covers Integrity/Data/InternalError etc.).
            # Anything outside this set (KeyboardInterrupt, SystemExit,
            # an actual code bug) propagates so the bug is visible.
            result.errors.append(
                {
                    "row": row_number,
                    "error": f"{type(exc).__name__}: {exc}",
                    "data": payload,
                }
            )

    if reserved_member_quota_ids:
        # Refund the reservations that never became a member (blank + failed
        # rows): one ledger row was reserved per data row, one result entry
        # exists per successful create, so the tail beyond the success count is
        # unused. Refunding keeps the weekly budget honest for later imports.
        from apps.shared.tenants.rate_limits import release_action_quota

        release_action_quota(reserved_member_quota_ids[len(result.results) :])

    return result
