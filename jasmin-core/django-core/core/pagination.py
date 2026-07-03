"""Project-wide pagination classes.

`OptionalLimitOffsetPagination` is the workhorse: attach it to a ViewSet and
the list endpoint becomes paginatable WITHOUT changing the response shape
for callers that don't ask for pagination. Old callers (`GET /members/`)
keep getting a plain array. New callers (`GET /members/?limit=200`) get the
envelope `{count, next, previous, results: [...]}`.

This lets us roll pagination out per-page on the frontend without a big-bang
migration.

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

from typing import Any

from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request


class OptionalLimitOffsetPagination(LimitOffsetPagination):
    """Pagination that activates only when the caller passes `?limit=`.

    Behaviour:
      * No `?limit=` (or `?offset=`) in the query → ``paginate_queryset``
        returns ``None``, which makes DRF return the full queryset shape
        (a plain list). Same as having no pagination configured.
      * `?limit=N` (with optional `?offset=M`) → standard LimitOffset
        pagination kicks in. Response is `{count, next, previous, results}`.

    Set ``max_limit`` to keep callers from accidentally requesting the full
    table — page size grows with what you pass, but caps at this number.
    """

    default_limit = None  # ← critical: when None, DRF skips pagination
    max_limit = 1000

    def paginate_queryset(
        self, queryset, request: Request, view=None
    ) -> list[Any] | None:
        # If the caller didn't opt in (no `limit` AND no `offset`), bypass.
        # DRF's default would still paginate with `default_limit`, but ours
        # is None so this is purely defensive in case someone changes it.
        if (
            self.limit_query_param not in request.query_params
            and self.offset_query_param not in request.query_params
        ):
            return None
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        # The default response is a plain list (no envelope) because we opt out
        # of pagination unless `?limit=` is explicit. Tell drf-spectacular to
        # generate the array shape so the orval client keeps typing list
        # endpoints as `T[]`. Paginated callers (with `?limit=`) still get the
        # envelope at runtime — they just won't see it in the schema.
        return schema
