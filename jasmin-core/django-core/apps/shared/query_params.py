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
  ``int('abc')`` HTTP 500s). ASCII digits with an optional sign only: Python's
  ``int()`` also reads ``1_0``, ``٥`` and other non-ASCII digits, spellings no
  caller means and every downstream ``str(value)`` renders differently.
* ``date``   — validated as ``YYYY-MM-DD`` and returned as a ``date`` object.
* ``bool``   — one of ``true``/``false``, ``1``/``0``, ``yes``/``no``,
  ``on``/``off``, case-insensitive. Anything else 400s (a typo'd ``?flag=ture``
  does not quietly become ``False``), and an explicit false token parses as
  ``False`` rather than merely "present".
* ``choice`` — checked against an allowed set (a bad value 400s instead of
  silently matching zero rows). A spec marked ``case_insensitive`` accepts any
  casing and returns the catalogue's own spelling.
* ``str``    — passthrough (FK ids are STR; a bad value yields an empty
  filter, not a 500).

Surrounding whitespace is trimmed for every kind but ``str``, whose value is a
stored id that must match byte for byte.

Two rules need two parameters each and so cannot live in a single spec.
:func:`validate_query_params` applies both once a call has parsed the halves:

* ISO week 53 exists only in a 53-week year — checked whenever one call parses
  both a ``year`` and a week (a spec marked ``iso_week``); see
  :func:`weeks_in_iso_year`.
* an inclusive date range runs forwards — checked whenever one call parses both
  halves of a pair listed in :data:`DATE_RANGE_PAIRS`.

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

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from rest_framework.request import Request

from core.errors import InvalidQueryParam

ParamKind = Literal["int", "bool", "str", "choice", "date"]

#: The boolean spellings accepted on the wire, in a query string and in a
#: request body alike. Compared case-insensitively after stripping whitespace.
_TRUE_TOKENS = frozenset({"true", "1", "yes", "on"})
_FALSE_TOKENS = frozenset({"false", "0", "no", "off"})

#: An integer on the wire: ASCII digits, optionally signed.
_INT_TOKEN = re.compile(r"[+-]?[0-9]+")


@dataclass(frozen=True)
class ParamSpec:
    """Declares how one query parameter is parsed and validated.

    ``wire_name`` is the name the client sends, when it differs from the
    catalogue key. The key then stays the *logical* name an endpoint validates
    by, so one app can catalogue two closed enums that share a generic name on
    the wire (``kind`` on consent documents versus on import mappings) instead
    of leaving either as a free string.

    ``case_insensitive`` (``choice`` only) accepts any casing and yields the
    catalogue's spelling — for a parameter whose callers have always been free
    to send either case.

    ``iso_week`` (``int`` only) marks the value as an ISO week number. The
    spec bounds it to 1-53 on its own; whether 53 exists depends on the year,
    so :func:`validate_query_params` checks that pair once both are parsed.
    """

    kind: ParamKind
    min_value: int | None = None
    max_value: int | None = None
    choices: tuple[str, ...] | None = None
    default: Any = None
    wire_name: str | None = None
    case_insensitive: bool = False
    iso_week: bool = False


#: The two pagination parameters, shared by every app rather than re-declared
#: per endpoint: ``core.pagination`` validates and documents ``limit`` and
#: ``offset`` from these entries. No ``max_value`` on ``limit`` — the ceiling
#: is the paginator's own ``max_limit``, which it fills in.
PAGINATION_PARAM_CATALOGUE: dict[str, ParamSpec] = {
    "limit": ParamSpec("int", min_value=1),
    "offset": ParamSpec("int", min_value=0),
}

#: The ``year`` every app's catalogue declares, defined once so the same value
#: is accepted whichever app serves the request. The range is wide because
#: ``year`` is not only a delivery year: the member statistics filter birth and
#: entry years through the same parameter.
YEAR_PARAM = ParamSpec("int", min_value=1900, max_value=2100)

#: An ISO week number. 53 is bounds-valid here and refused for a 52-week year
#: once the pair is known — see :func:`validate_query_params`.
ISO_WEEK_PARAM = ParamSpec("int", min_value=1, max_value=53, iso_week=True)

#: The inclusive date-range pairs the API takes, as ``(start, end)`` catalogue
#: names. An endpoint that reads both halves of a pair means one range, so the
#: order rule is checked here for all of them rather than re-written per
#: endpoint.
DATE_RANGE_PAIRS: tuple[tuple[str, str], ...] = (
    ("start_date", "end_date"),
    ("date_from", "date_to"),
)


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
        # NOT trimmed: the value is a stored id, matched byte for byte.
        return raw
    if spec.kind == "bool":
        return _bool_from_token(raw, name)
    token = raw.strip()
    if spec.kind == "int":
        if not _INT_TOKEN.fullmatch(token):
            raise InvalidQueryParam(
                f"Parameter '{name}' must be an integer",
                field=name,
                details={name: raw},
            )
        value = int(token)
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
        chosen = token
        if spec.case_insensitive:
            # Hand back the catalogue's spelling, so every downstream lookup
            # (model maps, ORM filters) sees one canonical value whatever
            # casing the caller sent.
            chosen = {choice.casefold(): choice for choice in choices}.get(
                token.casefold(), token
            )
        if chosen not in choices:
            raise InvalidQueryParam(
                f"Parameter '{name}' must be one of: {', '.join(choices)}",
                field=name,
                details={name: raw},
            )
        return chosen
    if spec.kind == "date":
        # Validate the "YYYY-MM-DD" wire format and return a ``date`` OBJECT:
        # consumers do real date work (``.isocalendar()`` week iteration,
        # ``.isoformat()`` for export filenames, ORM date filters).
        try:
            return datetime.strptime(token, "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise InvalidQueryParam(
                f"Parameter '{name}' must be a date (YYYY-MM-DD)",
                field=name,
                details={name: raw},
            ) from exc
    raise AssertionError(f"Unhandled param kind: {spec.kind}")  # pragma: no cover


def weeks_in_iso_year(year: int) -> int:
    """How many ISO weeks ``year`` has — 52 or 53.

    December 28 always falls in its ISO year's last week, so its week number
    is the count.
    """
    return date(year, 12, 28).isocalendar()[1]


def _refuse_a_week_the_year_does_not_have(
    parsed: dict[str, Any], catalogue: dict[str, ParamSpec]
) -> None:
    """400 on week 53 of a 52-week year, once both halves are known.

    Nothing downstream catches this pair: ``isoweek.Week(2027, 53)`` silently
    normalizes to 2028-W01, so the endpoint would answer for a week the caller
    did not ask about, and ``date.fromisocalendar`` raises a bare ``ValueError``
    (HTTP 500) instead.
    """
    year = parsed.get("year")
    if not isinstance(year, int):
        return
    for name, value in parsed.items():
        spec = catalogue[name]
        if not spec.iso_week or value != 53:
            continue
        if weeks_in_iso_year(year) == 53:
            continue
        wire_name = spec.wire_name or name
        raise InvalidQueryParam(
            f"Parameter '{wire_name}' must be between 1 and 52: "
            f"{year} has 52 ISO weeks",
            field=wire_name,
            details={wire_name: str(value), "year": str(year)},
        )


def _refuse_an_inverted_date_range(
    parsed: dict[str, Any], catalogue: dict[str, ParamSpec]
) -> None:
    """400 on a range whose end precedes its start, once both halves are known.

    No consumer has an answer for a backwards range. A scan filter
    (``>= start`` AND ``<= end``) can only return empty, which the caller reads
    as "no data" rather than as "you swapped the dates"; an overlap filter
    (``subscription_member_emails``, where each bound narrows the term window
    on its own) instead returns a large set nobody asked for. The 400 names the
    parameter to fix in both cases.
    """
    for start_name, end_name in DATE_RANGE_PAIRS:
        start = parsed.get(start_name)
        end = parsed.get(end_name)
        if not isinstance(start, date) or not isinstance(end, date):
            continue
        if start <= end:
            continue
        start_wire = catalogue[start_name].wire_name or start_name
        end_wire = catalogue[end_name].wire_name or end_name
        raise InvalidQueryParam(
            f"Parameter '{start_wire}' must be on or before '{end_wire}'",
            field=start_wire,
            details={start_wire: start.isoformat(), end_wire: end.isoformat()},
        )


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
    # Read — and report failures under — the name the CLIENT sends, so
    # ``field`` stays keyable against the request even when the catalogue
    # files the spec under a logical name of its own.
    wire_name = spec.wire_name or name
    raw = request.query_params.get(wire_name)
    if raw is None or raw == "":
        if required:
            raise InvalidQueryParam(
                f"Missing required query parameter: '{wire_name}'", field=wire_name
            )
        return spec.default
    return coerce_param(raw, wire_name, spec)


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

    A call also gets the two rules no single spec can hold alone: week 53 of a
    52-week year is a 400 (when it parsed both a ``year`` and an ``iso_week``
    param), and so is a date range that ends before it starts (when it parsed
    both halves of a :data:`DATE_RANGE_PAIRS` pair).
    """
    out: dict[str, Any] = {}
    for name in required:
        out[name] = _parse_one(request, name, catalogue, required=True)
    for name in optional:
        out[name] = _parse_one(request, name, catalogue, required=False)
    _refuse_a_week_the_year_does_not_have(out, catalogue)
    _refuse_an_inverted_date_range(out, catalogue)
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
