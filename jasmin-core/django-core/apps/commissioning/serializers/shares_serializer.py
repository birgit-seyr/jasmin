from datetime import date

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from ..errors import ShareTypeVariationOutsideShareTypeRange
from ..models import (
    Share,
    ShareContent,
    ShareDelivery,
    ShareType,
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
    Subscription,
)
from ..utils.capacity_window import build_capacity_by_week, parse_capacity_window
from ..utils.dynamic_keys import AMOUNT_KEY_PREFIX, DAY_VARIATION_RE
from ..utils.iso_week_utils import share_delivery_date
from .box_matrix_columns_serializer import PackingBoxesMatrixColumnSerializer
from .delivery_serializer import CapacityWeekEntrySerializer
from .dynamic_keys import DynamicAmountKeysMixin
from .serializers_mixin import (
    DeletableMixin,
    NameFieldMixin,
    mask_capacity_for_anonymous,
)


class _EmptyToZeroIntegerField(serializers.IntegerField):
    """An IntegerField that treats a cleared cell (``null`` or ``""``) as 0.

    The office ShareType table lets a user blank a joker count; the intent is
    "no jokers" (0), not a validation error. Coerce empty input to 0 instead of
    rejecting it, without allowing a genuinely absent key to overwrite the
    stored value on a PATCH.
    """

    def validate_empty_values(self, data):
        if data is None or data == "":
            return (True, 0)
        return super().validate_empty_values(data)


class ShareTypeSerializer(DeletableMixin, serializers.ModelSerializer):
    # Blanking a joker count in the office table means "0", so accept null / "".
    amount_of_jokers = _EmptyToZeroIntegerField(required=False)
    amount_of_donation_jokers = _EmptyToZeroIntegerField(required=False)
    share_type_variation_sizes_in_use = serializers.SerializerMethodField()
    # The lower bound for this share type's ``valid_until``: it may not end
    # before its latest variation, and cannot be closed at all while a variation
    # is open-ended (mirrors ``ShareType.clean``'s stranding guard). The
    # frontend datepicker disables Sundays before the max (and all dates when
    # open-ended) so the office can't submit an end date the backend rejects.
    variations_valid_until_max = serializers.SerializerMethodField()
    has_open_ended_variation = serializers.SerializerMethodField()

    class Meta:
        model = ShareType
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # DRF auto-builds a ``UniqueValidator`` on ``share_option`` from the
        # single-field ``sharetype_one_open_per_option`` partial constraint, but
        # it IGNORES the constraint's ``valid_until IS NULL`` condition — so it
        # treats share_option as GLOBALLY unique and rejects every succession in
        # ``is_valid()``, before ``save()`` → ``handle_succession`` can close the
        # open predecessor. Drop it; the real "one OPEN per share_option"
        # invariant is still enforced by the DB partial constraint and the
        # model's ``full_clean()`` (which runs in ``save()`` AFTER succession).
        share_option_field = self.fields.get("share_option")
        if share_option_field is not None:
            share_option_field.validators = [
                validator
                for validator in share_option_field.validators
                if not isinstance(validator, UniqueValidator)
            ]

    def get_share_type_variation_sizes_in_use(self, obj: ShareType) -> str:
        # Precomputed once per request by ``ShareTypeViewSet.list`` (single
        # query over the active variations) to avoid an N+1 per row.
        sizes_in_use_by_share_type = self.context.get("sizes_in_use_by_share_type", {})
        return sizes_in_use_by_share_type.get(obj.id, "")

    def _variation_bounds(self, obj: ShareType) -> dict:
        # Precomputed once per request by ``ShareTypeViewSet.list`` (single
        # aggregate over all variations) to avoid an N+1 per row.
        return self.context.get("variation_bounds_by_share_type", {}).get(obj.id, {})

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_variations_valid_until_max(self, obj: ShareType):
        value = self._variation_bounds(obj).get("max_valid_until")
        return value.isoformat() if value else None

    @extend_schema_field(serializers.BooleanField())
    def get_has_open_ended_variation(self, obj: ShareType) -> bool:
        return bool(self._variation_bounds(obj).get("has_open_ended"))


class ShareTypeVariationSerializer(
    DeletableMixin, NameFieldMixin, serializers.ModelSerializer
):
    NAME_FIELDS = ["share_type_name"]

    active_price_per_delivery = serializers.DecimalField(
        max_digits=8, decimal_places=2, read_only=True
    )
    active_price_sum_articles = serializers.DecimalField(
        max_digits=8, decimal_places=2, read_only=True
    )
    # Active solidarity floor (null when none set) — drives the editable price
    # field's min in the abos table + new-subscription modal.
    active_solidarity_min_price_per_delivery = serializers.DecimalField(
        max_digits=8, decimal_places=2, read_only=True, allow_null=True
    )
    # Per-ISO-week production-cap occupancy — the term-aware source of truth the
    # frontend's ``termCapacity`` evaluator reads (same
    # ``{"<year>-<week>": {occupied, free}}`` shape as the station-day's
    # ``capacity_by_week``). Populated only when the request carries ``year`` +
    # ``delivery_week`` (else ``None``); a term is full when its busiest ("peak")
    # week has ``free <= 0`` — exactly what ``VariationCapacityService`` blocks.
    capacity_by_week = serializers.SerializerMethodField()
    # The lower bound for this variation's ``valid_until``: it may not end before
    # its latest subscription, and cannot be closed at all while a subscription
    # is open-ended (mirrors ``ShareTypeVariation.clean``'s stranding guard).
    # Cancelled subscriptions have their ``valid_until`` truncated to the exit,
    # so the max is naturally the latest STILL-active end. The frontend
    # datepicker disables Sundays before the max (and all dates when open-ended).
    subscriptions_valid_until_max = serializers.SerializerMethodField()
    has_open_ended_subscription = serializers.SerializerMethodField()

    class Meta:
        model = ShareTypeVariation
        fields = "__all__"

    def _batched_variation_counts(self, year_weeks):
        """Occupancy for every variation in THIS serialization run, computed
        once and cached on the shared child serializer (kills the per-row
        N+1)."""
        cached = getattr(self, "_variation_counts_cache", None)
        if cached is not None:
            return cached

        from ..services.variation_capacity_service import VariationCapacityService

        # ``self.parent.instance`` is the whole page under ``many=True``; fall
        # back to the single instance when serialized on its own.
        if self.parent is not None and self.parent.instance is not None:
            instances = list(self.parent.instance)
        else:
            instances = [self.instance]
        variation_ids = [obj.id for obj in instances if getattr(obj, "id", None)]

        counts = VariationCapacityService.capacity_counts_by_week(
            variation_ids=variation_ids,
            year_weeks=year_weeks,
        )
        self._variation_counts_cache = counts
        return counts

    def _batched_subscription_bounds(self):
        """``{variation_id: {"max_valid_until", "has_open_ended"}}`` for every
        variation in THIS serialization run, in ONE aggregate (kills the per-row
        N+1). Mirrors ``_batched_variation_counts``' parent-instance trick."""
        cached = getattr(self, "_subscription_bounds_cache", None)
        if cached is not None:
            return cached

        from django.db.models import Count, Max, Q

        from ..models.members import Subscription

        if self.parent is not None and self.parent.instance is not None:
            instances = list(self.parent.instance)
        else:
            instances = [self.instance]
        variation_ids = [obj.id for obj in instances if getattr(obj, "id", None)]

        bounds = {
            row["share_type_variation_id"]: {
                "max_valid_until": row["max_valid_until"],
                "has_open_ended": row["open_count"] > 0,
            }
            for row in (
                Subscription.objects.filter(share_type_variation_id__in=variation_ids)
                .values("share_type_variation_id")
                .annotate(
                    max_valid_until=Max("valid_until"),
                    open_count=Count("pk", filter=Q(valid_until__isnull=True)),
                )
            )
        }
        self._subscription_bounds_cache = bounds
        return bounds

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_subscriptions_valid_until_max(self, obj: ShareTypeVariation):
        value = (
            self._batched_subscription_bounds().get(obj.id, {}).get("max_valid_until")
        )
        return value.isoformat() if value else None

    @extend_schema_field(serializers.BooleanField())
    def get_has_open_ended_subscription(self, obj: ShareTypeVariation) -> bool:
        return bool(
            self._batched_subscription_bounds().get(obj.id, {}).get("has_open_ended")
        )

    @extend_schema_field(
        serializers.DictField(child=CapacityWeekEntrySerializer(), allow_null=True)
    )
    def get_capacity_by_week(self, obj: ShareTypeVariation):
        year, start_week, num_weeks = parse_capacity_window(self.context.get("request"))
        if year is None or start_week is None:
            return None
        from ..utils.iso_week_utils import iso_week_range

        # ``date.fromisocalendar`` raises on an out-of-range start_week; return
        # None (same guard as the station-day serializer) rather than 500.
        try:
            date.fromisocalendar(year, start_week, 1)
        except ValueError:
            return None
        year_weeks = iso_week_range(year, start_week, num_weeks)
        counts = self._batched_variation_counts(year_weeks)
        # Variations always carry a numeric cap → no capacity_nullable guard.
        return build_capacity_by_week(year_weeks, counts, obj.id, obj.capacity)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Public registration (anonymous) reads: availability only — never the
        # exact per-week subscriber counts or the raw cap.
        mask_capacity_for_anonymous(ret, self.context.get("request"))
        return ret

    def validate_capacity(self, value):
        """Floor a capacity edit at the busiest current-or-future week's
        occupancy — the office can't drop the farm-wide cap below what's already
        subscribed for any upcoming week (mirrors the station-day guard, and
        prevents a silent mass-waitlist). On create (``self.instance is None``)
        nothing is subscribed yet, so skip.
        """
        if self.instance is None:
            return value

        from django.utils import timezone

        from ..errors import ShareTypeVariationCapacityBelowOccupancy
        from ..services.variation_capacity_service import VariationCapacityService

        peak = VariationCapacityService.peak_occupied_from_week(
            variation_id=self.instance.pk,
            from_date=timezone.now().date(),
        )
        if value < peak:
            raise ShareTypeVariationCapacityBelowOccupancy(capacity=value, peak=peak)
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # A variation's validity must lie WITHIN its share type's validity —
        # otherwise it (and the subscriptions on it) would outlive its parent.
        share_type = attrs.get("share_type") or getattr(
            self.instance, "share_type", None
        )
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get(
            "valid_until", getattr(self.instance, "valid_until", None)
        )
        if share_type is not None and valid_from is not None:
            within_range = valid_from >= share_type.valid_from and (
                share_type.valid_until is None
                or (valid_until is not None and valid_until <= share_type.valid_until)
            )
            if not within_range:
                raise ShareTypeVariationOutsideShareTypeRange(
                    variation_from=valid_from,
                    variation_until=valid_until,
                    share_type_from=share_type.valid_from,
                    share_type_until=share_type.valid_until,
                )
        return attrs


class ShareContentNestedSerializer(serializers.ModelSerializer):
    share_article_name = serializers.CharField(
        source="share_article.name", read_only=True
    )
    seller_name_for_member_pages = serializers.CharField(
        source="seller.name_for_member_pages",
        read_only=True,
        allow_null=True,
        default=None,
    )
    organic_status = serializers.CharField(
        source="share_article.organic_status", read_only=True, allow_null=True
    )

    class Meta:
        model = ShareContent
        fields = [
            "id",
            "share_article",
            "share_article_name",
            "seller",
            "seller_name_for_member_pages",
            "organic_status",
            "amount",
            "unit",
            "size",
        ]


class ShareDeliverySerializer(serializers.ModelSerializer):
    member_first_name = serializers.CharField(
        source="subscription.member.first_name", read_only=True
    )
    member_last_name = serializers.CharField(
        source="subscription.member.last_name", read_only=True
    )
    member_number = serializers.CharField(
        source="subscription.member.member_number", read_only=True
    )
    year = serializers.IntegerField(source="share.year", read_only=True)
    delivery_week = serializers.IntegerField(
        source="share.delivery_week", read_only=True
    )
    delivery_day_number = serializers.IntegerField(
        source="share.delivery_day.day_number", read_only=True
    )
    delivery_station_name = serializers.CharField(
        source="delivery_station_day.delivery_station.short_name", read_only=True
    )
    share_type_name = serializers.CharField(
        source="share.share_type_variation.share_type.name", read_only=True
    )
    share_type_variation_size = serializers.CharField(
        source="share.share_type_variation.size", read_only=True
    )
    share_type_variation_type = serializers.CharField(
        source="share.share_type_variation.variation_type", read_only=True
    )
    ordered_share_type_name = serializers.CharField(
        source="subscription.share_type_variation.share_type.name",
        read_only=True,
    )
    ordered_variation_name = serializers.CharField(
        source="subscription.share_type_variation.size",
        read_only=True,
    )
    ordered_variation_type = serializers.CharField(
        source="subscription.share_type_variation.variation_type",
        read_only=True,
    )
    # Per-share-type joker allowances, so the delivery-edit modal can decide
    # whether to show the joker / donation-joker checkboxes (only when the
    # share type actually grants that kind of joker). Same share-type path as
    # ``share_type_name`` above → covered by the existing select_related.
    amount_of_jokers = serializers.IntegerField(
        source="share.share_type_variation.share_type.amount_of_jokers",
        read_only=True,
    )
    amount_of_donation_jokers = serializers.IntegerField(
        source="share.share_type_variation.share_type.amount_of_donation_jokers",
        read_only=True,
    )
    # On-off opt-in surface (per-delivery toggle in the deliveries card).
    # ``requires_optin`` flags an on-off delivery; ``is_opted_in`` /
    # ``optin_decided_at`` are the member's decision; ``optin_locked`` says the
    # deadline has passed (toggle disabled). All read-only — writes go through
    # the dedicated ``toggle_optin`` action, never the generic update.
    requires_optin = serializers.BooleanField(
        source="share.share_type_variation.requires_optin", read_only=True
    )
    is_opted_in = serializers.BooleanField(read_only=True)
    optin_decided_at = serializers.DateTimeField(read_only=True)
    optin_deadline = serializers.SerializerMethodField()
    optin_locked = serializers.SerializerMethodField()

    share_content = serializers.SerializerMethodField()

    # Write-only control flag for PATCH: "also apply this station-day change to
    # the subscription's future deliveries". The viewset's perform_update reads
    # it; it is NOT a model field — declared here so the OpenAPI schema (and the
    # generated client) carries it instead of it being an invisible raw
    # ``request.data`` key. Popped from validated_data in create/update so the
    # ModelSerializer never passes it to the model.
    apply_to_future = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = ShareDelivery
        fields = [
            "id",
            "share",
            "subscription",
            "delivery_station_day",
            "member_first_name",
            "member_last_name",
            "member_number",
            "year",
            "delivery_week",
            "delivery_day_number",
            "delivery_station_name",
            "share_type_name",
            "share_type_variation_size",
            "share_type_variation_type",
            "ordered_share_type_name",
            "ordered_variation_name",
            "ordered_variation_type",
            "share_content",
            "joker_taken",
            "donation_joker_taken",
            "amount_of_jokers",
            "amount_of_donation_jokers",
            "requires_optin",
            "is_opted_in",
            "optin_decided_at",
            "optin_deadline",
            "optin_locked",
            "apply_to_future",
        ]

    def create(self, validated_data):
        validated_data.pop("apply_to_future", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("apply_to_future", None)
        return super().update(instance, validated_data)

    @extend_schema_field(ShareContentNestedSerializer(many=True))
    def get_share_content(self, obj):
        """Get all finalized share content for this delivery's share.

        ShareDeliveryViewSet prefetches ``share__sharecontent_set``
        (and ``share_article`` on each entry). Calling ``.filter()`` on
        the prefetched manager would issue a fresh query per row and
        defeat the prefetch — so we filter in Python over the cached
        ``all()`` result instead. Locked by
        ``apps/payments/tests/test_query_count_locks.py``.
        """
        target_station_id = obj.delivery_station_day.delivery_station_id
        share_contents = [
            share_content
            for share_content in obj.share.sharecontent_set.all()
            if share_content.is_finalized
            and share_content.delivery_station_id == target_station_id
        ]
        return ShareContentNestedSerializer(share_contents, many=True).data

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_optin_deadline(self, obj):
        # Reads share.share_type_variation + the share's date fields, both
        # covered by the viewset select_related → no per-row query.
        from apps.commissioning.services.optin_service import OptinService

        return OptinService.optin_deadline(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_optin_locked(self, obj):
        from apps.commissioning.services.optin_service import OptinService

        return OptinService.is_locked(obj)


class ShareDeliveryOverviewSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField()
    share_type_variation_string = serializers.CharField()
    delivery_week = serializers.IntegerField()
    delivery_date = serializers.SerializerMethodField()

    class Meta:
        model = ShareDelivery
        fields = "__all__"
        # On-off opt-in state is owned by OptinService.toggle (deadline guard +
        # audit stamp + recompute) — it must NEVER be writable through this
        # generic office grid, or the office could flip a locked delivery and
        # skip the audit trail. joker_taken / delivery_station_day stay editable.
        read_only_fields = ("is_opted_in", "optin_decided_at", "optin_decided_by")

    def get_delivery_date(self, obj) -> str | None:
        """ISO-8601 (``YYYY-MM-DD``) delivery date via the shared resolver.

        Uses ``share_delivery_date`` — which honours the Share's
        ``changed_day_number`` override before falling back to the delivery
        day's ``day_number`` — so the overview matches every other delivery-
        date surface. ``None`` for a malformed year/week/day tuple.
        """
        delivery_date = share_delivery_date(obj)
        return delivery_date.isoformat() if delivery_date else None


class DeliveryExceptionGapSerializer(serializers.Serializer):
    """A week a subscription WOULD deliver but doesn't, because a delivery
    exception ("Lieferpause") suppressed the ShareDelivery. There is no
    ShareDelivery row for these — they are reconstructed by
    ``services.delivery_exceptions.member_exception_gaps``."""

    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    delivery_day_number = serializers.IntegerField(allow_null=True)
    share_type_name = serializers.CharField(allow_blank=True)
    share_type_variation_size = serializers.CharField(allow_blank=True)
    note = serializers.CharField(allow_blank=True)


class ShareContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareContent
        fields = "__all__"


class ShareSerializer(serializers.ModelSerializer):
    delivery_day_number = serializers.IntegerField(read_only=True)
    share_type_name = serializers.CharField(read_only=True)
    share_type_variation_size = serializers.CharField(read_only=True)
    share_type_variation_average_weight = serializers.DecimalField(
        max_digits=5, decimal_places=3, read_only=True
    )

    class Meta:
        model = Share
        fields = "__all__"


class ShareDayPlanningRowSerializer(serializers.Serializer):
    """Response row of ``ShareViewSet.get_days`` / ``bulk_update``.

    Mirrors ``_build_day_data`` in ``viewsets/shares_viewsets.py``: one row
    per delivery day carrying the week's day-level overrides plus a
    ``*_changed`` flag per field marking deviation from the delivery
    day's defaults.
    """

    id = serializers.IntegerField()
    delivery_day = serializers.IntegerField()
    changed_day_number = serializers.IntegerField(allow_null=True)
    harvesting_day = serializers.IntegerField(allow_null=True)
    harvesting_day_changed = serializers.BooleanField()
    packing_day = serializers.IntegerField(allow_null=True)
    packing_day_changed = serializers.BooleanField()
    washing_day = serializers.IntegerField(allow_null=True)
    washing_day_changed = serializers.BooleanField()
    cleaning_day = serializers.IntegerField(allow_null=True)
    cleaning_day_changed = serializers.BooleanField()
    get_current_stock_day = serializers.IntegerField(allow_null=True)
    get_current_stock_day_changed = serializers.BooleanField()


class ShareTypeVariationGrossPriceSerializer(
    DeletableMixin, serializers.ModelSerializer
):
    share_type_variation_size = serializers.CharField(read_only=True)

    class Meta:
        model = ShareTypeVariationGrossPrice
        fields = "__all__"

    def get_can_be_deleted(self, obj: ShareTypeVariationGrossPrice) -> bool:
        # Base reverse-relation deletability (DeletableMixin) first.
        if not super().get_can_be_deleted(obj):
            return False
        # A price whose variation any member has subscribed to must not be
        # deletable: the subscription references the variation (not this price
        # row), so the PROTECT FK doesn't cover it, but the price is part of
        # that variation's billable history. The list endpoint precomputes the
        # set in one query (via context); retrieve falls back to one exists().
        variation_ids = self.context.get("variation_ids_with_subscriptions")
        if variation_ids is not None:
            return obj.share_type_variation_id not in variation_ids
        return not Subscription.objects.filter(
            share_type_variation_id=obj.share_type_variation_id
        ).exists()


# --- Default Share Content ---


class DefaultShareContentRequestSerializer(
    DynamicAmountKeysMixin, serializers.Serializer
):
    year = serializers.IntegerField()
    share_article = serializers.CharField()
    share_option = serializers.CharField()
    unit = serializers.CharField()
    size = serializers.CharField()
    range_1 = serializers.IntegerField()
    range_2 = serializers.IntegerField()
    only_odd_weeks = serializers.BooleanField(required=False, default=False)
    only_even_weeks = serializers.BooleanField(required=False, default=False)
    only_every_three_weeks = serializers.BooleanField(required=False, default=False)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    seller = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def _is_dynamic_amount_key(self, key: str) -> bool:
        return key.startswith(AMOUNT_KEY_PREFIX) and len(key) > len(AMOUNT_KEY_PREFIX)


class DefaultShareContentResponseSerializer(serializers.Serializer):
    """Schema doc for the bulk-list / bulk-create / bulk-update payload.

    Per-variation amounts are returned alongside as ``amount_<variation_id>``
    keys — those are dynamic and stay untyped in the generated client; this
    serializer only documents the stable fields, ``needed_amount`` included.
    """

    id = serializers.CharField()
    year = serializers.IntegerField()
    share_article = serializers.CharField()
    share_option = serializers.CharField(allow_null=True)
    range_1 = serializers.IntegerField()
    range_2 = serializers.IntegerField()
    unit = serializers.CharField()
    size = serializers.CharField()
    note = serializers.CharField(allow_blank=True, allow_null=True)
    only_odd_weeks = serializers.BooleanField()
    only_even_weeks = serializers.BooleanField()
    only_every_three_weeks = serializers.BooleanField()
    needed_amount = serializers.CharField()
    seller = serializers.CharField(allow_null=True)
    seller_name = serializers.CharField(allow_null=True)


# --- Virtual Variation Components ---


class VirtualVariationComponentItemSerializer(serializers.Serializer):
    physical_variation = serializers.CharField()
    quantity = serializers.FloatField(default=1.0)


class VirtualVariationComponentListItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    virtual_variation = serializers.CharField()
    physical_variation = serializers.CharField()
    physical_variation_name = serializers.CharField()
    quantity = serializers.FloatField()


class VirtualVariationComponentsRequestSerializer(serializers.Serializer):
    virtual_variation = serializers.CharField()
    components = serializers.ListField(child=VirtualVariationComponentItemSerializer())


class VirtualVariationComponentsResponseSerializer(serializers.Serializer):
    virtual_variation = serializers.CharField()
    variation_type = serializers.CharField()
    components = serializers.ListField(child=serializers.DictField())


# --- Harvest Share Planning ---


class _DayVariationAmountSerializer(DynamicAmountKeysMixin, serializers.Serializer):
    """Base for the share-planning request serializers — validates the dynamic
    ``day_<id>_variation_<id>`` amount cells via the shared pattern."""

    def _is_dynamic_amount_key(self, key: str) -> bool:
        return bool(DAY_VARIATION_RE.match(key))


class HarvestSharePlanningCreateRequestSerializer(_DayVariationAmountSerializer):
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    share_article = serializers.CharField()
    unit = serializers.CharField(required=False)
    size = serializers.CharField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    seller = serializers.CharField(required=False, allow_null=True)
    cleaning = serializers.BooleanField(required=False, default=False)
    washing = serializers.BooleanField(required=False, default=False)
    kg_per_piece = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, allow_null=True
    )
    price_per_unit = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    packing_station = serializers.IntegerField(required=False, default=1)


class HarvestSharePlanningUpdateRequestSerializer(_DayVariationAmountSerializer):
    year = serializers.IntegerField(required=False)
    delivery_week = serializers.IntegerField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    seller = serializers.CharField(required=False, allow_null=True)
    cleaning = serializers.BooleanField(required=False, default=False)
    washing = serializers.BooleanField(required=False, default=False)
    kg_per_piece = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, allow_null=True
    )
    price_per_unit = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    packing_station = serializers.IntegerField(required=False, default=1)


class HarvestSharePlanningBackupRequestSerializer(_DayVariationAmountSerializer):
    backup_share_article = serializers.CharField(required=False, allow_null=True)
    backup_unit = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    backup_size = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )


class HarvestSharePlanningRowSerializer(serializers.Serializer):
    """Stable fields of a harvest-share planning group row.

    Mirrors ``ShareContentService.get_share_content_as_frontend_data`` (one
    object per ``(year, week, article, unit, size)`` slot) — the response of
    ``HarvestSharePlanningViewSet`` list (many) and the single-group echo of
    create / update / partial_update / backup.

    Dynamic per-day/per-variation keys are read by iteration on the frontend
    and are left OUT here:
      * ``day_<day_id>_variation_<variation_id>`` (basic amount cells)
      * ``day_<day_id>_variation_<variation_id>_station_<station_id>`` (per-station)
      * ``day_<day_id>_variation_<variation_id>_tour_<n>`` (per-tour)
      * ``backup_day_<day_id>_variation_<variation_id>`` (backup amount cells)
      * ``day_<day_id>_planned_amount`` (per-day planned totals)

    ``variations`` / ``basic_variations`` / ``tour_variations`` /
    ``backup_variations`` appear as nested empty objects only on synthesized
    stock-only rows (and on the cleared-slot placeholder echoed by update) —
    in normal rows they are flattened into the dynamic keys above and are not
    present. They are declared ``required=False`` here for that reason.
    """

    id = serializers.CharField()
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    share_article = serializers.CharField()
    share_article_name = serializers.CharField(required=False)
    # Per-article spoilage buffer % for the commissioning-list PACKING view;
    # applied to the displayed amount there (the harvest-planning grid ignores it).
    percentage_added_to_commissioning_list_packing = serializers.IntegerField(
        required=False
    )
    # Per-size weight references off the ShareArticle (all DecimalField, nullable).
    kg_per_piece_S = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    kg_per_piece_M = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    kg_per_piece_L = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    kg_per_bunch_S = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    kg_per_bunch_M = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    kg_per_bunch_L = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    # Resolved (share_content value, else share-article fallback) — DecimalField.
    kg_per_piece = serializers.DecimalField(
        max_digits=12, decimal_places=3, allow_null=True, required=False
    )
    price_per_unit = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, required=False
    )
    packing_station = serializers.IntegerField(required=False)
    unit = serializers.CharField(required=False)
    size = serializers.CharField(required=False)
    note = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    seller = serializers.CharField(allow_null=True, required=False)
    cleaning = serializers.BooleanField(allow_null=True, required=False)
    washing = serializers.BooleanField(allow_null=True, required=False)
    forecast_available_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, required=False
    )
    forecast = serializers.CharField(allow_null=True, required=False)
    forecast_unit = serializers.CharField(allow_null=True, required=False)
    forecast_note = serializers.CharField(
        allow_blank=True, allow_null=True, required=False
    )
    forecast_share_type_variation_ids = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    # Computed in Python (float at the boundary).
    current_stock_begin_of_week = serializers.FloatField(required=False)
    current_stock_note = serializers.CharField(allow_blank=True, required=False)
    backup_share_article = serializers.CharField(allow_null=True, required=False)
    # Only present on real rows (not on stock-only rows / placeholder).
    backup_share_article_name = serializers.CharField(allow_null=True, required=False)
    backup_unit = serializers.CharField(allow_null=True, required=False)
    backup_size = serializers.CharField(allow_null=True, required=False)
    is_finalized = serializers.BooleanField(required=False)
    # Only on synthesized stock-only rows.
    is_stock_only = serializers.BooleanField(required=False)
    # Nested empty objects on stock-only rows / the cleared-slot placeholder;
    # flattened into dynamic keys on normal rows.
    variations = serializers.DictField(required=False)
    basic_variations = serializers.DictField(required=False)
    tour_variations = serializers.DictField(required=False)
    backup_variations = serializers.DictField(required=False)


class PackingListRowSerializer(serializers.Serializer):
    """Stable fields of a ``PackingListService.get_packing_list`` row — one
    object per ``(share_article, unit, size)`` (grouped by packing station).

    Dynamic ``variation_<share_type_variation_id>`` amount keys are read by
    iteration on the frontend and are left OUT here.
    """

    id = serializers.CharField()
    share_article = serializers.CharField()
    share_article_name = serializers.CharField()
    unit = serializers.CharField()
    size = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    backup_share_article = serializers.CharField(allow_null=True)
    backup_share_article_name = serializers.CharField(allow_null=True)
    backup_share_article_unit = serializers.CharField(allow_null=True)
    backup_share_article_size = serializers.CharField(allow_blank=True)
    packing_station = serializers.IntegerField()


class PackingBoxesMatrixRowSerializer(serializers.Serializer):
    """Stable fields of a packing boxes matrix row — one per
    ``(share_article, unit, size)``. Dynamic ``combo_<signature>`` per-box
    quantity keys are read by iteration on the frontend and are left OUT here
    (mirrors the ``variation_<id>`` pattern in ``PackingListRowSerializer``).
    """

    id = serializers.CharField()
    share_article_id = serializers.CharField()
    share_article_name = serializers.CharField()
    unit = serializers.CharField(allow_blank=True)
    size = serializers.CharField(allow_blank=True)
    note = serializers.CharField(allow_blank=True)


class PackingBoxesMatrixSerializer(serializers.Serializer):
    """Full packing boxes matrix payload: combination columns + article rows."""

    columns = PackingBoxesMatrixColumnSerializer(many=True)
    rows = PackingBoxesMatrixRowSerializer(many=True)


class StationMemberMatrixRowSerializer(serializers.Serializer):
    """One member of a delivery station. Dynamic ``combo_<signature>`` integer
    keys carry the member's box count of that combination (read by iteration on
    the frontend, left OUT of the typed schema like the ``variation_<id>``
    pattern)."""

    id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)


class StationMemberMatrixSerializer(serializers.Serializer):
    """Delivery-station member × combination matrix: the SAME combination
    columns as the packing boxes matrix, one row per member."""

    columns = PackingBoxesMatrixColumnSerializer(many=True)
    rows = StationMemberMatrixRowSerializer(many=True)


class ShareDeliveryDetailsRowSerializer(serializers.Serializer):
    """Stable fields of a ``ShareDeliveryDetailsViewSet.list`` row — one object
    per member.

    Dynamic ``variation_<share_type_variation_id>`` integer quantity keys are
    read by iteration on the frontend and are left OUT here.
    """

    id = serializers.CharField()
    name = serializers.CharField()


class ShareTypeVariationTotalRowSerializer(serializers.Serializer):
    """One share_type_variation total row of ``ShareTypeVariationsTotalsView``.

    Honest UNION of the view's two code paths (see the view's ``get``):

    * Logical path (``physical_share_type_variations`` falsy) →
      ``get_total_quantity_of_share_type_variations``: emits
      ``share__share_type_variation_id``, ``share__share_type_variation__size``
      and ``total_quantity``. It does NOT emit
      ``share__share_type_variation__name``.
    * Physical path (``physical_share_type_variations`` truthy) →
      ``get_physical_share_type_variation_totals``: emits the same three keys
      PLUS ``share__share_type_variation__name`` (which falls back to the
      variation's size — ``ShareTypeVariation`` has no ``name`` attribute).

    ``share__share_type_variation__name`` is therefore the only path-specific
    key and is declared ``required=False`` + ``allow_null=True``.
    ``total_quantity`` is a Python ``int`` on both paths (a summed
    ``defaultdict(int)`` on the logical path, a ``round(Decimal)`` on the
    physical path) → ``IntegerField``.
    """

    share__share_type_variation_id = serializers.CharField()
    share__share_type_variation__size = serializers.CharField()
    share__share_type_variation__name = serializers.CharField(
        required=False, allow_null=True
    )
    total_quantity = serializers.IntegerField()


class ShareTypeVariationsTotalsResponseSerializer(serializers.Serializer):
    """Envelope returned by ``ShareTypeVariationsTotalsView`` —
    ``{"variations": [...]}``."""

    variations = ShareTypeVariationTotalRowSerializer(many=True)
