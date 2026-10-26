"""Cultivation app's query-parameter catalogue (built on the shared machinery).

Holds the query params cultivation endpoints validate by: ``year`` and the
batch list's ``is_greenhouse`` filter.

The solver run's ``year`` is a request-BODY field, not a query param, so the
run action reads it from ``request.data`` rather than through this catalogue.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import YEAR_PARAM, ParamSpec
from apps.shared.query_params import validate_query_params as _validate

CULTIVATION_PARAM_CATALOGUE: dict[str, ParamSpec] = {
    "year": YEAR_PARAM,
    "is_greenhouse": ParamSpec("bool"),
}


def validate_query_params(
    request: Request,
    *,
    required: list[str] | tuple[str, ...] = (),
    optional: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    return _validate(
        request, CULTIVATION_PARAM_CATALOGUE, required=required, optional=optional
    )
