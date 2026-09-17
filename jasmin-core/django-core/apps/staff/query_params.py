"""Staff app's query-parameter catalogue (built on the shared machinery).

Holds the query params staff endpoints validate by: ``year`` and the ISO
``week``. (The generic ``is_active`` param is reused from commissioning;
``year`` lives here too so the staff schema helpers stay self-contained.)

The copy endpoint's ``from_week`` / ``to_week`` are request-BODY fields
validated by ``WeeklyPlanCopySerializer``, not query params, so they are not
catalogued here.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import ISO_WEEK_PARAM, YEAR_PARAM, ParamSpec
from apps.shared.query_params import validate_query_params as _validate

STAFF_PARAM_CATALOGUE: dict[str, ParamSpec] = {
    "year": YEAR_PARAM,
    "week": ISO_WEEK_PARAM,
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
