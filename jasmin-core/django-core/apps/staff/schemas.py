"""OpenAPI parameter helpers for the staff app.

Built from ``STAFF_PARAM_CATALOGUE`` (single source of truth for each param's
type/range), mirroring ``apps/commissioning/schemas.py``.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from .query_params import STAFF_PARAM_CATALOGUE

_CATALOGUE_OPENAPI_TYPE = {
    "int": OpenApiTypes.INT,
    "bool": OpenApiTypes.BOOL,
    "str": OpenApiTypes.STR,
    "choice": OpenApiTypes.STR,
    "date": OpenApiTypes.DATE,
}


def _catalogue_parameter(name, *, description="", required=False, **overrides):
    spec = STAFF_PARAM_CATALOGUE[name]
    kwargs = {
        "name": name,
        "type": _CATALOGUE_OPENAPI_TYPE[spec.kind],
        "location": OpenApiParameter.QUERY,
        "required": required,
        "description": description,
    }
    if spec.default is not None:
        kwargs["default"] = spec.default
    kwargs.update(overrides)
    return OpenApiParameter(**kwargs)


def get_year_parameter(**overrides):
    required = overrides.pop("required", True)
    return _catalogue_parameter(
        "year", description="Calendar year", required=required, **overrides
    )


def get_week_parameter(**overrides):
    required = overrides.pop("required", True)
    return _catalogue_parameter(
        "week", description="ISO week number (1–53)", required=required, **overrides
    )
