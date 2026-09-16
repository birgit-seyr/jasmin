"""Notifications query-parameter catalogue (built on the shared machinery).

Holds the filters the email-log list accepts. ``status`` is a closed set —
the same choices the model column stores — so a typo 400s instead of
returning an empty log, and the OpenAPI schema carries the enum.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import ParamSpec
from apps.shared.query_params import validate_query_params as _validate

from .models import EmailLog

PARAM_CATALOGUE: dict[str, ParamSpec] = {
    # The template endpoints' ``?language=``. A free string, not a ``choice``:
    # ``normalize_language`` accepts far more than the two bare codes
    # (``de-DE``, ``deutsch``, ``german``, …) and falls back to the tenant
    # default for anything it cannot map, so closing the set here would refuse
    # spellings the server serves today.
    "language": ParamSpec("str"),
    "recipient": ParamSpec("str"),
    # Free-form CharField on the model (no choices) — passthrough.
    "purpose": ParamSpec("str"),
    "status": ParamSpec(
        "choice",
        choices=tuple(value for value, _label in EmailLog.STATUS_CHOICES),
    ),
}


def validate_query_params(
    request: Request,
    *,
    required: list[str] | tuple[str, ...] = (),
    optional: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate the named query params against the notifications catalogue."""
    return _validate(request, PARAM_CATALOGUE, required=required, optional=optional)
