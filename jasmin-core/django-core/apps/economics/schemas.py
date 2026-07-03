from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter


# YEAR
def get_year_parameter(**overrides):
    """
    Get year parameter with optional overrides.

    Usage:
        get_year_parameter()  # Default
        get_year_parameter(required=False)  # Optional year
    """
    required = overrides.pop("required", True)

    return OpenApiParameter(
        name="year",
        type=OpenApiTypes.INT,
        required=required,
        description="Year (YYYY format)",
        examples=[
            OpenApiExample("2024", value=2024),
            OpenApiExample("2025", value=2025),
        ],
        **overrides  # Allow customization
    )


# MONTH
def get_month_parameter(**overrides):
    """
    Get month parameter with optional overrides.

    Usage:
        get_month_parameter()
        get_month_parameter(required=False)
    """

    required = overrides.pop("required", True)

    return OpenApiParameter(
        name="month",
        type=OpenApiTypes.INT,
        required=required,
        description="Month (1-12)",
        examples=[
            OpenApiExample("January", value=1),
            OpenApiExample("June", value=6),
            OpenApiExample("December", value=12),
        ],
        **overrides
    )
