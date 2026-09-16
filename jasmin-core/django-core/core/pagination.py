"""Project-wide pagination classes.

`OptionalLimitOffsetPagination` is the workhorse: attach it to a ViewSet and
the list endpoint becomes paginatable WITHOUT changing the response shape
for callers that don't ask for pagination. Old callers (`GET /members/`)
keep getting a plain array. New callers (`GET /members/?limit=200`) get the
envelope `{count, next, previous, results: [...]}`.

This lets us roll pagination out per-page on the frontend without a big-bang
migration.

Both classes read `limit` / `offset` through the shared query-param catalogue
(`apps.shared.query_params.PAGINATION_PARAM_CATALOGUE`), so the documented
type and bounds are the validated ones — see
``ValidatedLimitOffsetPagination`` for what that changes.

SCHEMA NOTE (deliberate single-shape typing): the OpenAPI schema declares
ONLY the bare array shape — see ``get_paginated_response_schema`` below —
so orval keeps typing list endpoints as ``T[]``. A ``oneOf`` union would be
the honest two-shape declaration, but it would force type-narrowing on
every list consumer in the app to serve the rare paginated caller. The
trade-off: a frontend caller that passes ``?limit=`` receives the envelope
at runtime and must locally cast, e.g.::

    const payload = data as { count?: number; results?: Row[] } | undefined;

(``DecidedDeletionsCard.tsx`` is the reference implementation of that
pattern.)
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from drf_spectacular.utils import OpenApiParameter
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request

from apps.shared.openapi_params import param_schema
from apps.shared.query_params import PAGINATION_PARAM_CATALOGUE, coerce_param


class ValidatedLimitOffsetPagination(LimitOffsetPagination):
    """``LimitOffsetPagination`` that validates its two parameters.

    DRF's own ``get_limit`` / ``get_offset`` swallow every parse error and
    fall back to the default, so ``?limit=abc``, ``?limit=0`` and
    ``?limit=-3`` all read as "no limit given" — on a paginator whose
    ``default_limit`` is ``None`` that hands a caller who asked for one page
    the WHOLE table. Here each of those is an HTTP 400
    (``query.invalid_param``) naming the parameter.

    Accepted: ``limit`` an integer >= 1, ``offset`` an integer >= 0; absent or
    empty means "not sent". A ``limit`` above ``max_limit`` is served AT
    ``max_limit`` rather than refused, so the cap is a clamp and not a
    constraint: it is documented in the parameter's prose, NOT as an OpenAPI
    ``maximum`` — a ``maximum`` is a rule a schema-driven caller enforces
    before sending, and it would refuse a request this server answers.
    """

    # English, and describing this project's semantics. DRF's own wording goes
    # through Django's translations, which renders the public schema in the
    # server's locale.
    limit_query_description = "Maximum number of rows to return."
    offset_query_description = (
        "Index of the first row to return. Only meaningful together with `limit`."
    )

    def get_limit(self, request: Request) -> int | None:
        raw = request.query_params.get(self.limit_query_param)
        if raw is None or not raw.strip():
            return self.default_limit
        # ``max_value`` is dropped for the parse: the cap is applied by
        # clamping below, not by refusing the request.
        limit = coerce_param(
            raw,
            self.limit_query_param,
            replace(PAGINATION_PARAM_CATALOGUE["limit"], max_value=None),
        )
        return min(limit, self.max_limit) if self.max_limit else limit

    def get_offset(self, request: Request) -> int:
        raw = request.query_params.get(self.offset_query_param)
        if raw is None or not raw.strip():
            return 0
        return coerce_param(
            raw, self.offset_query_param, PAGINATION_PARAM_CATALOGUE["offset"]
        )

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        # Derived from the catalogue (type AND bounds) instead of DRF's
        # hand-written bare ``{"type": "integer"}``, so the documented range is
        # the enforced one. ``max_limit`` stays out of it: ``get_limit`` clamps
        # to it instead of refusing, and publishing it as ``maximum`` would
        # declare a rule the server does not apply.
        return [
            {
                "name": self.limit_query_param,
                "required": False,
                "in": "query",
                "description": self.limit_query_description,
                "schema": param_schema(PAGINATION_PARAM_CATALOGUE["limit"]),
            },
            {
                "name": self.offset_query_param,
                "required": False,
                "in": "query",
                "description": self.offset_query_description,
                "schema": param_schema(PAGINATION_PARAM_CATALOGUE["offset"]),
            },
        ]

    @classmethod
    def openapi_parameters(cls) -> list[OpenApiParameter]:
        """The same two parameters as ``OpenApiParameter`` objects, for a view
        that paginates BY HAND (an ``@api_view`` instantiating the paginator in
        its body) where drf-spectacular has no ``pagination_class`` to find.
        """
        return [
            OpenApiParameter(
                name=parameter["name"],
                type=parameter["schema"],
                location=OpenApiParameter.QUERY,
                required=False,
                description=parameter["description"],
            )
            for parameter in cls().get_schema_operation_parameters(view=None)
        ]


class OptionalLimitOffsetPagination(ValidatedLimitOffsetPagination):
    """Pagination that activates only when the caller passes `?limit=`.

    Behaviour:
      * No `?limit=` (or `?offset=`) in the query → ``paginate_queryset``
        returns ``None``, which makes DRF return the full queryset shape
        (a plain list). Same as having no pagination configured.
      * `?limit=N` (with optional `?offset=M`) → standard LimitOffset
        pagination kicks in. Response is `{count, next, previous, results}`.

    ``max_limit`` keeps callers from accidentally requesting the full table —
    page size grows with what you pass, but caps at this number.
    """

    default_limit = None  # ← critical: when None, DRF skips pagination
    max_limit = 1000

    limit_query_description = (
        "Page size. Pass it to opt into pagination: the response is then "
        "`{count, next, previous, results}` instead of a plain array. A value "
        f"above {max_limit} is served at {max_limit} rather than refused."
    )

    def paginate_queryset(
        self, queryset, request: Request, view=None
    ) -> list[Any] | None:
        # If the caller didn't opt in (no `limit` AND no `offset`), bypass.
        # DRF's default would still paginate with `default_limit`, but ours
        # is None so this is purely defensive in case someone changes it.
        # An empty value (`?limit=`) counts as not sent.
        if not request.query_params.get(
            self.limit_query_param
        ) and not request.query_params.get(self.offset_query_param):
            return None
        # Validate BOTH here: DRF reaches ``get_offset`` only once it has a
        # usable limit, so a malformed offset sent on its own would otherwise
        # pass unnoticed.
        self.get_limit(request)
        self.get_offset(request)
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        # The default response is a plain list (no envelope) because we opt out
        # of pagination unless `?limit=` is explicit. Tell drf-spectacular to
        # generate the array shape so the orval client keeps typing list
        # endpoints as `T[]`. Paginated callers (with `?limit=`) still get the
        # envelope at runtime — they just won't see it in the schema.
        return schema
