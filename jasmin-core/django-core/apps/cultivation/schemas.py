from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter

"""
OpenAPI schema definitions for the commissioning app.
"""


# YEAR
def get_year_parameter(**overrides):
    """
    Get year parameter with optional overrides.

    Usage:
        get_year_parameter()  # Default
        get_year_parameter(required=False)  # Optional year
    """
    return OpenApiParameter(
        name="year",
        type=OpenApiTypes.INT,
        required=True,
        description="Year (YYYY format)",
        **overrides  # Allow customization
    )


# DELIVERY WEEK
def get_delivery_week_parameter(**overrides):
    """
    Get delivery week parameter with optional overrides.

    Usage:
        get_delivery_week_parameter()
        get_delivery_week_parameter(description="Custom description")
    """
    return OpenApiParameter(
        name="delivery_week",
        type=OpenApiTypes.INT,
        required=True,
        description="ISO week number (1-53)",
        examples=[
            OpenApiExample("Week 1", value=1),
            OpenApiExample("Week 26", value=26),
            OpenApiExample("Week 52", value=52),
        ],
        **overrides
    )
