"""OpenAPI schema helpers for the cultivation app.

Each helper returns an ``OpenApiParameter`` built from a defaults dict that
callers may override — merged rather than passed alongside ``**overrides``, so
``get_year_parameter(required=False)`` works as the docstrings advertise
(passing it positionally raised "got multiple values for keyword argument").
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter


# YEAR
def get_year_parameter(**overrides):
    """Year query parameter.

    Usage:
        get_year_parameter()                 # required (default)
        get_year_parameter(required=False)   # optional filter
    """
    params = {
        "name": "year",
        "type": OpenApiTypes.INT,
        "required": True,
        "description": "Year (YYYY format)",
    }
    params.update(overrides)
    return OpenApiParameter(**params)


# DELIVERY WEEK
def get_delivery_week_parameter(**overrides):
    """ISO delivery-week query parameter.

    Usage:
        get_delivery_week_parameter()
        get_delivery_week_parameter(description="Custom description")
    """
    params = {
        "name": "delivery_week",
        "type": OpenApiTypes.INT,
        "required": True,
        "description": "ISO week number (1-53)",
        "examples": [
            OpenApiExample("Week 1", value=1),
            OpenApiExample("Week 26", value=26),
            OpenApiExample("Week 52", value=52),
        ],
    }
    params.update(overrides)
    return OpenApiParameter(**params)
