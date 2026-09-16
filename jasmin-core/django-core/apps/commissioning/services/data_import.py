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
(validation, an unexpected exception, or a line the CSV parser itself
could not read). The response always lists every processed row.
"""

from __future__ import annotations

import contextlib
import csv
import io
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, transaction
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import ValidationError as DRFValidationError

from core.errors import JasminError

from ..errors import DataImportInvalid, MemberLinkConflict
from ..serializers import (
    CoopShareImportSerializer,
    CrateSerializer,
    DeliveryStationSerializer,
    MemberImportSerializer,
    ResellerSerializer,
    ShareArticleSerializer,
    SubscriptionImportSerializer,
)

# ────────────────────────────────────────────────────────────────────────────
# Model registry — keep keys lowercase / snake-case to match what the
# frontend sends in ``model_name``. Add commissioning models here directly; a
# model owned by ANOTHER app registers itself via ``register_import_serializer``
# (see below). The import flow is fully driven by this dict.
# ────────────────────────────────────────────────────────────────────────────
MODEL_IMPORT_REGISTRY: dict[str, type[drf_serializers.BaseSerializer]] = {
    "share_article": ShareArticleSerializer,
    "crate": CrateSerializer,
    # Onboarding import: same serializer as the office grid, except
    # ``member_number`` is writable so a tenant can carry its existing
    # Mitgliedsnummern over (the other onboarding imports resolve their
    # member by that natural key).
    "member": MemberImportSerializer,
    "delivery_station": DeliveryStationSerializer,
    "reseller": ResellerSerializer,
    # Subscriptions resolve their FKs by natural key (see
    # ``SubscriptionImportSerializer``) and land as unconfirmed drafts.
    "subscription": SubscriptionImportSerializer,
    # Cooperative shares (member equity) — created unconfirmed, GenG min/max
    # enforced per row via CoopShare.save() → full_clean().
    "coop_share": CoopShareImportSerializer,
}


def register_import_serializer(
    model_name: str, serializer_cls: type[drf_serializers.BaseSerializer]
) -> None:
    """Register a CSV-import serializer for ``model_name`` from ANOTHER app.

    Lets an app OUTSIDE commissioning contribute an importable model without
    commissioning importing it — preserving the one-way isolation. The other
    app calls this from its ``AppConfig.ready()`` (payments→commissioning is the
    allowed direction). Payments uses it for ``sepa_mandate`` (a
    ``BillingProfile`` create). commissioning's own models are seeded in
    ``MODEL_IMPORT_REGISTRY`` above.
    """
    MODEL_IMPORT_REGISTRY[model_name] = serializer_cls


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

# Upload columns that write bank-account / SEPA-mandate data: ``Member.iban`` /
# ``account_owner`` (``member``), the mandate fields of ``sepa_mandate``, and
# ``ContactEntity.iban``, which the ``reseller`` / ``delivery_station`` imports
# accept through their dynamic contact fields. Every interactive write of these
# requires fresh step-up auth, so a real import carrying any of them requires
# it too — ``DataImportView`` enforces that via ``bank_data_columns_in_csv``.
BANK_DATA_IMPORT_COLUMNS = frozenset(
    {
        "iban",
        "account_owner",
        "account_holder",
        "sepa_mandate_reference",
        "sepa_mandate_signed_at",
        "sepa_mandate_paper_received_at",
    }
)


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
    serializer_cls: type[drf_serializers.BaseSerializer],
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
        # raise UnicodeDecodeError, so it needs no ``except``.
        return file_bytes.decode("latin-1")


@dataclass
class _CsvLine:
    """One non-blank line of the upload: its cells, or why they are unreadable.

    ``csv`` refuses a line whose quoting is broken — a stray quote swallowing
    the rest of the file into one oversized field, say — but goes on reading at
    the next one, so an unreadable line stays a single reported row instead of
    killing the whole upload.
    """

    cells: list[str] = field(default_factory=list)
    parse_error: str | None = None


def _split_template_rows(
    all_lines: list[_CsvLine],
) -> tuple[list[str], list[_CsvLine], int]:
    """Pick the header row + data rows out of the parsed CSV.

    Three-row download template (titles / dataIndex / type hints): row 1 is
    the schema, data rows start at row 3 (0-indexed) / row 4 (1-indexed for
    human-friendly error messages).

    Two-row hand-rolled CSV (header + data): row 0 is the schema.

    Raises :class:`~apps.commissioning.errors.DataImportInvalid` when the schema
    row itself is unreadable — with no field names there is nothing to validate
    the data rows against, so that one is a whole-file failure.
    """
    if len(all_lines) >= 3:
        header_line = all_lines[1]
        data_lines = all_lines[3:]
        first_data_row_number = 4
    else:
        header_line = all_lines[0]
        data_lines = all_lines[1:]
        first_data_row_number = 2
    if header_line.parse_error:
        raise DataImportInvalid(
            f"The CSV header row could not be read: {header_line.parse_error}",
            field="file",
        )
    headers = [h.strip() for h in header_line.cells]
    return headers, data_lines, first_data_row_number


def _read_csv_rows(file_bytes: bytes, *, max_lines: int) -> list[_CsvLine]:
    """Decode the upload and return its lines, dropping blank ones.

    Reading stops at ``max_lines``, so a runaway file costs one pass over its
    first ``max_lines`` lines instead of a full parse. Memory is bounded by the
    byte cap the view applies before calling in — the decode here materialises
    whatever bytes it is handed.
    """
    reader = csv.reader(io.StringIO(_decode_csv(file_bytes)))
    lines: list[_CsvLine] = []
    while len(lines) < max_lines:
        try:
            cells = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            lines.append(_CsvLine(parse_error=str(exc)))
            continue
        if any(cell.strip() for cell in cells):
            lines.append(_CsvLine(cells=cells))
    return lines


def bank_data_columns_in_csv(file_bytes: bytes) -> set[str]:
    """Return the :data:`BANK_DATA_IMPORT_COLUMNS` named by the upload's schema row.

    Reads the header exactly as :func:`import_rows_from_csv` does (same
    decoding, same template-vs-hand-rolled row pick), so the result matches
    the field names the import hands to the serializer. A file too short to
    import reports nothing; the import itself rejects it. An unreadable schema
    row raises ``DataImportInvalid``, as the import would a moment later.
    """
    # The schema row is the second line at the latest, so three lines settle
    # both the template-vs-hand-rolled pick and the header itself.
    all_lines = _read_csv_rows(file_bytes, max_lines=3)
    if len(all_lines) < 2:
        return set()
    headers, _data_lines, _first_data_row_number = _split_template_rows(all_lines)
    return set(BANK_DATA_IMPORT_COLUMNS.intersection(headers))


def get_serializer_for_model(model_name: str) -> type[drf_serializers.BaseSerializer]:
    """Look up the registered serializer or raise
    :class:`~apps.commissioning.errors.DataImportInvalid`."""
    serializer_cls = MODEL_IMPORT_REGISTRY.get(model_name)
    if serializer_cls is None:
        raise DataImportInvalid(
            f"Unknown model_name '{model_name}'. "
            f"Allowed: {sorted(MODEL_IMPORT_REGISTRY)}"
        )
    return serializer_cls


def _save_imported_member(
    serializer, payload, importing_user, *, confirm_active_users: bool
):
    """Save an imported Member row and preserve the Member↔JasminUser link.

    Mirrors ``MemberViewSet.create``: an email that already belongs to a user is
    linked (auto-confirms an active user unless ``confirm_active_users`` is
    False), or rejected with ``MemberLinkConflict`` BEFORE the row is saved (so a
    conflict never leaves an orphaned member). No welcome email is sent on
    import (``notify_user=False``).

    Exception: an address whose login already belongs to a DIFFERENT member
    imports as an UNLINKED member rather than failing. Shared inboxes are
    legitimate (``Member.email`` is not unique) but a login is not shareable, so
    the second member is simply office-managed.
    """
    from ..errors import UserAlreadyLinked
    from .member_service import MemberService

    service = MemberService()
    email = (payload.get("email") or "").strip().lower()
    existing_user = service.find_existing_user_for_email(email) if email else None
    if existing_user is not None:
        try:
            # Raises MemberLinkConflict (caught per-row) when blocked — before
            # save, so a conflict never leaves an orphaned member.
            service.assert_user_can_be_linked(existing_user)
        except UserAlreadyLinked:
            # The address already belongs to ANOTHER member's login. That is a
            # legitimate shape because ``Member.email`` is not unique — two
            # members share one inbox, and only one of them can hold the login.
            # Import this member anyway, unlinked: failing the row would drop a
            # real Mitglied from the Mitgliederliste over an account they were
            # never going to have. ``UserInBlockedStatus`` still fails the row —
            # that one means the address is mid-flow in another application.
            existing_user = None

    member = serializer.save()

    if existing_user is not None:
        service.link_to_user(
            member,
            existing_user,
            admin_user=importing_user,
            notify_user=False,
            request=None,
            confirm_active_user=confirm_active_users,
        )
    return member


def _persist_import_row(
    serializer, model_name, payload, importing_user, *, confirm_active_users: bool
):
    """Persist one validated row via the model-appropriate path.

    ``member`` rows go through ``_save_imported_member`` (which preserves the
    Member↔JasminUser link + conflict guard). ``reseller`` / ``delivery_station``
    rows go through ``ResellerAndDeliveryStationService``, the path their office
    create endpoints use: both serializers flatten the linked ``ContactEntity``'s
    columns (address, zip_code, city, …) onto themselves, and only the service
    splits that block back off — a plain ``serializer.save()`` hands those names
    to ``Model.objects.create()`` and fails every row. Every other model is a
    plain ``serializer.save()``. Shared by the real import AND the dry-run
    preview (the latter calls this inside a rolled-back savepoint), so both
    exercise identical model-level validation.
    """
    if model_name == "member":
        return _save_imported_member(
            serializer,
            payload,
            importing_user,
            confirm_active_users=confirm_active_users,
        )
    if model_name in {"reseller", "delivery_station"}:
        from .reseller_and_delivery_station_service import (
            ResellerAndDeliveryStationService,
        )

        service = ResellerAndDeliveryStationService()
        # The service consumes what it is handed (it pops the contact columns
        # and the transient ``is_also_delivery_station`` flag out), so give it a
        # copy and leave the serializer's own validated_data intact.
        validated_data = dict(serializer.validated_data)
        if model_name == "reseller":
            return service.create_reseller(validated_data)
        return service.create_delivery_station(validated_data)
    return serializer.save()


@contextlib.contextmanager
def _dry_run_scope(dry_run: bool):
    """Wrap a whole dry-run pass in ONE transaction that is always rolled back.

    Successful rows stay visible to the rows that follow (so an intra-file
    uniqueness collision surfaces in the preview), and nothing survives the
    pass. A real import yields a no-op scope — its rows must actually commit,
    each in its own per-row transaction.
    """
    if not dry_run:
        yield
        return
    with transaction.atomic():
        try:
            yield
        finally:
            # ``finally`` so the rollback still happens if the caller raises
            # (e.g. a whole-file error part-way through the loop).
            transaction.set_rollback(True)


def import_rows_from_csv(
    model_name: str,
    file_bytes: bytes,
    importing_user=None,
    *,
    dry_run: bool = False,
    confirm_active_users: bool = True,
) -> DataImportResult:
    """Run an import end-to-end. Pure logic — no HTTP.

    Raises :class:`~apps.commissioning.errors.DataImportInvalid` for
    whole-file problems (unknown model, undecodable bytes, no data rows).
    Per-row failures are collected on the returned
    :class:`DataImportResult` and never raise.

    ``importing_user`` is the office user running the import (threaded down so
    member rows can be linked to an existing JasminUser, recording the actor).

    ``confirm_active_users`` decides whether a member row linked to an existing
    active user is confirmed on import. The import view turns it off in
    onboarding mode, where the office confirms members with their historical
    dates afterwards.

    ``dry_run`` validates every row — including FK resolution (e.g. a
    Subscription's member / variation / station-day natural keys) — WITHOUT
    persisting anything. It is the preview pass for many-FK imports: the office
    fixes every unresolved reference in one go before committing. No rows are
    saved, no member↔user links are made, and no rate-limit quota is consumed.
    """
    serializer_cls = get_serializer_for_model(model_name)
    # One line past what a full-size upload needs (the three template rows plus
    # the cap): enough to tell "at the cap" from "over it", and it keeps the
    # parse off the rest of a runaway file (whose bytes the view caps first).
    all_lines = _read_csv_rows(file_bytes, max_lines=_MAX_IMPORT_ROWS + 4)
    if len(all_lines) < 2:
        raise DataImportInvalid(
            "CSV must contain at least a header row and one data row."
        )

    headers, data_lines, first_data_row_number = _split_template_rows(all_lines)
    if len(data_lines) > _MAX_IMPORT_ROWS:
        raise DataImportInvalid(
            f"CSV has more than {_MAX_IMPORT_ROWS} data rows; imports are "
            f"capped at {_MAX_IMPORT_ROWS} rows per upload. Split the file."
        )
    reserved_member_quota_ids: list[str] = []
    if model_name == "member" and not dry_run:
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
            count=len(data_lines),
            actor=importing_user,
        )
    bool_fields = _collect_bool_fields(serializer_cls)
    result = DataImportResult(model_name=model_name)

    with _dry_run_scope(dry_run):
        for offset, line in enumerate(data_lines):
            row_number = first_data_row_number + offset
            if line.parse_error:
                # The CSV parser itself refused this line (broken quoting, a
                # field past csv's size limit). Report it like any other bad
                # row — the office fixes that line and re-uploads.
                result.errors.append(
                    {
                        "row": row_number,
                        "error": f"Row could not be read: {line.parse_error}",
                        "data": {},
                    }
                )
                continue
            payload = _row_to_payload(headers, line.cells, bool_fields)
            if not payload:
                # Blank line in the middle of the file — silently skip.
                continue
            serializer = serializer_cls(data=payload)
            try:
                if serializer.is_valid():
                    if dry_run:
                        # Faithful preview: run the SAME persistence path (model
                        # full_clean via save(), member↔user linking, DB
                        # constraints). Serializer ``is_valid()`` alone misses
                        # model-level invariants (TimeBoundMixin Monday/Sunday,
                        # finalized-protection, DB constraints), so a preview that
                        # skipped save() would show green for rows the real import
                        # later rejects.
                        #
                        # Each row gets its own savepoint (a bad row rolls back to
                        # here and the preview continues) but a SUCCESSFUL row is
                        # deliberately left in place for the rest of the pass —
                        # ``_dry_run_scope`` discards the lot at the end. That is
                        # what makes a duplicate WITHIN the file visible: rolling
                        # every row back individually meant row 2 never saw row 1,
                        # so two rows sharing a unique value (email, member_number,
                        # a member's single SEPA mandate) both previewed green and
                        # then collided for real.
                        with transaction.atomic():
                            _persist_import_row(
                                serializer,
                                model_name,
                                payload,
                                importing_user,
                                confirm_active_users=confirm_active_users,
                            )
                        result.results.append({"row": row_number, "id": None})
                    else:
                        # One transaction PER ROW (requests run in autocommit). The
                        # member path is multi-step — ``serializer.save()`` then
                        # ``link_to_user`` → ``Member.confirm`` (which can raise
                        # e.g. ``MemberCoopSharesOutOfRange``) — so without this the
                        # member would commit on save() and a later link/confirm
                        # failure would strand an orphaned row that is nonetheless
                        # reported as failed (and duplicated on re-run). Wrapping
                        # makes each row atomic: a mid-row failure rolls the insert
                        # back, leaving a clean per-row error and nothing persisted.
                        with transaction.atomic():
                            instance = _persist_import_row(
                                serializer,
                                model_name,
                                payload,
                                importing_user,
                                confirm_active_users=confirm_active_users,
                            )
                        result.results.append(
                            {"row": row_number, "id": getattr(instance, "id", None)}
                        )
                else:
                    result.errors.append(
                        {
                            "row": row_number,
                            "error": _flatten_drf_errors(serializer.errors),
                            "data": payload,
                        }
                    )
            except (
                DjangoValidationError,
                DRFValidationError,
                DatabaseError,
                JasminError,
                MemberLinkConflict,
                ValueError,
                TypeError,
                AttributeError,
                KeyError,
            ) as exc:
                # Per-row collection: one bad row must not stop the import.
                # Catch the realistic data/parse/DB exception families
                # (DatabaseError covers Integrity/Data/InternalError etc.;
                # JasminError covers domain rules raised at save(), e.g.
                # OpenEndedSubscriptionNotAllowed / delivery-day out-of-range —
                # otherwise one such row would abort the whole batch).
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
