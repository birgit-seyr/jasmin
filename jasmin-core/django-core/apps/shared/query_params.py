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
* ``bool``   — one of ``true``/``false``, ``1``/``0``, ``yes``/``no``,
  ``on``/``off``, case-insensitive and whitespace-trimmed. Anything else
  400s (a typo'd ``?flag=ture`` does not quietly become ``False``), and an
  explicit false token parses as ``False`` rather than merely "present".
* ``choice`` — checked against an allowed set (a bad value 400s instead of
  silently matching zero rows).
* ``str``    — passthrough (FK ids are STR; a bad value yields an empty
  filter, not a 500).

All failures raise :class:`core.errors.InvalidQueryParam` (HTTP 400, code
``query.invalid_param``) with ``field`` naming the offending parameter.

The canonical catalogue lives in ``apps/commissioning/utils/query_params.py``;
payments, staff and super-admin keep their own small catalogues built on this
machinery. The two pagination parameters are catalogued in this module itself
(``PAGINATION_PARAM_CATALOGUE``) because every app's paginated list endpoints
share them.

Boolean fields read from a request BODY go through :func:`parse_body_bool`,
which accepts the same tokens, so a flag means the same thing in the query
string and in a JSON or multipart body.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from rest_framework.request import Request

from core.errors import InvalidQueryParam

ParamKind = Literal["int", "bool", "str", "choice", "date"]

#: The boolean spellings accepted on the wire, in a query string and in a
#: request body alike. Compared case-insensitively after stripping whitespace.
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


#: The two pagination parameters, shared by every app rather than re-declared
#: per endpoint: ``core.pagination`` validates and documents ``limit`` and
#: ``offset`` from these entries. No ``max_value`` on ``limit`` — the ceiling
#: is the paginator's own ``max_limit``, which it fills in.
PAGINATION_PARAM_CATALOGUE: dict[str, ParamSpec] = {
    "limit": ParamSpec("int", min_value=1),
    "offset": ParamSpec("int", min_value=0),
}


def _bool_from_token(raw: str, name: str) -> bool:
    """Parse one of the accepted boolean spellings (400 on anything else)."""
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


def parse_body_bool(data: dict[str, Any], name: str, *, default: bool = False) -> bool:
    """Parse one boolean flag out of a request BODY (400 on a bad value).

    Accepts a real JSON boolean, the JSON numbers ``0``/``1``, and the string
    spellings ``true``/``false``, ``1``/``0``, ``yes``/``no``, ``on``/``off``
    (case-insensitive, whitespace-trimmed) — the same token set a ``bool``
    query parameter accepts, so a flag means the same thing wherever it is
    sent. Absent, ``null`` or empty yields ``default``.

    Use it for every body flag instead of ``bool(body(request).get(...))``:
    that cast turns the string ``"false"`` — which a form post, a hand-written
    client or an older frontend build may well send — into ``True``, silently
    switching the feature ON when the caller asked for it OFF.
    """
    raw = data.get(name)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        return _bool_from_token(raw, name)
    raise InvalidQueryParam(
        f"Parameter '{name}' must be a boolean (true/false)",
        field=name,
        details={name: str(raw)},
    )


def coerce_param(raw: str, name: str, spec: ParamSpec):
    """Coerce one raw query-param string according to its spec (400 on failure)."""
    if spec.kind == "str":
        return raw
    if spec.kind == "bool":
        return _bool_from_token(raw, name)
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
