from rest_framework import serializers

from ..models import (
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
)
from .serializers_mixin import NameFieldMixin


class TheoreticalHarvestSerializer(NameFieldMixin, serializers.ModelSerializer):
    NAME_FIELDS = ["share_article_name"]

    class Meta:
        model = TheoreticalHarvest
        fields = "__all__"


class TheoreticalCleanAmountSerializer(NameFieldMixin, serializers.ModelSerializer):
    NAME_FIELDS = ["share_article_name"]

    class Meta:
        model = TheoreticalCleanAmount
        fields = "__all__"


class TheoreticalPurchaseSerializer(NameFieldMixin, serializers.ModelSerializer):
    NAME_FIELDS = ["share_article_name"]

    class Meta:
        model = TheoreticalPurchase
        fields = "__all__"


class TheoreticalWashAmountSerializer(NameFieldMixin, serializers.ModelSerializer):
    NAME_FIELDS = ["share_article_name"]

    class Meta:
        model = TheoreticalWashAmount
        fields = "__all__"


class StockComparisonSerializer(serializers.Serializer):
    """Single row in the theoretical-vs-actual stock comparison view."""

    id = serializers.CharField(help_text="Composite ID")
    share_article = serializers.CharField()
    share_article_name = serializers.CharField()
    unit = serializers.CharField()
    size = serializers.CharField()
    storage_id = serializers.CharField(allow_null=True)
    theoretical_current_stock = serializers.FloatField(allow_null=True)
    amount = serializers.FloatField(
        allow_null=True, help_text="Absolute counted value (or null if not yet counted)"
    )
    is_finalized = serializers.BooleanField(allow_null=True)
    washed = serializers.BooleanField(allow_null=True)
    cleaned = serializers.BooleanField(allow_null=True)
    for_shares = serializers.BooleanField(allow_null=True)
    for_resellers = serializers.BooleanField(allow_null=True)
    for_markets = serializers.BooleanField(allow_null=True)
    note = serializers.CharField(allow_null=True, allow_blank=True, required=False)


class InventoryEntrySerializer(serializers.Serializer):
    """Response serializer for PATCH on an INVENTORY movement."""

    id = serializers.CharField(help_text="Composite ID")
    share_article = serializers.CharField()
    share_article_name = serializers.CharField()
    unit = serializers.CharField()
    size = serializers.CharField()
    storage_id = serializers.CharField(allow_null=True)
    amount = serializers.FloatField(allow_null=True, help_text="Absolute counted value")
    for_shares = serializers.BooleanField()
    for_resellers = serializers.BooleanField()
    for_markets = serializers.BooleanField()
    washed = serializers.BooleanField()
    cleaned = serializers.BooleanField()
    note = serializers.CharField(allow_null=True)


class StorageLoggingEntrySerializer(serializers.Serializer):
    """
    Unified serializer for all movement entries in the stock ledger,
    including INVENTORY movements (physical stock counts).

    Fields that are null indicate they're not applicable for that entry type:
    - Non-INVENTORY movements: washed, cleaned, for_* fields are None
    - INVENTORY movements: cultivation_origin is None
    """

    id = serializers.CharField(help_text="Entry ID (mv_* for Movement)")
    date = serializers.DateTimeField()
    type = serializers.CharField(
        help_text="INVENTORY, HARVEST, SHARECONTENT, ORDERCONTENT, etc."
    )
    share_article = serializers.CharField()
    share_article_name = serializers.CharField()
    amount = serializers.FloatField(allow_null=True)
    unit = serializers.CharField()
    size = serializers.CharField()

    # INVENTORY-specific fields
    year = serializers.IntegerField(allow_null=True, required=False)
    delivery_week = serializers.IntegerField(allow_null=True, required=False)
    day_number = serializers.IntegerField(allow_null=True, required=False)
    washed = serializers.BooleanField(allow_null=True, required=False)
    cleaned = serializers.BooleanField(allow_null=True, required=False)
    for_shares = serializers.BooleanField(allow_null=True, required=False)
    for_resellers = serializers.BooleanField(allow_null=True, required=False)
    for_markets = serializers.BooleanField(allow_null=True, required=False)
    is_finalized = serializers.BooleanField(allow_null=True, required=False)

    # Movement-specific fields
    cultivation_origin = serializers.CharField(allow_null=True, required=False)

    # Common fields
    note = serializers.CharField(allow_null=True, required=False)
    storage_name = serializers.CharField()
    running_balance = serializers.FloatField(allow_null=True, required=False)


class MemberGrowthStatisticSerializer(serializers.Serializer):
    """Serializer for member growth statistics."""

    period = serializers.DateField(help_text="Period date (start of month/week/year)")
    new_members = serializers.IntegerField(
        help_text="Number of new members in this period"
    )
    total_members = serializers.IntegerField(
        help_text="Cumulative total members up to this period"
    )
