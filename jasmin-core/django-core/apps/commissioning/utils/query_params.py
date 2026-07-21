"""Central catalogue of the commissioning API's query parameters.

Every query parameter the API accepts is declared ONCE in ``PARAM_CATALOGUE``
with its type and bounds. Endpoints then validate by *naming* the params they
read — ``validate_query_params(request, required=[...], optional=[...])`` —
instead of re-deriving coercion/ranges at each call site.

The generic machinery (``ParamSpec``, coercion, the catalogue-driven
validator) lives in :mod:`apps.shared.query_params`; this module binds it to
the commissioning catalogue. See the shared module's docstring for the
per-kind validation depth (``int``/``date``/``bool``/``choice``/``str``).

This catalogue is the front door for QUERY params. ``validate_and_parse_int_params``
(in :mod:`.validation_utils`) is kept only for POST-body int parsing (its
``source="data"`` mode), which the catalogue does not cover.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

from apps.shared.query_params import (
    ParamSpec,
)
from apps.shared.query_params import (
    validate_query_params as _validate_against_catalogue,
)

from ..models.choices import ShareOptions

# Single source of truth for the documentation model discriminator — the
# ``documentation_viewsets`` VALID_MODELS derives from this (was a hand-kept
# duplicate). Public so the viewset imports it instead of re-listing values.
DOCUMENTATION_MODELS = ("harvest", "purchase", "washamount", "cleanamount")


# Strict bool params (absent → ``None``, i.e. "not filtered").
_BOOL_PARAMS = (
    "is_active",
    "is_packed_bulk",
    "is_trial",
    "manual",
    "joker",
    "for_tours",
    "for_stations",
    "physical",
    "virtual",
    "include_next_week",
    "include_extra",
    "include_future",
    "is_preparation_lists",
    "current",
    "future",
    "force",
    "only_with_subscriptions",
    "on_waiting_list",
    "need_info_on_tours",
    "exclude_trial_members",
    "get_price_info",
    "get_delivery_stations",
    "summed",
    "undo",
    "is_supplier",
    "is_sold_to_resellers",
    "is_seller",
    "is_reseller",
    "is_purchased",
    "is_harvest_share_article",
    "is_extra",
    "is_donation_recipient",
    "is_data_list",
    "is_active_supplier",
    "is_active_seller",
    "is_active_reseller",
    "is_active_donation_recipient",
    "physical_share_type_variations",
)

# FK-id references + free strings: STR ids (no coercion, no 500 risk).
# Catalogued for completeness; tighten to a ``choice``/existence check at the
# endpoint only where a 404 on an unknown value is genuinely wanted.
_STR_PARAMS = (
    "share_type",
    "share_type_variation",
    "share_type_variation_ids",
    "delivery_station",
    "delivery_station_day",
    "delivery_day",
    "member",
    "share_article",
    "reseller",
    "storage",
    "offer_group",
    "invoice_id",
    "delivery_note_id",
    "order_id",
    "seller",
    "locale",
    "status",  # e.g. import-batch status — free string filter
    "virtual_variation",
    "physical_variation",
    "crate",
    "crate_type",  # FK to Crate — a STR id, not an enum
    "source",  # uppercased + looked up in a model map at the call site
    "period",
    "kind",  # read raw in more than one context — keep as passthrough
    "delete_context",
)

PARAM_CATALOGUE: dict[str, ParamSpec] = {
    # ---- week scope (int + range) ----
    # ``year`` spans delivery years AND entry/birth-year filters (statistics),
    # hence the wide lower bound rather than 2000.
    "year": ParamSpec("int", min_value=1900, max_value=2100),
    "delivery_week": ParamSpec("int", min_value=1, max_value=53),
    "day_number": ParamSpec("int", min_value=0, max_value=6),
    "num_weeks": ParamSpec("int", min_value=1, max_value=104, default=52),
    "years_back": ParamSpec("int", min_value=0, max_value=50, default=2),
    "tour": ParamSpec("int", min_value=0),  # tour number — int()-coerced at call sites
    "packing_station": ParamSpec("int", min_value=0),  # int()-coerced at call sites
    # ---- dates (YYYY-MM-DD) ----
    "active_at_date": ParamSpec("date"),
    "active_at_date_or_future": ParamSpec("date"),
    "start_date": ParamSpec("date"),
    "end_date": ParamSpec("date"),
    "date_from": ParamSpec("date"),
    "date_to": ParamSpec("date"),
    "price_date": ParamSpec("date"),
    # ---- enums ----
    "share_option": ParamSpec("choice", choices=tuple(ShareOptions.values)),
    "model": ParamSpec("choice", choices=DOCUMENTATION_MODELS),
    # ---- booleans (strict) + the one with a False default ----
    "is_past": ParamSpec("bool", default=False),
    **{name: ParamSpec("bool") for name in _BOOL_PARAMS},
    # ---- FK-id references / free strings (passthrough) ----
    **{name: ParamSpec("str") for name in _STR_PARAMS},
}


def validate_query_params(
    request: Request,
    *,
    required: list[str] | tuple[str, ...] = (),
    optional: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate the named query params against the central catalogue.

    Returns ``{name: parsed_value}``. A required-but-missing param → 400; a
    present value that fails its catalogue spec → 400 (``InvalidQueryParam``).
    Absent optional params return their catalogue ``default`` (usually ``None``).
    Naming a param that isn't catalogued raises ``KeyError`` (programmer
    error — add it to ``PARAM_CATALOGUE`` rather than reading it raw).
    """
    return _validate_against_catalogue(
        request, PARAM_CATALOGUE, required=required, optional=optional
    )
