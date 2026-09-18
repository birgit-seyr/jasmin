"""
Generic validation utilities for request parameters.
Reusable across all views in the commissioning app.

All helpers raise a :class:`core.errors.JasminError` subclass (HTTP 400 via
``core.exception_handler``) on bad input and return the parsed values
directly — callers don't need any error handling.
"""

from __future__ import annotations

import datetime
from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import ParamSpec, coerce_param
from apps.shared.request_utils import body

from ..errors import (
    BulkIdsInvalid,
    BulkIdsTooMany,
    CommissioningError,
    RequiredFieldMissing,
)
from .query_params import PARAM_CATALOGUE

# The body ints this helper parses take the query catalogue's bounds, so a year
# means the same thing in a POST body as in a query string. ``week`` is the
# body spelling of ``delivery_week``.
_BODY_INT_SPECS = {
    "year": PARAM_CATALOGUE["year"],
    "delivery_week": PARAM_CATALOGUE["delivery_week"],
    "week": PARAM_CATALOGUE["delivery_week"],
}

#: A name with no catalogued range: still parsed as an integer, just unbounded.
_UNBOUNDED_INT = ParamSpec("int")

# Ceiling on the ids one bulk call may carry. Every id costs a row lock plus
# its cascade inside the caller's single transaction, and the bulk stock views
# additionally take one transaction-scoped advisory lock per distinct entity in
# the batch, held until that transaction commits. Postgres sizes its lock table
# cluster-wide — roughly ``max_locks_per_transaction * max_connections``, ~6400
# at the defaults this deployment runs on — so one oversized batch can push
# unrelated transactions, other tenants included, into "out of shared memory".
# 1000 holds a single batch to roughly a sixth of that table, so several
# concurrent batches still fit. It also stays clear of every batch the office
# UI can produce: a bulk action is fed the table's checkbox selection, and the
# page-size picker tops out at 500 rows. An endpoint whose per-id work is
# heavier than a lock — the subscription bulk renewal, which resolves a
# variation and runs a full_clean INSERT per id — passes its own lower
# ``max_count`` rather than relying on this ceiling.
MAX_BULK_IDS = 1000


def parse_body_int_fields(
    request: Request,
    field_names: list[str],
    ranges: dict[str, tuple[int, int]] | None = None,
) -> list[int]:
    """Validate and parse integer fields from the request BODY.

    Body-only: a query parameter is validated by ``validate_query_params``
    against ``PARAM_CATALOGUE``, the front door for the query string, and the
    catalogue models no body fields.

    Parsing and the 400 shape come from ``coerce_param``, the same parser the
    catalogued query parameters use, so an integer means one thing everywhere.
    The ranges are the catalogue's as well:
    - year: 1900-2100
    - delivery_week/week: 1-53

    Args:
        request: DRF Request object
        field_names: Body fields to read, in the order their values are returned
        ranges: Optional custom ranges overriding the defaults {field: (min, max)}

    Returns:
        List of parsed integer values (same order as ``field_names``).

    Raises:
        RequiredFieldMissing: if a field is absent from the body.
        InvalidQueryParam: if a present value is not an integer or lies outside
            its allowed range — ``coerce_param`` raises that one for a body
            scalar just as it does for a query parameter.

    Example:
        >>> year, week = parse_body_int_fields(
        ...     request, ["year", "delivery_week"]
        ... )

        >>> # Custom range override
        >>> (year,) = parse_body_int_fields(
        ...     request, ["year"], ranges={"year": (1900, 2200)}
        ... )
    """
    effective_specs = dict(_BODY_INT_SPECS)
    if ranges:
        effective_specs.update(
            {
                name: ParamSpec("int", min_value=low, max_value=high)
                for name, (low, high) in ranges.items()
            }
        )

    parsed_values = []
    # ``body`` rather than ``request.data``: a body that is not a JSON object
    # (an array, a bare string) reads as empty here, so the missing-field 400
    # below answers it instead of ``.get`` raising AttributeError (500).
    fields = body(request)

    for field_name in field_names:
        value = fields.get(field_name)

        # Nothing was sent, so ``field`` names it and there is no offending
        # value for ``details`` to echo — unlike the coercion failures below.
        if value is None:
            raise RequiredFieldMissing(
                f"{field_name} field is required",
                field=field_name,
            )

        # ``str`` because a JSON body carries real ints, while the shared
        # parser reads the wire spelling.
        parsed_values.append(
            coerce_param(
                str(value),
                field_name,
                effective_specs.get(field_name, _UNBOUNDED_INT),
            )
        )

    return parsed_values


def parse_body_date(
    request: Request,
    field: str,
    *,
    required: bool = True,
    code_prefix: str,
    required_code: str | None = None,
    format_code: str | None = None,
) -> datetime.date | None:
    """Parse an ISO ``YYYY-MM-DD`` date from the request BODY.

    Returns the parsed :class:`datetime.date`; ``None`` when the field is
    absent/empty and ``required=False`` (e.g. an optional ``valid_until``).

    Raises :class:`apps.commissioning.errors.CommissioningError` (HTTP 400) with
    a stable per-case ``code`` on missing/malformed input. The codes default to
    ``<code_prefix>.<field>_required`` / ``<code_prefix>.<field>_format``; pass
    ``required_code`` / ``format_code`` to preserve a pre-existing non-standard
    code (so consolidating the call site doesn't change the wire contract).
    """
    raw = body(request).get(field)
    if not raw:
        if not required:
            return None
        raise CommissioningError(
            "This field is required.",
            field=field,
            code=required_code or f"{code_prefix}.{field}_required",
        )
    try:
        return datetime.date.fromisoformat(str(raw))
    except (ValueError, TypeError) as exc:
        raise CommissioningError(
            "Expected YYYY-MM-DD.",
            field=field,
            code=format_code or f"{code_prefix}.{field}_format",
        ) from exc


def parse_bulk_ids(
    request: Request,
    *,
    field: str = "ids",
    invalid_item_error: type[BulkIdsInvalid] = BulkIdsInvalid,
    max_count: int = MAX_BULK_IDS,
) -> list[str]:
    """Extract and validate the ``{field: [...]}`` array from a bulk request body.

    The single canonical parser for every bulk-by-IDs endpoint (finalize,
    inventory, forecast-copy, offer/reminder-send, set-to-paid, …). Returns the
    list of IDs and raises
    :class:`apps.commissioning.errors.RequiredFieldMissing`
    (HTTP 400, ``field=<field>``) when the value is missing, empty, or not a
    list.

    Every entry must be a non-empty string, otherwise ``invalid_item_error``
    (default :class:`apps.commissioning.errors.BulkIdsInvalid`, HTTP 400,
    ``field=<field>``) is raised. Ids are string primary keys or string
    composite ids; a number, null, list or object entry would otherwise reach
    the composite-id parsers, which call ``.split`` on it and fail with a 500.

    At most ``max_count`` ids (default :data:`MAX_BULK_IDS`) per call, otherwise
    :class:`apps.commissioning.errors.BulkIdsTooMany` (HTTP 400) is raised with
    the ``limit`` and the ``received`` count in ``details``.
    """
    ids = body(request).get(field)
    if not ids or not isinstance(ids, list):
        raise RequiredFieldMissing(
            "A non-empty list of IDs is required.",
            field=field,
        )
    if not all(isinstance(item, str) and item.strip() for item in ids):
        raise invalid_item_error("Every id must be a non-empty string.", field=field)
    if len(ids) > max_count:
        raise BulkIdsTooMany(
            f"At most {max_count} ids per request.",
            field=field,
            details={"limit": max_count, "received": len(ids)},
        )
    return ids


def validate_bulk_document_request(request: Request) -> dict[str, Any]:
    """
    Validate request for bulk document operations (create/finalize/delete).

    Returns:
        Dict: {"order_ids": list, "model": str, "date": datetime.date|None}

    Raises:
        RequiredFieldMissing: if ``ids`` is missing or not a non-empty list.
        CommissioningError: if ``model`` is not a known document model, or
            ``date`` is present but not ``YYYY-MM-DD``.

    Example:
        >>> params = validate_bulk_document_request(request)
        >>> order_ids = params["order_ids"]
        >>> model = params["model"]
    """
    order_ids = parse_bulk_ids(request)
    model = body(request).get("model")
    # A malformed non-empty ``date`` must not reach ``coerce_document_date``:
    # that helper falls back to the order's ISO-week date, so a typo used to
    # issue a delivery note or invoice carrying a date nobody asked for — on a
    # document that is legally immutable once finalized. Absent / empty still
    # means "derive it", which is what the office UI sends.
    date = parse_body_date(
        request,
        "date",
        required=False,
        code_prefix="bulk_documents",
    )

    if model not in ["delivery_note", "invoice"]:
        raise CommissioningError(
            "model must be either 'delivery_note' or 'invoice'",
            field="model",
            code="bulk_documents.model_invalid",
        )

    return {
        "order_ids": order_ids,
        "model": model,
        "date": date,
    }
