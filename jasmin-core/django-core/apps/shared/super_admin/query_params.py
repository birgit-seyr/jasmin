"""Super-admin (platform) API query-parameter catalogue.

Small by design: the platform endpoints take almost no filters. What they do
take is declared here as a ``ParamSpec`` so the OpenAPI description and the
runtime validation both read the SAME entry (via
``apps.shared.openapi_params.catalogue_parameter`` and
``validate_query_params``) instead of an inline parameter next to a
hand-rolled token check.

See :mod:`apps.shared.query_params` for the machinery and the per-kind
validation depth.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import ParamSpec
from apps.shared.query_params import validate_query_params as _validate

PARAM_CATALOGUE: dict[str, ParamSpec] = {
    # Counting users is cross-schema work, so the tenant roster stays useful
    # without it — but the dashboard wants the counts, hence the True default.
    "include_user_count": ParamSpec("bool", default=True),
}


def validate_query_params(
    request: Request,
    *,
    required: list[str] | tuple[str, ...] = (),
    optional: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate the named query params against the super-admin catalogue."""
    return _validate(request, PARAM_CATALOGUE, required=required, optional=optional)
