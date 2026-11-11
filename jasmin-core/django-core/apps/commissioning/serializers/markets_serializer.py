from typing import Any

from rest_framework import serializers

from ..models import (
    MarketArticle,
    MarketPrice,
    MarketProductGroup,
    ScaleTaxCode,
)
from ..models.choices import UnitOptions, VegetableSizeOptions
from ..services.market_prices import previous_week_price
from ..services.market_scale_export import default_scale_tax_code
from .bulk_serializer import BulkIdsRequestSerializer
from .serializers_mixin import DeletableMixin, ReadOnlyOnUpdateMixin


class MarketProductGroupSerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = MarketProductGroup
        fields = "__all__"


class MarketArticleSerializer(DeletableMixin, serializers.ModelSerializer):
    """A PLU. Saved without ``scale_tax_code`` (left out on create, or null),
    it sells under the scale's code for its share article's VAT rate, or the
    farm's default rate."""

    share_article_name = serializers.CharField(
        source="share_article.name", read_only=True, allow_null=True, default=None
    )
    product_group_name = serializers.CharField(
        source="product_group.name", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = MarketArticle
        fields = "__all__"
        extra_kwargs = {"scale_tax_code": {"required": False, "allow_null": True}}

    def create(self, validated_data: dict[str, Any]) -> MarketArticle:
        if validated_data.get("scale_tax_code") is None:
            validated_data["scale_tax_code"] = default_scale_tax_code(
                MarketArticle(**validated_data)
            )
        return super().create(validated_data)

    def update(
        self, instance: MarketArticle, validated_data: dict[str, Any]
    ) -> MarketArticle:
        if (
            "scale_tax_code" in validated_data
            and validated_data["scale_tax_code"] is None
        ):
            share_article = validated_data.get("share_article", instance.share_article)
            validated_data["scale_tax_code"] = default_scale_tax_code(
                MarketArticle(share_article=share_article)
            )
        return super().update(instance, validated_data)


class MarketPriceSerializer(ReadOnlyOnUpdateMixin, serializers.ModelSerializer):
    """A PLU's gross price in one week, with the PLU's own fields and its price
    the week before. ``is_changed`` is true when the price or the origin differs
    from that week's, or the PLU had no price then."""

    # A price moves to another week or PLU by copying, not by an edit.
    READ_ONLY_ON_UPDATE = ("market_article", "year", "delivery_week")

    plu_number = serializers.IntegerField(
        source="market_article.plu_number", read_only=True
    )
    name = serializers.CharField(source="market_article.name", read_only=True)
    unit = serializers.ChoiceField(
        choices=UnitOptions.choices, source="market_article.unit", read_only=True
    )
    size = serializers.ChoiceField(
        choices=VegetableSizeOptions.choices,
        source="market_article.size",
        read_only=True,
    )
    sort = serializers.CharField(
        source="market_article.sort", read_only=True, allow_null=True
    )
    product_group_number = serializers.IntegerField(
        source="market_article.product_group.number",
        read_only=True,
        allow_null=True,
        default=None,
    )
    product_group_name = serializers.CharField(
        source="market_article.product_group.name",
        read_only=True,
        allow_null=True,
        default=None,
    )
    previous_gross_price = serializers.SerializerMethodField()
    previous_origin = serializers.SerializerMethodField()
    is_changed = serializers.SerializerMethodField()

    class Meta:
        model = MarketPrice
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._previous_by_price: dict[str, MarketPrice | None] = {}

    def _previous(self, obj: MarketPrice) -> MarketPrice | None:
        # A list hands in the whole previous week, read once; a single price
        # looks its own up once for the three fields that read it.
        previous_prices = self.context.get("previous_prices")
        if previous_prices is not None:
            return previous_prices.get(obj.market_article_id)
        if obj.pk not in self._previous_by_price:
            self._previous_by_price[obj.pk] = previous_week_price(obj)
        return self._previous_by_price[obj.pk]

    def get_previous_gross_price(self, obj: MarketPrice) -> str | None:
        previous = self._previous(obj)
        return str(previous.gross_price) if previous else None

    def get_previous_origin(self, obj: MarketPrice) -> str | None:
        previous = self._previous(obj)
        return previous.origin if previous else None

    def get_is_changed(self, obj: MarketPrice) -> bool:
        previous = self._previous(obj)
        return (
            previous is None
            or previous.gross_price != obj.gross_price
            or (previous.origin or "") != (obj.origin or "")
        )


class ScaleTaxCodeSerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = ScaleTaxCode
        fields = "__all__"


class MarketPriceBulkActiveRequestSerializer(BulkIdsRequestSerializer):
    """The prices to put on sale (``is_active`` true) or take off it."""

    is_active = serializers.BooleanField()


class MarketPriceCopyResultSerializer(serializers.Serializer):
    total_requested = serializers.IntegerField()
    total_copied = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
