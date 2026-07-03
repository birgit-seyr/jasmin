from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..errors import SharesDeliveryDayToursReducedWhileInUse
from ..models import OrdersDeliveryDay, PaymentCycle, SharesDeliveryDay, Subscription
from ..utils.deletion_utils import bulk_deletable_pks, can_delete_instance
from .serializers_mixin import DeletableMixin

# Reverse relation excluded when deciding whether a SharesDeliveryDay can be
# deleted (its own delivery-station-day children cascade away with it). Kept in
# lock-step between the per-instance fallback and the bulk pass below.
_SHARES_DELIVERY_DAY_DELETE_EXCLUDE = ["DeliveryStationDay"]


class _DeliveryStationEntrySerializer(serializers.Serializer):
    """Shape of one entry in `SharesDeliveryDaySerializer.delivery_stations`.

    Defined as a Serializer (not a TypedDict) so drf-spectacular emits a
    proper OpenAPI schema for the list items.
    """

    id = serializers.CharField()
    short_name = serializers.CharField()
    tour_number = serializers.IntegerField(allow_null=True)
    stop_order = serializers.IntegerField(allow_null=True)


class SharesDeliveryDayListSerializer(serializers.ListSerializer):
    """PERF-1: bulk-precomputes ``can_be_deleted`` for the delivery-day list.

    The per-instance path runs ``can_delete_instance`` (a reverse-relation walk)
    PLUS one ``Subscription`` 2-hop ``.exists()`` per row — an O(N) N+1 on the
    list endpoint. This collapses both to a fixed number of queries: one
    ``bulk_deletable_pks`` pass plus ONE ``Subscription`` query for the page.
    Falls back to the child's per-instance path when ``bulk_deletable_pks``
    reports it can't batch a relation, so behaviour stays identical.
    """

    _deletable_pks: set | None = None
    _bulk_failed: bool = False
    _subscription_in_use_day_ids: set | None = None

    def to_representation(self, data):
        instances = list(data)
        if instances:
            self._compute_bulk(instances)
        return super().to_representation(instances)

    def _compute_bulk(self, instances: list) -> None:
        pks = [obj.pk for obj in instances]
        deletable, failed = bulk_deletable_pks(
            SharesDeliveryDay,
            pks,
            exclude_models=_SHARES_DELIVERY_DAY_DELETE_EXCLUDE,
        )
        self._bulk_failed = failed
        if not failed:
            self._deletable_pks = deletable
        # 2-hop usage the deletion helper can't see: Subscription
        # .default_delivery_station_day -> DeliveryStationDay -> delivery_day.
        # One query for the whole page (default_delivery_station_day is nullable,
        # so NULL rows simply don't match).
        self._subscription_in_use_day_ids = set(
            Subscription.objects.filter(
                default_delivery_station_day__delivery_day_id__in=pks
            ).values_list("default_delivery_station_day__delivery_day_id", flat=True)
        )


class SharesDeliveryDaySerializer(serializers.ModelSerializer):
    can_be_deleted = serializers.SerializerMethodField()
    delivery_stations = serializers.SerializerMethodField()
    used_tours = serializers.ListField(
        child=serializers.IntegerField(), read_only=True, required=False
    )

    @extend_schema_field(_DeliveryStationEntrySerializer(many=True))
    def get_delivery_stations(self, obj):
        if hasattr(obj, "active_delivery_stations"):
            return [
                {
                    "id": station.delivery_station.id,
                    "short_name": station.delivery_station.short_name,
                    "tour_number": station.tour_number,
                    "stop_order": station.stop_order,
                }
                for station in obj.active_delivery_stations
            ]
        return []

    def get_can_be_deleted(self, obj) -> bool:
        """Check if this instance can be deleted.

        On the LIST path, read the parent ListSerializer's bulk-precomputed sets
        (one batch + one Subscription query for the whole page). The detail /
        create / update path (no list parent, or a bulk-batch failure) falls
        through to the per-instance check — identical result.
        """
        parent = getattr(self, "parent", None)
        if (
            isinstance(parent, SharesDeliveryDayListSerializer)
            and not parent._bulk_failed
            and parent._deletable_pks is not None
            and parent._subscription_in_use_day_ids is not None
        ):
            return (
                obj.pk in parent._deletable_pks
                and obj.pk not in parent._subscription_in_use_day_ids
            )

        can_delete, _ = can_delete_instance(
            obj, exclude_models=_SHARES_DELIVERY_DAY_DELETE_EXCLUDE
        )
        if not can_delete:
            return False

        # Additional check: subscriptions using this delivery day
        has_subscriptions = Subscription.objects.filter(
            default_delivery_station_day__delivery_day=obj
        ).exists()

        return not has_subscriptions

    class Meta:
        model = SharesDeliveryDay
        fields = "__all__"
        # PERF-1: list path bulk-precomputes deletability (one batch per reverse
        # relation + one Subscription query) instead of per-row N+1.
        list_serializer_class = SharesDeliveryDayListSerializer

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # The number of tours on an IN-USE (non-deletable) delivery day may only
        # be raised — lowering it would strand deliveries on the removed tours.
        # Raising it (e.g. 3 -> 4) is always fine.
        if self.instance is not None and "number_of_tours" in attrs:
            new_tours = attrs["number_of_tours"]
            current_tours = self.instance.number_of_tours
            if (
                new_tours is not None
                and current_tours is not None
                and new_tours < current_tours
                and not self.get_can_be_deleted(self.instance)
            ):
                raise SharesDeliveryDayToursReducedWhileInUse(
                    current_tours=current_tours, new_tours=new_tours
                )
        return attrs


class OrdersDeliveryDaySerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = OrdersDeliveryDay
        fields = "__all__"


class PaymentCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentCycle
        fields = "__all__"
