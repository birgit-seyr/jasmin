"""Build ``OpenApiParameter`` objects FROM a query-param catalogue.

The catalogue (``{name: ParamSpec}``, see :mod:`apps.shared.query_params`) is
the single source of truth for what a query parameter *is* — its kind, its
bounds, its allowed values. Runtime validation already reads it via
``validate_query_params``. This module makes the OpenAPI schema read it too,
so the documented type and the enforced type cannot drift apart.

Without this bridge each endpoint re-declares the parameter inline::

    OpenApiParameter(name="is_active", type=bool, description="...")

which silently diverges from the catalogue the validator actually enforces
(a param catalogued as ``bool`` but documented as ``str``, an ``enum`` that
gained a value in the catalogue but not in the docs, and so on).

Each app binds this to its own catalogue with a thin wrapper — see
``apps/commissioning/schemas.py`` — so an app never has to reach into another
app's catalogue.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from apps.shared.query_params import ParamSpec

#: ``ParamSpec.kind`` -> the OpenAPI type drf-spectacular should document.
CATALOGUE_OPENAPI_TYPE = {
    "int": OpenApiTypes.INT,
    "bool": OpenApiTypes.BOOL,
    "str": OpenApiTypes.STR,
    "choice": OpenApiTypes.STR,
    "date": OpenApiTypes.DATE,
}


def catalogue_parameter(
    name: str,
    catalogue: dict[str, ParamSpec],
    *,
    description: str = "",
    required: bool = False,
    **overrides: Any,
) -> OpenApiParameter:
    """Return an ``OpenApiParameter`` derived from ``catalogue[name]``.

    Type, ``enum`` (for ``choice`` params) and ``default`` come from the
    catalogue entry, so they cannot drift from what the validator enforces.
    ``description`` and ``required`` are per-endpoint and passed in; anything
    in ``overrides`` wins over the derived values for genuine special cases.

    Raises ``KeyError`` with a pointed message when the parameter is not
    catalogued — add it to the catalogue rather than declaring it inline.
    """
    try:
        spec = catalogue[name]
    except KeyError:
        raise KeyError(
            f"Query parameter {name!r} is not in the catalogue. Add a ParamSpec "
            "for it instead of declaring an inline OpenApiParameter, so the "
            "documented type matches the validated one."
        ) from None

    kwargs: dict[str, Any] = {
        "name": name,
        "type": CATALOGUE_OPENAPI_TYPE[spec.kind],
        "location": OpenApiParameter.QUERY,
        "required": required,
        "description": description,
    }
    if spec.kind == "choice" and spec.choices:
        kwargs["enum"] = list(spec.choices)
    if spec.default is not None:
        kwargs["default"] = spec.default
    kwargs.update(overrides)
    return OpenApiParameter(**kwargs)
