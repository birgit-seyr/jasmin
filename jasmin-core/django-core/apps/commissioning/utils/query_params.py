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
    ISO_WEEK_PARAM,
    YEAR_PARAM,
    ParamSpec,
)
from apps.shared.query_params import (
    validate_query_params as _validate_against_catalogue,
)

from ..models.choices import ConsentKind, ShareOptions
from ..models.imports import ExternalCodeMapping, ShareImportBatch

# Single source of truth for the documentation model discriminator. Public so
# ``documentation_viewsets`` imports it instead of re-listing values.
DOCUMENTATION_MODELS = ("harvest", "purchase", "washamount", "cleanamount")

# The sources the documentation overview aggregates over. ``documentation_views``
# keys its source-to-model map by these, so both ends stay one list.
DOCUMENTATION_SOURCES = ("HARVEST", "PURCHASE", "WASTE")

# The groupings ``calculate_member_growth_statistics`` can truncate by — one
# per truncation it knows how to apply.
MEMBER_GROWTH_PERIODS = ("month", "week", "year")


# Strict bool params (absent → ``None``, i.e. "not filtered").
_BOOL_PARAMS = (
    "is_active",
    "is_packed_bulk",
    "is_trial",
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
    "has_orders_without_invoice",
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
    "virtual_variation",
    "physical_variation",
    "crate",
    "crate_type",  # FK to Crate — a STR id, not an enum
)

PARAM_CATALOGUE: dict[str, ParamSpec] = {
    # ---- week scope (int + range) ----
    # ``year`` and the ISO week come from the shared specs, so every app's
    # catalogue accepts the same values.
    "year": YEAR_PARAM,
    "delivery_week": ISO_WEEK_PARAM,
    "day_number": ParamSpec("int", min_value=0, max_value=6),
    "num_weeks": ParamSpec("int", min_value=1, max_value=104, default=52),
    "years_back": ParamSpec("int", min_value=0, max_value=50, default=2),
    # Tour number and packing-station number: parsed here, so every consumer
    # downstream takes the int this yields rather than re-coercing a string.
    "tour": ParamSpec("int", min_value=0),
    "packing_station": ParamSpec("int", min_value=0),
    # ---- dates (YYYY-MM-DD) ----
    "active_at_date": ParamSpec("date"),
    "active_at_date_or_future": ParamSpec("date"),
    "start_date": ParamSpec("date"),
    "end_date": ParamSpec("date"),
    "date_from": ParamSpec("date"),
    "date_to": ParamSpec("date"),
    "price_date": ParamSpec("date"),
    # ---- enums ----
    # Case-insensitive to match the POST/PATCH body, which upper-cases the
    # value before validating it: one spelling rule for the same enum wherever
    # it is sent, and the catalogue's own spelling comes back either way.
    "share_option": ParamSpec(
        "choice", choices=tuple(ShareOptions.values), case_insensitive=True
    ),
    "model": ParamSpec("choice", choices=DOCUMENTATION_MODELS),
    # Which of a reseller row's two roles a DELETE means to drop. The service
    # branches on exactly these two values and does nothing for anything else,
    # so an unlisted value must be refused rather than silently no-op.
    "delete_context": ParamSpec("choice", choices=("sellers", "resellers")),
    # Enums sent under a generic wire name: the catalogue key says whose enum
    # it is, ``wire_name`` is what the client sends. Two endpoints can then
    # each close their own value set instead of sharing a free string.
    "consent_kind": ParamSpec(
        "choice", choices=tuple(ConsentKind.values), wire_name="kind"
    ),
    "mapping_kind": ParamSpec(
        "choice",
        choices=tuple(value for value, _label in ExternalCodeMapping.KIND_CHOICES),
        wire_name="kind",
    ),
    "import_batch_status": ParamSpec(
        "choice",
        choices=tuple(value for value, _label in ShareImportBatch.STATUS_CHOICES),
        wire_name="status",
    ),
    # Callers have always been free to send either case here, so the match
    # stays case-insensitive; the default lives here rather than at the call
    # site, so an absent AND an empty value land on the same documented value.
    "source": ParamSpec(
        "choice",
        choices=DOCUMENTATION_SOURCES,
        default="HARVEST",
        case_insensitive=True,
    ),
    "period": ParamSpec("choice", choices=MEMBER_GROWTH_PERIODS, default="month"),
    # ---- booleans (strict) ----
    # Action-style flags: absent means OFF, so the default lives here instead
    # of being re-derived as ``bool(params[...])`` at each call site.
    "is_past": ParamSpec("bool", default=False),
    "force": ParamSpec("bool", default=False),
    "joker": ParamSpec("bool", default=False),
    "donation_joker": ParamSpec("bool", default=False),
    # Filter-style flags: absent means "not filtered" (``None``).
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
