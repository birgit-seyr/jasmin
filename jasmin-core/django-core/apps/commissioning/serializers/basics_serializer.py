from django.utils import timezone
from rest_framework import serializers

from ..models import (
    Crate,
    CrateNetPrice,
    DefaultShareArticleInShare,
    Season,
    ShareArticle,
    ShareArticleNetPrice,
    Storage,
)
from ..models.choices import ShareOptions
from ..utils.deletion_utils import parent_in_use
from .serializers_mixin import DeletableMixin, NameFieldMixin


class SeasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Season
        fields = "__all__"


class StorageSerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = Storage
        fields = "__all__"


class ShareArticleSerializer(DeletableMixin, serializers.ModelSerializer):
    share_option_list = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )

    # The ``net_price_for_*`` and ``tax_rate`` fields are NOT model columns —
    # they are pulled from the active ``ShareArticleNetPrice`` row by the
    # ``?get_price_info=true`` annotation in ``ShareArticleViewSet.get_queryset``
    # (``get_price_annotations``). Without that query param the annotation never
    # runs, so the keys are absent from the response — hence
    # ``required=False, allow_null=True``.
    net_price_for_boxes_kg = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_boxes_pieces = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_boxes_bunch = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_kg_1 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_kg_2 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_kg_3 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_kg_4 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_pieces_1 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_pieces_2 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_pieces_3 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_pieces_4 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_bunch_1 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_bunch_2 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_bunch_3 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    net_price_for_orders_bunch_4 = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, required=False, allow_null=True
    )

    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True, required=False, allow_null=True
    )

    # Only annotated under ``?is_data_list=true`` (the F() lookups in
    # ``get_queryset``); absent otherwise.
    default_crate_harvest_name = serializers.CharField(
        read_only=True, required=False, allow_null=True
    )
    default_crate_reseller_name = serializers.CharField(
        read_only=True, required=False, allow_null=True
    )

    # adding the share_type fields dynamically
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Dynamically add one boolean field per share option (lowercased value).
        # These are only annotated under ``?is_data_list=true`` (the
        # ``get_share_options_annotation`` Case/When in the viewset), so they are
        # ``required=False`` — absent from the response otherwise.
        for value, _label in ShareOptions.choices:
            lowercase_field_name = value.lower()
            self.fields[lowercase_field_name] = serializers.BooleanField(
                read_only=True, required=False
            )

    class Meta:
        model = ShareArticle
        fields = "__all__"


class ShareArticleNetPriceSerializer(
    DeletableMixin, NameFieldMixin, serializers.ModelSerializer
):
    # share_article_name (auto source share_article.name) via NameFieldMixin.
    NAME_FIELDS = ["share_article_name"]

    class Meta:
        model = ShareArticleNetPrice
        fields = "__all__"

    def get_can_be_deleted(self, obj: ShareArticleNetPrice) -> bool:
        # Nothing FK-references the price row, so the base check is normally
        # True. An ACTIVE price becomes non-deletable once the priced
        # ShareArticle is itself in use anywhere (offers, member shares, reseller
        # orders, deliveries, stock, forecasts). Future and past prices stay
        # freely deletable. Cached per article so a price list stays O(parents).
        if not super().get_can_be_deleted(obj):
            return False
        today = timezone.localdate()
        is_active = obj.valid_from <= today and (
            obj.valid_until is None or obj.valid_until >= today
        )
        if not is_active:
            return True
        cache = self.context.setdefault("_share_article_in_use", {})
        article_id = obj.share_article_id
        if article_id not in cache:
            cache[article_id] = parent_in_use(obj.share_article)
        return not cache[article_id]


class CrateSerializer(DeletableMixin, serializers.ModelSerializer):
    # ``price`` and ``tax_rate`` are NOT model columns — they are pulled from
    # the active ``CrateNetPrice`` row by the ``?get_price_info=true`` annotation
    # in ``CrateViewSet.get_queryset`` (``get_current_price_annotations``).
    # Without that query param the keys are absent — hence
    # ``required=False, allow_null=True``.
    price = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True, required=False, allow_null=True
    )
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Crate
        fields = "__all__"


class CrateNetPriceSerializer(DeletableMixin, serializers.ModelSerializer):
    name = serializers.CharField(source="crate.name", read_only=True)
    short_name = serializers.CharField(source="crate.short_name", read_only=True)

    class Meta:
        model = CrateNetPrice
        fields = "__all__"

    def get_can_be_deleted(self, obj: CrateNetPrice) -> bool:
        # See ShareArticleNetPriceSerializer: an ACTIVE price becomes
        # non-deletable once the priced Crate is itself in use (offers, crate
        # orders, deliveries, a variation's packing crate). Future and past
        # prices stay deletable. Cached per crate to avoid an N+1 over history.
        if not super().get_can_be_deleted(obj):
            return False
        today = timezone.localdate()
        is_active = obj.valid_from <= today and (
            obj.valid_until is None or obj.valid_until >= today
        )
        if not is_active:
            return True
        cache = self.context.setdefault("_crate_in_use", {})
        crate_id = obj.crate_id
        if crate_id not in cache:
            cache[crate_id] = parent_in_use(obj.crate)
        return not cache[crate_id]


class DefaultShareArticleInShareSerializer(NameFieldMixin, serializers.ModelSerializer):
    """Default quantity of a ``ShareArticle`` inside a ``ShareTypeVariation``.

    Used by the ``DefaultShareArticlesInShare`` configuration page (one cell
    per (share_article, share_type_variation) pair). The ``unit`` is optional
    and falls back to the share article's ``default_movement_unit``.
    """

    NAME_FIELDS = ["share_article_name"]
    share_type_variation_size = serializers.CharField(
        source="share_type_variation.size", read_only=True
    )
    share_type_id = serializers.CharField(
        source="share_type_variation.share_type_id", read_only=True
    )

    class Meta:
        model = DefaultShareArticleInShare
        fields = "__all__"


class DefaultShareArticleInShareBulkEntrySerializer(serializers.Serializer):
    """One cell in the ``bulk_upsert`` payload."""

    share_type_variation = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=7, decimal_places=3, allow_null=True)
    unit = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class DefaultShareArticleInShareBulkUpsertRequestSerializer(serializers.Serializer):
    """Payload accepted by ``DefaultShareArticleInShareViewSet.bulk_upsert``."""

    share_article = serializers.CharField()
    # API-5: bound the item list so one authorized request can't stream an
    # unbounded number of update_or_create/delete ops through the single
    # atomic loop (soft DoS). Well above any realistic per-article variation set.
    entries = DefaultShareArticleInShareBulkEntrySerializer(many=True, max_length=2000)
