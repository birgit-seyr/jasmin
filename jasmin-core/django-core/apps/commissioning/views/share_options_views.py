from __future__ import annotations

from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsStaff

from ..models.choices_text import ShareOptions
from ..models.shares import ShareTypeVariation


@extend_schema(
    summary="List all share options",
    description="Return all available share options as a list of {value, label} objects.",
    responses=inline_serializer(
        name="ShareOptionItem",
        fields={
            "value": drf_serializers.CharField(),
            "label": drf_serializers.CharField(),
        },
        many=True,
    ),
)
@api_view(["GET"])
@permission_classes([IsStaff])
def share_options_list(request: Request) -> Response:
    """Return all available share options as a list of {value, label} objects."""
    return Response(
        [{"value": value, "label": label} for value, label in ShareOptions.choices]
    )


@extend_schema(
    summary="List active share options",
    description=(
        "Return which share options have active share type variations. "
        "Each key is a share option value mapped to a boolean. "
        "Includes a derived 'fruit_and_veg_shares_are_separate' flag."
    ),
    responses=inline_serializer(
        name="ActiveShareOptions",
        # Generated from the enum so new ShareOptions can't drift out of
        # the schema — the view emits one boolean per option value.
        fields={
            **{value: drf_serializers.BooleanField() for value in ShareOptions.values},
            "fruit_and_veg_shares_are_separate": drf_serializers.BooleanField(),
        },
    ),
)
@api_view(["GET"])
@permission_classes([IsStaff])
def active_share_options_list(request: Request) -> Response:
    """Return which share options have active share type variations."""
    today = timezone.localdate()
    active_variations = ShareTypeVariation.current.active_at_date(today)
    active_options: set[str] = set(
        active_variations.values_list("share_type__share_option", flat=True)
    )

    result: dict[str, bool] = {
        value: value in active_options for value, label in ShareOptions.choices
    }

    # True if both HARVEST_SHARE and HARVEST_SHARE_FRUIT have active variations
    result["fruit_and_veg_shares_are_separate"] = result.get(
        "HARVEST_SHARE", False
    ) and result.get("HARVEST_SHARE_FRUIT", False)

    return Response(result)
