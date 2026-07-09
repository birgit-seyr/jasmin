"""
Generic validation utilities for request parameters.
Reusable across all views in the commissioning app.

All helpers raise :class:`apps.commissioning.errors.InvalidQueryParam`
(HTTP 400 via ``core.exception_handler``) on bad input and return the
parsed values directly — callers don't need any error handling.
"""

from __future__ import annotations

import datetime
from typing import Any

from rest_framework.request import Request

from ..errors import CommissioningError, InvalidQueryParam, RequiredFieldMissing


def validate_and_parse_int_params(
    request: Request,
    param_names: list[str],
    source: str = "query",
    ranges: dict[str, tuple[int, int]] | None = None,
) -> list[int]:
    """
    Validate and parse integer parameters from request with automatic range checks.

    Automatically validates common ranges:
    - year: 2000-2100
    - delivery_week/week: 1-53

    Args:
        request: DRF Request object
        param_names: List of parameter names to validate
        source: Where to get params from - "query" (GET) or "data" (POST body)
        ranges: Optional custom ranges to override defaults {param_name: (min, max)}

    Returns:
        List of parsed integer values (same order as ``param_names``).

    Raises:
        InvalidQueryParam: if a parameter is missing, not an integer, or
            outside its allowed range.

    Example:
        >>> # GET request with automatic year/week validation
        >>> year, week = validate_and_parse_int_params(
        ...     request, ["year", "delivery_week"]
        ... )

        >>> # POST request
        >>> year, week = validate_and_parse_int_params(
        ...     request, ["year", "delivery_week"], source="data"
        ... )

        >>> # Custom range override
        >>> (year,) = validate_and_parse_int_params(
        ...     request, ["year"], ranges={"year": (1900, 2200)}
        ... )
    """
    # Default ranges for common parameters
    DEFAULT_RANGES = {
        "year": (2000, 2100),
        "delivery_week": (1, 53),
        "week": (1, 53),
    }

    # Merge custom ranges with defaults
    if ranges:
        effective_ranges = {**DEFAULT_RANGES, **ranges}
    else:
        effective_ranges = DEFAULT_RANGES

    parsed_values = []
    params_source = request.query_params if source == "query" else request.data

    for param_name in param_names:
        value = params_source.get(param_name)

        # Check if parameter is present
        if value is None:
            raise InvalidQueryParam(
                f"{param_name} parameter is required",
                field=param_name,
            )

        # Parse integer
        try:
            parsed_value = int(value)
        except (ValueError, TypeError) as exc:
            raise InvalidQueryParam(
                f"{param_name} must be an integer",
                field=param_name,
            ) from exc

        # Check range if defined
        if param_name in effective_ranges:
            min_val, max_val = effective_ranges[param_name]
            if not min_val <= parsed_value <= max_val:
                raise InvalidQueryParam(
                    f"{param_name} must be between {min_val} and {max_val}, "
                    f"got {parsed_value}",
                    field=param_name,
                    details={"min": min_val, "max": max_val, "got": parsed_value},
                )

        parsed_values.append(parsed_value)

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
    raw = request.data.get(field)
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


def parse_bulk_ids(request: Request, *, field: str = "ids") -> list[str]:
    """Extract and validate the ``{field: [...]}`` array from a bulk request body.

    The single canonical parser for every bulk-by-IDs endpoint (finalize,
    inventory, forecast-copy, offer/reminder-send, set-to-paid, …). Returns the
    list of IDs and raises one canonical error —
    :class:`apps.commissioning.errors.RequiredFieldMissing`
    (HTTP 400, ``field=<field>``) — when the value is missing, empty, or not a
    list, replacing the divergent per-endpoint checks.
    """
    ids = request.data.get(field)
    if not ids or not isinstance(ids, list):
        raise RequiredFieldMissing(
            "A non-empty list of IDs is required.",
            field=field,
        )
    return ids


def validate_bulk_document_request(request: Request) -> dict[str, Any]:
    """
    Validate request for bulk document operations (create/finalize/delete).

    Returns:
        Dict: {"order_ids": list, "model": str, "date": str|None}

    Raises:
        RequiredFieldMissing: if ``ids`` is missing or not a non-empty list.
        CommissioningError: if ``model`` is not a known document model.

    Example:
        >>> params = validate_bulk_document_request(request)
        >>> order_ids = params["order_ids"]
        >>> model = params["model"]
    """
    order_ids = parse_bulk_ids(request)
    model = request.data.get("model")
    date = request.data.get("date", None)

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
