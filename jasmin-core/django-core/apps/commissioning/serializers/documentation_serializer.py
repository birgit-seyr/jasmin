import logging

from rest_framework import serializers

from ..errors import OfferGroupNotFound, ShareTypeVariationNotFound
from ..models import (
    Forecast,
    Harvest,
    OfferGroup,
    Plot,
    Purchase,
    ShareTypeVariation,
    Waste,
)
from .serializers_mixin import DeletableMixin, NameFieldMixin, StorageFieldsMixin

logger = logging.getLogger(__name__)


class PlotSerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = Plot
        fields = "__all__"


class ForecastSerializer(NameFieldMixin, DeletableMixin, serializers.ModelSerializer):
    NAME_FIELDS = ["share_article_name", "plot_name"]

    class Meta:
        model = Forecast
        fields = "__all__"

    def to_representation(self, instance):
        """
        Handle both model instances and dictionary data from the service
        """
        if isinstance(instance, dict):
            # Convert dictionary back to model instance
            if "id" in instance:
                try:
                    # Get the actual model instance
                    model_instance = self.Meta.model.objects.get(id=instance["id"])
                    # Use the model instance for serialization
                    instance = model_instance
                except self.Meta.model.DoesNotExist:
                    # Fallback: create a temporary instance with the dict data
                    # This won't work for SerializerMethodFields that need database access
                    return instance
            else:
                # No ID available, return dict as-is (SerializerMethodFields won't work)
                return instance

        # Now we always have a model instance
        data = super().to_representation(instance)

        # Add variation fields. The AttributeError catch handles the
        # dict-instance path above where ``instance`` lacks the related
        # manager — that's expected. Anything else (e.g. a real schema
        # regression) should leave a breadcrumb instead of silently
        # dropping variation_X keys from the response.
        try:
            for variation_rel in instance.forecastsharetypevariation_set.all():
                data[f"variation_{variation_rel.share_type_variation.id}"] = True
        except AttributeError as exc:
            logger.debug(
                "forecast.variation_fields.skipped instance=%r error=%s",
                type(instance).__name__,
                exc,
            )

        # Add offer group fields — same rationale as variation fields above.
        try:
            for offer_group_rel in instance.forecastoffergroup_set.all():
                data[f"offer_group_{offer_group_rel.offer_group.id}"] = True
        except AttributeError as exc:
            logger.debug(
                "forecast.offer_group_fields.skipped instance=%r error=%s",
                type(instance).__name__,
                exc,
            )

        return data

    def to_internal_value(self, data):
        """
        Handle incoming data with variation_ and offer_group_ fields
        """
        # Separate standard fields from dynamic fields
        standard_data = {}
        dynamic_data = {}

        for key, value in data.items():
            if key.startswith(("variation_", "offer_group_")):
                # Handle undefined/null values - treat as False
                if value is None or value == "undefined":
                    dynamic_data[key] = False
                elif isinstance(value, bool):
                    dynamic_data[key] = value
                elif isinstance(value, str):
                    dynamic_data[key] = value.lower() in ("true", "1", "yes", "on")
                else:
                    dynamic_data[key] = bool(value)
            else:
                standard_data[key] = value

        # Validate standard fields
        validated_data = super().to_internal_value(standard_data)

        # Add dynamic fields
        validated_data.update(dynamic_data)

        return validated_data

    def validate(self, data):
        """
        Custom validation for variation and offer group fields
        """
        data = super().validate(data)

        # Validate variation + offer-group ids unconditionally — a bogus id
        # must be rejected even when its flag is falsey (deselected).
        for key in data:
            if key.startswith("variation_"):
                variation_id = key.replace("variation_", "")
                if not ShareTypeVariation.objects.filter(id=variation_id).exists():
                    # Typed 404 with a stable code (matches the service-layer
                    # check + the sibling OfferGroupNotFound), instead of a
                    # generic 400 / a bare ValueError → 500.
                    raise ShareTypeVariationNotFound(
                        f"ShareTypeVariation with id {variation_id} does not exist",
                        field=key,
                        details={"variation_id": variation_id},
                    )

            elif key.startswith("offer_group_"):
                offer_group_id = key.replace("offer_group_", "")
                if not OfferGroup.objects.filter(id=offer_group_id).exists():
                    raise OfferGroupNotFound(
                        f"OfferGroup with id {offer_group_id} does not exist",
                        field=key,
                        details={"offer_group_id": offer_group_id},
                    )

        return data


class PurchaseSerializer(StorageFieldsMixin, serializers.ModelSerializer):
    seller_first_name = serializers.CharField(read_only=True)
    seller_last_name = serializers.CharField(read_only=True)
    seller_company_name = serializers.CharField(read_only=True)

    class Meta:
        model = Purchase
        fields = "__all__"

    def validate(self, attrs):
        from isoweek import Week

        from ..errors import OrganicPurchaseCertificateRequired
        from ..models import OrganicCertificate, ShareArticle
        from ..models.managers import active_on_date_q

        attrs = super().validate(attrs)

        status = attrs.get(
            "organic_status", getattr(self.instance, "organic_status", None)
        )
        if status not in (
            ShareArticle.OrganicStatus.ORGANIC,
            ShareArticle.OrganicStatus.IN_CONVERSION,
        ):
            return attrs

        # ``organic`` / ``in_conversion`` may only be carried through from a
        # seller certified AT this purchase's delivery week (the Monday of the
        # ISO year/week). No seller, or no covering certificate → reject.
        seller = attrs.get("seller", getattr(self.instance, "seller", None))
        year = attrs.get("year", getattr(self.instance, "year", None))
        week = attrs.get("delivery_week", getattr(self.instance, "delivery_week", None))
        certified = bool(
            seller
            and year
            and week
            and OrganicCertificate.objects.filter(reseller_id=seller.pk)
            .filter(active_on_date_q(Week(int(year), int(week)).monday()))
            .exists()
        )
        if not certified:
            raise OrganicPurchaseCertificateRequired(
                "The seller has no organic certificate valid for this "
                "purchase's delivery week.",
                field="organic_status",
            )
        return attrs


class HarvestSerializer(StorageFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Harvest
        fields = "__all__"


class WasteSerializer(StorageFieldsMixin, NameFieldMixin, serializers.ModelSerializer):
    NAME_FIELDS = ["share_article_name"]

    class Meta:
        model = Waste
        fields = "__all__"


class DocumentationAggregationItemSerializer(serializers.Serializer):
    """Single item in documentation aggregation response."""

    share_article_name = serializers.CharField()
    unit = serializers.CharField(help_text="Unit of measurement (kg, pieces, etc.)")
    size = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=3)


class PurchaseBulkSetAsExpectedItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    theoretical_purchase_amount = serializers.FloatField()
    theoretical_purchase_unit = serializers.CharField()
    theoretical_purchase_size = serializers.CharField()
    storage = serializers.CharField()


class PurchaseBulkSetAsExpectedRequestSerializer(serializers.Serializer):
    selectedData = serializers.ListField(
        child=PurchaseBulkSetAsExpectedItemSerializer()
    )


class HarvestBulkSetAsExpectedItemSerializer(serializers.Serializer):
    """Mirrors ``DocumentationSummaryService.bulk_set_as_expected`` —
    ``id`` is the share-article id of the summary row."""

    id = serializers.CharField()
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    day_number = serializers.IntegerField()
    theoretical_harvest_amount = serializers.FloatField()
    theoretical_harvest_unit = serializers.CharField()
    theoretical_harvest_size = serializers.CharField()
    storage = serializers.CharField()


class HarvestBulkSetAsExpectedRequestSerializer(serializers.Serializer):
    selectedData = serializers.ListField(child=HarvestBulkSetAsExpectedItemSerializer())


class DocumentationSummaryRowSerializer(serializers.Serializer):
    """Response shape of a ``DocumentationSummaryService.get_summary()`` row (and
    the create/update echoes via ``_summary_echo_response``).

    Schema-only: the view returns the service dict directly; this types the
    stable + per-model union fields so the generated client isn't ``any``.

    A row is one of four model variants (harvest / purchase / washamount /
    cleanamount), so the per-model amount fields are all optional — a given row
    carries only its model's set. The actual ``amount`` is a ``DecimalField``
    (rendered as a string); the computed theoretical / additional sums are
    floats (rendered as numbers). The two seeded harvest storages also add
    ``storage_<id>`` boolean keys with auto-generated ids — not statically
    declarable, read by iterating the storages on the frontend.
    """

    _DEC = {"max_digits": 12, "decimal_places": 3}

    # ---- stable identity ----
    id = serializers.CharField()
    share_article = serializers.CharField(allow_null=True)
    share_article_name = serializers.CharField()
    unit = serializers.CharField()
    size = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    theoretical_id = serializers.CharField(allow_null=True)
    additional_id = serializers.CharField(allow_null=True)

    # ---- per-model amounts (only the row's model set is present) ----
    harvest_amount = serializers.DecimalField(**_DEC, required=False, allow_null=True)
    purchase_amount = serializers.DecimalField(**_DEC, required=False, allow_null=True)
    washamount_amount = serializers.DecimalField(
        **_DEC, required=False, allow_null=True
    )
    cleanamount_amount = serializers.DecimalField(
        **_DEC, required=False, allow_null=True
    )
    theoretical_harvest_amount = serializers.FloatField(required=False, allow_null=True)
    theoretical_purchase_amount = serializers.FloatField(
        required=False, allow_null=True
    )
    theoretical_washamount_amount = serializers.FloatField(
        required=False, allow_null=True
    )
    theoretical_cleanamount_amount = serializers.FloatField(
        required=False, allow_null=True
    )
    additional_theoretical_harvest_amount = serializers.FloatField(
        required=False, allow_null=True
    )
    additional_theoretical_purchase_amount = serializers.FloatField(
        required=False, allow_null=True
    )
    additional_theoretical_washamount_amount = serializers.FloatField(
        required=False, allow_null=True
    )
    additional_theoretical_cleanamount_amount = serializers.FloatField(
        required=False, allow_null=True
    )

    # ---- forecast / stock ----
    forecast_plot_name = serializers.CharField(allow_null=True)
    forecast_bed_number = serializers.IntegerField(allow_null=True)
    forecast_note = serializers.CharField(allow_null=True)
    theoretical_current_stock = serializers.FloatField(allow_null=True)

    # ---- per-pu / crate / seller / price ----
    amount_per_pu = serializers.DecimalField(**_DEC, allow_null=True)
    harvesting_crate = serializers.CharField(allow_null=True)
    harvesting_crate_name = serializers.CharField(allow_null=True)
    seller = serializers.CharField(allow_null=True)
    seller_name = serializers.CharField(allow_null=True)
    price_per_unit = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    # Purchase-only: the documented organic status of the purchase (None for
    # other models). Lets DocumentationPurchase's organic column round-trip.
    organic_status = serializers.CharField(required=False, allow_null=True)

    # ---- harvest-only extras (present only when model == "harvest") ----
    theoretical_harvest_amount_share_content = serializers.FloatField(
        required=False, allow_null=True
    )
    theoretical_harvest_amount_order_content = serializers.FloatField(
        required=False, allow_null=True
    )
    additional_theoretical_harvest_amount_share_content = serializers.FloatField(
        required=False, allow_null=True
    )
    additional_theoretical_harvest_amount_order_content = serializers.FloatField(
        required=False, allow_null=True
    )
    theoretical_current_stock_share_content = serializers.FloatField(
        required=False, allow_null=True
    )
    theoretical_current_stock_order_content = serializers.FloatField(
        required=False, allow_null=True
    )
    is_finalized = serializers.BooleanField(required=False, allow_null=True)


class ForecastRowSerializer(serializers.Serializer):
    """Response shape of a ``ForecastService.get_forecasts_with_relations()`` row
    (the flattened forecast dicts returned by ``ForecastViewSet.list`` when both
    ``?year=`` and ``?delivery_week=`` are provided).

    Schema-only: the view returns the service dict directly; this types the
    stable keys so the generated client isn't ``any``.

    The service also adds per-relation ``variation_<id>`` and ``offer_group_<id>``
    boolean keys with auto-generated ids — not statically declarable, read by
    iterating the variations / offer groups on the frontend.
    """

    id = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=3, allow_null=True)
    bed_number = serializers.IntegerField(allow_null=True)
    delivery_week = serializers.IntegerField()
    for_all_harvest_shares = serializers.BooleanField()
    for_all_harvest_shares_fruit = serializers.BooleanField()
    for_all_markets = serializers.BooleanField()
    for_all_resellers = serializers.BooleanField()
    note = serializers.CharField(allow_null=True, allow_blank=True)
    plot = serializers.CharField(allow_null=True)
    plot_name = serializers.CharField(allow_blank=True)
    share_article = serializers.CharField()
    share_article_name = serializers.CharField()
    size = serializers.CharField()
    unit = serializers.CharField()
    year = serializers.IntegerField()
    is_finalized = serializers.BooleanField()
