from drf_spectacular.utils import OpenApiExample, OpenApiParameter

from apps.shared.openapi_params import catalogue_parameter

from .utils.query_params import PARAM_CATALOGUE

"""
OpenAPI schema definitions for the commissioning app.
"""


def catalogue_param(name, *, description="", required=False, **overrides):
    """Build an OpenApiParameter from PARAM_CATALOGUE[name] — single source of
    truth for the param's type/enum/default. ``overrides`` win (e.g. required=True).

    Thin binding of the generic helper in :mod:`apps.shared.openapi_params` to
    the commissioning catalogue."""
    return catalogue_parameter(
        name,
        PARAM_CATALOGUE,
        description=description,
        required=required,
        **overrides,
    )


# YEAR
def get_year_parameter(**overrides):
    """
    Get year parameter with optional overrides.

    Usage:
        get_year_parameter()  # Default
        get_year_parameter(required=False)  # Optional year
    """
    required = overrides.pop("required", True)

    return catalogue_param(
        "year",
        description="Year (YYYY format)",
        required=required,
        examples=[
            OpenApiExample("2024", value=2024),
            OpenApiExample("2025", value=2025),
        ],
        **overrides,
    )


# DELIVERY WEEK
def get_delivery_week_parameter(**overrides):
    """
    Get delivery week parameter with optional overrides.

    Usage:
        get_delivery_week_parameter()
        get_delivery_week_parameter(description="Custom description")
    """
    required = overrides.pop("required", True)

    return catalogue_param(
        "delivery_week",
        description="ISO week number (1-53)",
        required=required,
        examples=[
            OpenApiExample("Week 1", value=1),
            OpenApiExample("Week 26", value=26),
            OpenApiExample("Week 52", value=52),
        ],
        **overrides,
    )


# DAY NUMBER
def get_day_number_parameter(**overrides):
    """
    Get day number parameter with optional overrides.

    Usage:
        get_day_number_parameter()
        get_day_number_parameter(required=False)
    """

    required = overrides.pop("required", True)

    return catalogue_param(
        "day_number",
        description="Day of the week (0=Monday, 6=Sunday)",
        required=required,
        examples=[
            OpenApiExample("Monday", value=0),
            OpenApiExample("Wednesday", value=2),
            OpenApiExample("Sunday", value=6),
        ],
        **overrides,
    )


# DELIVERY DAY
def get_delivery_day_parameter(**overrides):
    """Get delivery_day parameter; this is a sharesdeliveryday object"""
    required = overrides.pop("required", True)

    return catalogue_param(
        "delivery_day",
        description="sharesdeliveryday ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# SHARE_OPTION_PARAMETER — defined later in this file (line ~543).
# An earlier copy lived here; Python's def re-binding silently kept the later
# one so removing this stub is a no-op behaviour-wise.


# STORAGE
def get_storage_parameter(**overrides):
    """
    Get storage parameter with default required=True.

    Usage:
        get_storage_parameter()                  # required=True (default)
        get_storage_parameter(required=False)    # required=False (override)
    """
    # Extract 'required' from overrides or use True as default
    required = overrides.pop("required", True)

    return catalogue_param(
        "storage",
        description="Storage ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# IS PAST (archive toggle)
def get_is_past_parameter(**overrides):
    """Get is_past boolean parameter for archive manager toggling."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "is_past",
        description=(
            "When true, includes archived/historical data. "
            "When false (default), only recent data is returned."
        ),
        required=required,
        **overrides,
    )


# SHARE ARTICLE
def get_share_article_parameter(**overrides):
    """
    Get share article parameter with default required=True.

    Usage:
        get_share_article_parameter()                  # required=True (default)
        get_share_article_parameter(required=False)    # required=False (override)
    """
    required = overrides.pop("required", True)

    return catalogue_param(
        "share_article",
        description="Share article ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# IS ACTIVE
def get_is_active_parameter(**overrides):
    """Get is_active boolean parameter for filtering by active status."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "is_active",
        description="Filter by active status",
        required=required,
        **overrides,
    )


# IS ACTIVE AT DATE OR FUTURE
def get_active_at_date_or_future_parameter(**overrides):
    """Get is_active_at_date_or_future boolean parameter for filtering by active status at a date or in the future."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "active_at_date_or_future",
        description="Filter for records active at a specific date or starting in the future",
        required=required,
        **overrides,
    )


# ACTIVE AT DATE
def get_active_at_date_parameter(**overrides):
    """Get active_at_date date parameter for time-bound filtering."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "active_at_date",
        description="Filter for records active at the given date (YYYY-MM-DD)",
        required=required,
        **overrides,
    )


# START / END DATE (inclusive date-range reports)
def get_start_date_parameter(**overrides):
    """Get start_date date parameter (inclusive range start, YYYY-MM-DD)."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "start_date",
        description="Inclusive range start (YYYY-MM-DD)",
        required=required,
        **overrides,
    )


def get_end_date_parameter(**overrides):
    """Get end_date date parameter (inclusive range end, YYYY-MM-DD)."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "end_date",
        description="Inclusive range end (YYYY-MM-DD)",
        required=required,
        **overrides,
    )


# DATE_FROM / DATE_TO — the required date-range pair shared by the CSV export
# endpoints. Declared as plain strings (not the catalogue's ``date`` kind):
# some consumers read the raw values straight off the query params.
EXPORT_DATE_RANGE_PARAMETERS = [
    OpenApiParameter(
        name="date_from",
        type=str,
        required=True,
        description="Start date (YYYY-MM-DD)",
    ),
    OpenApiParameter(
        name="date_to",
        type=str,
        required=True,
        description="End date (YYYY-MM-DD)",
    ),
]


# CURRENT (price validity)
def get_current_parameter(**overrides):
    """Get current boolean parameter for filtering current prices."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "current",
        description="Filter for current prices (valid_until is null)",
        required=required,
        **overrides,
    )


# GET PRICE INFO
def get_price_info_parameter(**overrides):
    """Get get_price_info boolean parameter for including price annotations."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "get_price_info",
        description="Include price information in response",
        required=required,
        **overrides,
    )


# ORDER ID
def get_order_id_parameter(**overrides):
    """Get order_id parameter."""
    required = overrides.pop("required", True)

    return catalogue_param(
        "order_id",
        description="Order ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# CRATE TYPE
def get_crate_type_parameter(**overrides):
    """Get crate_type parameter."""
    required = overrides.pop("required", True)

    return catalogue_param(
        "crate_type",
        description="Crate type ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# DELIVERY NOTE ID
def get_delivery_note_id_parameter(**overrides):
    """Get delivery_note_id parameter."""
    required = overrides.pop("required", True)

    return catalogue_param(
        "delivery_note_id",
        description="Delivery note ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# INVOICE ID
def get_invoice_id_parameter(**overrides):
    """Get invoice_id parameter."""
    required = overrides.pop("required", True)

    return catalogue_param(
        "invoice_id",
        description="Invoice ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# CRATE
def get_crate_parameter(**overrides):
    """Get crate parameter for filtering by crate."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "crate",
        description="Crate ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# RESELLER
def get_reseller_parameter(**overrides):
    """Get reseller parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "reseller",
        description="Reseller ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# OFFER GROUP
def get_offer_group_parameter(**overrides):
    """Get offer_group parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "offer_group",
        description="Offer group ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# DELIVERY STATION
def get_delivery_station_parameter(**overrides):
    """Get delivery_station parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "delivery_station",
        description="Delivery station ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# SELLER
def get_seller_parameter(**overrides):
    """Get seller parameter for filtering purchases by seller."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "seller",
        description="Seller ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# MODEL (harvest/purchase/washamount/cleanamount)
def get_model_parameter(**overrides):
    """Get model parameter for summary endpoints."""
    required = overrides.pop("required", True)

    return catalogue_param(
        "model",
        description="Data model type",
        required=required,
        **overrides,
    )


# INCLUDE NEXT WEEK
def get_include_next_week_parameter(**overrides):
    """Get include_next_week boolean parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "include_next_week",
        description="Include data from the following week",
        required=required,
        **overrides,
    )


# IS PREPARATION LISTS
def get_is_preparation_lists_parameter(**overrides):
    """Get is_preparation_lists boolean parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "is_preparation_lists",
        description="Filter by short-term storage (preparation lists)",
        required=required,
        **overrides,
    )


# TOUR
def get_tour_parameter(**overrides):
    """Get tour parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "tour",
        description="Tour number",
        required=required,
        **overrides,
    )


# PACKING STATION
def get_packing_station_parameter(**overrides):
    """Get packing_station parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "packing_station",
        description="Packing station number",
        required=required,
        **overrides,
    )


# SHARE TYPE
def get_share_type_parameter(**overrides):
    """Get share_type parameter."""
    required = overrides.pop("required", True)

    return catalogue_param(
        "share_type",
        description="Share type ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# MEMBER
def get_member_parameter(**overrides):
    """Get member parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "member",
        description="Member ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


def get_is_trial_parameter(**overrides):
    """Get is_trial boolean parameter for filtering by trial status."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "is_trial",
        description="Filter by trial status (true for trial, false for non-trial)",
        required=required,
        **overrides,
    )


# SHARE TYPE VARIATION
def get_share_type_variation_parameter(**overrides):
    """Get share_type_variation parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "share_type_variation",
        description="Share type variation ID (Jasmin ID format)",
        required=required,
        **overrides,
    )


# SHARE OPTION
def get_share_option_parameter(**overrides):
    """Get share_option parameter."""
    required = overrides.pop("required", False)

    return catalogue_param(
        "share_option",
        description="Share option (e.g. GEMUESE, OBST)",
        required=required,
        **overrides,
    )
