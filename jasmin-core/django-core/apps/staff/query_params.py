"""Staff app's query-parameter catalogue (built on the shared machinery).

Holds the params that are staff-specific and NOT in the commissioning catalogue
— the ISO ``week`` and the copy ``from_week`` / ``to_week``. (The generic
``is_active`` param is reused from commissioning; ``year`` lives here so the
staff schema helpers stay self-contained.)
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import ParamSpec
from apps.shared.query_params import validate_query_params as _validate

STAFF_PARAM_CATALOGUE: dict[str, ParamSpec] = {
    "year": ParamSpec("int", min_value=2000, max_value=2100),
    "week": ParamSpec("int", min_value=1, max_value=53),
    "from_week": ParamSpec("int", min_value=1, max_value=53),
    "to_week": ParamSpec("int", min_value=1, max_value=53),
}


def validate_query_params(
    request: Request,
    *,
    required: list[str] | tuple[str, ...] = (),
    optional: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    return _validate(
        request, STAFF_PARAM_CATALOGUE, required=required, optional=optional
    )
