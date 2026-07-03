"""Generic, catalogue-driven query-parameter validation machinery.

Each app declares its own catalogue — a ``{name: ParamSpec}`` dict — and
validates by *naming* the params an endpoint reads::

    params = validate_query_params(
        request, MY_CATALOGUE, required=["year"], optional=["month"]
    )

instead of re-deriving coercion/ranges at each call site (the manual
``int(raw)`` / ``strptime(raw)`` pattern that turns ``?year=abc`` into an
HTTP 500).

Validation depth by kind:

* ``int``    — parsed + range-checked (prevents the ``int(None)`` /
  ``int('abc')`` HTTP 500s).
* ``date``   — validated as ``YYYY-MM-DD`` and returned as a ``date`` object.
* ``bool``   — strict ``true``/``false`` (a typo'd ``?flag=ture`` 400s
  instead of quietly becoming ``False``).
* ``choice`` — checked against an allowed set (a bad value 400s instead of
  silently matching zero rows).
* ``str``    — passthrough (FK ids are STR; a bad value yields an empty
  filter, not a 500).

All failures raise :class:`core.errors.InvalidQueryParam` (HTTP 400, code
``query.invalid_param``) with ``field`` naming the offending parameter.

The canonical catalogue lives in ``apps/commissioning/utils/query_params.py``;
other apps (payments, notifications) keep their own small catalogues built on
this machinery.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from rest_framework.request import Request

from core.errors import InvalidQueryParam

ParamKind = Literal["int", "bool", "str", "choice", "date"]

_TRUE_TOKENS = frozenset({"true", "1", "yes", "on"})
_FALSE_TOKENS = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class ParamSpec:
    """Declares how one query parameter is parsed and validated."""

    kind: ParamKind
    min_value: int | None = None
    max_value: int | None = None
    choices: tuple[str, ...] | None = None
    default: Any = None


def coerce_param(raw: str, name: str, spec: ParamSpec):
    """Coerce one raw query-param string according to its spec (400 on failure)."""
    if spec.kind == "str":
        return raw
    if spec.kind == "bool":
        token = raw.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
        raise InvalidQueryParam(
            f"Parameter '{name}' must be a boolean (true/false)",
            field=name,
            details={name: raw},
        )
    if spec.kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidQueryParam(
                f"Parameter '{name}' must be an integer",
                field=name,
                details={name: raw},
            ) from exc
        lo, hi = spec.min_value, spec.max_value
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise InvalidQueryParam(
                f"Parameter '{name}' must be between {lo} and {hi}",
                field=name,
                details={name: raw},
            )
        return value
    if spec.kind == "choice":
        choices = spec.choices or ()
        if raw not in choices:
            raise InvalidQueryParam(
                f"Parameter '{name}' must be one of: {', '.join(choices)}",
                field=name,
                details={name: raw},
            )
        return raw
    if spec.kind == "date":
        # Validate the "YYYY-MM-DD" wire format and return a ``date`` OBJECT:
        # consumers do real date work (``.isocalendar()`` week iteration,
        # ``.isoformat()`` for export filenames, ORM date filters).
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise InvalidQueryParam(
                f"Parameter '{name}' must be a date (YYYY-MM-DD)",
                field=name,
                details={name: raw},
            ) from exc
    raise AssertionError(f"Unhandled param kind: {spec.kind}")  # pragma: no cover


def _parse_one(
    request: Request,
    name: str,
    catalogue: dict[str, ParamSpec],
    *,
    required: bool,
):
    spec = catalogue.get(name)
    if spec is None:
        # Programmer error: name a param that isn't catalogued. Add it to
        # the app's catalogue rather than reading it raw.
        raise KeyError(f"Query parameter '{name}' is not in the catalogue")
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        if required:
            raise InvalidQueryParam(
                f"Missing required query parameter: '{name}'", field=name
            )
        return spec.default
    return coerce_param(raw, name, spec)


def validate_query_params(
    request: Request,
    catalogue: dict[str, ParamSpec],
    *,
    required: list[str] | tuple[str, ...] = (),
    optional: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate the named query params against the given catalogue.

    Returns ``{name: parsed_value}``. A required-but-missing param → 400; a
    present value that fails its catalogue spec → 400 (``InvalidQueryParam``).
    Absent optional params return their catalogue ``default`` (usually ``None``).
    """
    out: dict[str, Any] = {}
    for name in required:
        out[name] = _parse_one(request, name, catalogue, required=True)
    for name in optional:
        out[name] = _parse_one(request, name, catalogue, required=False)
    return out


def validate_choice_param(
    value: str, valid_choices: Collection[str], param_name: str
) -> str:
    """Validate a query-param value against a set of allowed choices.

    Raises ``InvalidQueryParam`` (HTTP 400) with a deterministic,
    alphabetically sorted choice list in the message; returns the value
    unchanged when it is valid.
    """
    if value not in valid_choices:
        raise InvalidQueryParam(
            f"Invalid {param_name} '{value}'. Must be one of: "
            f"{', '.join(sorted(valid_choices))}",
            field=param_name,
            details={param_name: value},
        )
    return value
