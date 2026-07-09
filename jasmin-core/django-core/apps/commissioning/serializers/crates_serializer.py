from rest_framework import serializers

from ..models import CrateOrderContent
from .serializers_mixin import LinePricingFieldsMixin, NameFieldMixin


class CrateOrderContentSerializer(
    LinePricingFieldsMixin, NameFieldMixin, serializers.ModelSerializer
):
    NAME_FIELDS = ["crate_type_name"]

    class Meta:
        model = CrateOrderContent
        fields = "__all__"
        read_only_fields = ["is_finalized", "finalized_at", "finalized_by"]


class CrateOrderContentCreateRequestSerializer(serializers.Serializer):
    """Validated request body for ``CrateOrderContentViewSet.create``.

    The crate viewset forwards individual service kwargs (not a model
    instance) and the period ints land directly in ``Order`` /
    ``CrateOrderContent`` integer columns, so a non-numeric or missing value
    would otherwise surface as a bare ``ValueError`` / ``IntegrityError`` →
    HTTP 500. Coercing here turns malformed input into a clean 400. Int
    bounds mirror the query-param catalogue (year / delivery_week /
    day_number).
    """

    crate_type = serializers.CharField()
    amount = serializers.IntegerField(min_value=1)
    year = serializers.IntegerField(min_value=1900, max_value=2100)
    delivery_week = serializers.IntegerField(min_value=1, max_value=53)
    day_number = serializers.IntegerField(min_value=0, max_value=6)
    reseller = serializers.CharField()
    price_per_unit = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    rabatt = serializers.IntegerField(
        min_value=0, max_value=100, required=False, allow_null=True
    )
    note = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=500
    )


class CrateOrderContentUpdateRequestSerializer(serializers.Serializer):
    """Validated request body for ``CrateOrderContentViewSet.partial_update``.

    The crate type comes from the URL; the period (year / delivery_week /
    day_number / reseller) is required to scope the rows while the mutable
    line fields are optional (PATCH). Same rationale as the create serializer
    — keep malformed period ints off the 500 path.
    """

    year = serializers.IntegerField(min_value=1900, max_value=2100)
    delivery_week = serializers.IntegerField(min_value=1, max_value=53)
    day_number = serializers.IntegerField(min_value=0, max_value=6)
    reseller = serializers.CharField()
    amount = serializers.IntegerField(min_value=1, required=False)
    price_per_unit = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    rabatt = serializers.IntegerField(
        min_value=0, max_value=100, required=False, allow_null=True
    )
    note = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=500
    )


# NOTE: ``CrateDeliveryNoteContentSerializer`` and
# ``CrateContentInvoiceResellerSerializer`` live in ``resellers_serializer.py``
# — the diff-tracking variants (``DifferenceTrackingMixin``), matching their
# article-content siblings. They are the ones wired into the viewsets and
# re-exported from this package; a diff-less copy used to live here and silently
# shadowed them.
