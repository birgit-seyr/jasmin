"""OpenAPI parameter helpers for the staff app.

Built from ``STAFF_PARAM_CATALOGUE`` (single source of truth for each param's
type/range), mirroring ``apps/commissioning/schemas.py``.
"""

from __future__ import annotations

from apps.shared.openapi_params import catalogue_parameter

from .query_params import STAFF_PARAM_CATALOGUE


def catalogue_param(name, *, description="", required=False, **overrides):
    """Build an OpenApiParameter from STAFF_PARAM_CATALOGUE[name] — single source
    of truth for the param's type/enum/default. ``overrides`` win.

    Thin binding of the generic helper in :mod:`apps.shared.openapi_params` to
    the staff catalogue."""
    return catalogue_parameter(
        name,
        STAFF_PARAM_CATALOGUE,
        description=description,
        required=required,
        **overrides,
    )


def get_year_parameter(**overrides):
    required = overrides.pop("required", True)
    return catalogue_param(
        "year", description="Calendar year", required=required, **overrides
    )


def get_week_parameter(**overrides):
    required = overrides.pop("required", True)
    return catalogue_param(
        "week",
        description=(
            "ISO week number (1-53). Week 53 is accepted only for a year that "
            "has one; sent with a 52-week year it is refused."
        ),
        required=required,
        **overrides,
    )
