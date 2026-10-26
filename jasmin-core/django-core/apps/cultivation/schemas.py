"""OpenAPI parameter helpers for the cultivation app.

Built from ``CULTIVATION_PARAM_CATALOGUE`` (single source of truth for each
param's type/range), mirroring ``apps/staff/schemas.py``.
"""

from __future__ import annotations

from apps.shared.openapi_params import catalogue_parameter

from .query_params import CULTIVATION_PARAM_CATALOGUE


def catalogue_param(name, *, description="", required=False, **overrides):
    """Build an OpenApiParameter from CULTIVATION_PARAM_CATALOGUE[name] — single
    source of truth for the param's type/enum/default. ``overrides`` win.

    Thin binding of the generic helper in :mod:`apps.shared.openapi_params` to
    the cultivation catalogue."""
    return catalogue_parameter(
        name,
        CULTIVATION_PARAM_CATALOGUE,
        description=description,
        required=required,
        **overrides,
    )


def get_year_parameter(**overrides):
    required = overrides.pop("required", True)
    return catalogue_param(
        "year", description="Calendar year", required=required, **overrides
    )


def get_is_greenhouse_parameter(**overrides):
    required = overrides.pop("required", False)
    return catalogue_param(
        "is_greenhouse",
        description=(
            "Filter by protected cultivation. The indoor and outdoor batch pages "
            "each show one side; the placement optimizer only ever plans the "
            "outdoor ones."
        ),
        required=required,
        **overrides,
    )
