from datetime import date

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.authz.permissions import IsStaff, has_any_role

from ..errors import (
    DeliveryExceptionInvalidRange,
    DeliveryExceptionOverlap,
    DeliveryExceptionPeriodLocked,
)
from ..models import DeliveryExceptionPeriod, DeliveryStation, DeliveryStationDay
from ..utils.deletion_utils import bulk_deletable_pks, can_delete_instance
from ..utils.query_params import validate_query_params
from .box_matrix_columns_serializer import PackingBoxesMatrixColumnSerializer
from .serializers_mixin import (
    DeletableMixin,
    DynamicContactFieldsMixin,
    DynamicDeliveryDayFieldsMixin,
    mask_capacity_for_anonymous,
)

# ========================================
# DELIVERY STATION SERIALIZERS
# ========================================

# Reverse relations excluded when deciding whether a DeliveryStation /
# linked Reseller can be deleted. Kept in module scope so the bulk list
# serializer and the per-row fallback use the SAME exclude sets.
#
# ``DeliveryStationDay`` is deliberately NOT excluded: its FK to the station
# is CASCADE, but the days themselves are PROTECTed downstream (import demand
# rows, share content, a member's default station-day — see the FKs to
# ``DeliveryStationDay``), so deleting a station that has days would raise
# ProtectedError mid-cascade. A configured station is therefore effectively
# undeletable, and the office must not be shown a delete button that 500s.
# Only ``Reseller`` is excluded (its unlink is handled separately via
# ``linked_reseller_can_be_deleted``).
_STATION_DELETE_EXCLUDE = ["Reseller"]
_RESELLER_DELETE_EXCLUDE = ["DeliveryStation"]


class CapacityWeekEntrySerializer(serializers.Serializer):
    """One "<year>-<week>" entry of ``capacity_by_week``. Schema-only — the
    method builds plain dicts; this gives the generated client a typed
    {occupied, free} shape instead of ``{[key: string]: unknown}``."""

    occupied = serializers.IntegerField()
    # ``None`` when the station-day has no capacity limit.
    free = serializers.IntegerField(allow_null=True)


class DeliveryStationListSerializer(serializers.ListSerializer):
    """Bulk-precomputes the two per-row deletability flags for the station list.

    The naive child implementation calls ``can_delete_instance`` once for
    ``get_can_be_deleted`` and once for ``get_linked_reseller_can_be_deleted``
    per row — each walking the model's reverse relations (R queries). On the
    list endpoint that's an O(N*R) N+1. Here both are collapsed to R queries
    total via ``bulk_deletable_pks`` (one ``filter(fk__in=pks)`` per reverse
    relation). The child reads the precomputed sets; falls back to the
    per-instance path when ``bulk_deletable_pks`` reports it can't batch a
    relation, so behaviour stays identical to ``can_delete_instance``.

    Locked by
    apps/commissioning/tests/tests_viewsets/test_delivery_station_query_count.py.
    """

    # Set on ``self`` once ``to_representation`` runs; the child reads them.
    _station_deletable_pks: set | None = None
    _station_failed: bool = False
    _linked_reseller_deletable_pks: set | None = None
    _linked_reseller_failed: bool = False

    def to_representation(self, data):
        instances = list(data)
        if instances:
            self._compute_bulk_deletable(instances)
        return super().to_representation(instances)

    def _compute_bulk_deletable(self, instances: list) -> None:
        from ..models import Reseller

        station_pks = [obj.pk for obj in instances]
        deletable, failed = bulk_deletable_pks(
            DeliveryStation, station_pks, exclude_models=_STATION_DELETE_EXCLUDE
        )
        self._station_deletable_pks = deletable
        self._station_failed = failed

        # ``linked_reseller`` is select_related in the viewset, so this
        # forward O2O access is query-free.
        reseller_pks = [
            obj.linked_reseller.pk
            for obj in instances
            if obj.linked_reseller is not None
        ]
        if not reseller_pks:
            self._linked_reseller_deletable_pks = set()
            return
        deletable, failed = bulk_deletable_pks(
            Reseller, reseller_pks, exclude_models=_RESELLER_DELETE_EXCLUDE
        )
        self._linked_reseller_deletable_pks = deletable
        self._linked_reseller_failed = failed


class DeliveryStationSerializer(
    DynamicContactFieldsMixin,
    DynamicDeliveryDayFieldsMixin,
    serializers.ModelSerializer,
):
    """Serializer for DeliveryStation with dynamic contact and day fields."""

    can_be_deleted = serializers.SerializerMethodField()
    tour_assignment_missing = serializers.BooleanField(read_only=True)
    # Tells the frontend whether the ``is_also_reseller`` / ``is_also_seller``
    # checkboxes can be unticked. False when the linked Reseller still has
    # dependants and would be orphaned by an unlink.
    linked_reseller_can_be_deleted = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_contact_fields(
            strict_required=False,
            handle_conflicts=True,
        )
        self._add_day_fields()

    class Meta:
        model = DeliveryStation
        fields = "__all__"
        # List path bulk-precomputes both deletability flags (one batch per
        # reverse relation) instead of running ``can_delete_instance`` per row.
        list_serializer_class = DeliveryStationListSerializer

    def get_can_be_deleted(self, obj) -> bool:
        """Check if this instance can be deleted"""
        # List path: the parent ListSerializer precomputed deletability for
        # every station on the page in one batch.
        parent = getattr(self, "parent", None)
        if (
            isinstance(parent, DeliveryStationListSerializer)
            and not parent._station_failed
            and parent._station_deletable_pks is not None
        ):
            return obj.pk in parent._station_deletable_pks
        # Detail / create / update path — single instance, single check.
        can_delete, _ = can_delete_instance(obj, exclude_models=_STATION_DELETE_EXCLUDE)
        return can_delete

    def get_linked_reseller_can_be_deleted(self, obj) -> bool:
        reseller = obj.linked_reseller
        if reseller is None:
            return True
        # List path: the parent ListSerializer precomputed linked-reseller
        # deletability for every station on the page in one batch.
        parent = getattr(self, "parent", None)
        if (
            isinstance(parent, DeliveryStationListSerializer)
            and not parent._linked_reseller_failed
            and parent._linked_reseller_deletable_pks is not None
        ):
            return reseller.pk in parent._linked_reseller_deletable_pks
        # Detail / create / update path — single instance, single check.
        can_delete, _ = can_delete_instance(
            reseller, exclude_models=_RESELLER_DELETE_EXCLUDE
        )
        return can_delete


# ========================================
# DELIVERY STATION DAY SERIALIZERS
# ========================================


class DeliveryStationDaySerializer(DeletableMixin, serializers.ModelSerializer):
    """
    Serializer for DeliveryStationDay CRUD operations.

    Supports dynamic variation fields for tour overview.
    """

    delivery_station_short_name = serializers.CharField(read_only=True)
    delivery_day_number = serializers.CharField(read_only=True)
    delivery_station_name = serializers.CharField(
        source="delivery_station.contact.name", read_only=True, allow_null=True
    )
    # Coordinates live on the linked ContactEntity; surface them read-only so a
    # single station-days fetch can drive the map picker without a second
    # request + client-side join. The viewset already
    # ``select_related("delivery_station__contact")``, so this is N+1-safe.
    coords_lat = serializers.DecimalField(
        source="delivery_station.contact.coords_lat",
        max_digits=12,
        decimal_places=10,
        read_only=True,
        allow_null=True,
    )
    coords_lon = serializers.DecimalField(
        source="delivery_station.contact.coords_lon",
        max_digits=12,
        decimal_places=10,
        read_only=True,
        allow_null=True,
    )
    capacity_by_week = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryStationDay
        fields = "__all__"

    def validate_capacity(self, value):
        """Floor a capacity edit at the busiest upcoming week's occupancy.

        The field stays freely editable up and down — the only constraint is
        that you can't drop the cap below the number of shares already booked
        (confirmed deliveries + active draft reservations) for any current or
        future week. ``None`` clears the limit (always allowed); on create
        there's nothing booked yet so the check is skipped.
        """
        if value is None or self.instance is None:
            return value

        from django.utils import timezone

        from ..errors import DeliveryStationCapacityBelowOccupancy
        from ..services.share_demand_service import ShareDemandService

        iso = timezone.now().date().isocalendar()
        peak, peak_year, peak_week = ShareDemandService.peak_occupied_from_week(
            delivery_station_day_id=self.instance.id,
            from_year=iso[0],
            from_week=iso[1],
        )
        if value < peak:
            raise DeliveryStationCapacityBelowOccupancy(
                capacity=value, peak=peak, year=peak_year, week=peak_week
            )
        return value

    def _get_year_and_weeks(self):
        """Return (year, start_week, num_weeks) from request params."""
        request = self.context.get("request")
        if not request:
            return None, None, 52
        parsed = validate_query_params(
            request,
            optional=["year", "delivery_week", "num_weeks"],
        )
        year = parsed["year"]
        start_week = parsed["delivery_week"]
        num_weeks = parsed["num_weeks"]
        if year is not None and start_week is not None:
            return year, start_week, num_weeks
        return None, None, 52

    # Returns a dict keyed by ``"<year>-<week>"`` strings, where each value
    # is ``{"occupied": int, "free": int}``. OpenAPI has no way to express
    # an open-ended string-keyed mapping precisely, so annotate as OBJECT.
    @staticmethod
    def _build_year_weeks(year, start_week, num_weeks):
        """Expand ``(year, start_week, num_weeks)`` into ISO-correct
        ``(iso_year, iso_week)`` pairs.

        Steps real Monday dates forward 7 days at a time, so the year /
        53-week rollover matches what ``date.isocalendar()`` (and the dayjs
        ``isoWeekYear``/``isoWeek`` the frontend uses) produce — e.g.
        ``…2026-52, 2026-53, 2027-1…`` — rather than the naive ``week-52``
        arithmetic that skips/duplicates weeks at the boundary.
        """
        from ..utils.iso_week_utils import iso_week_range

        # ``date.fromisocalendar`` raises on an out-of-range start_week (return
        # [] for that), whereas isoweek.Week silently normalises it — so keep
        # this explicit validation before delegating the iteration.
        try:
            date.fromisocalendar(year, start_week, 1)
        except ValueError:
            return []
        return iso_week_range(year, start_week, num_weeks)

    def _batched_capacity_counts(self, year_weeks):
        """Occupancy for every station-day in THIS serialization run, in one
        query. Cached on the shared child serializer so the per-row
        ``get_capacity_by_week`` doesn't re-query (kills the old N+1 where
        each row ran one ``.count()`` per week).
        """
        cached = getattr(self, "_capacity_counts_cache", None)
        if cached is not None:
            return cached

        from ..services.share_demand_service import ShareDemandService

        # ``self.parent.instance`` is the whole list/page under ``many=True``;
        # fall back to the single instance when serialized on its own.
        if self.parent is not None and self.parent.instance is not None:
            instances = list(self.parent.instance)
        else:
            instances = [self.instance]
        station_day_ids = [obj.id for obj in instances if getattr(obj, "id", None)]

        counts = ShareDemandService.capacity_counts_by_week(
            station_day_ids=station_day_ids,
            year_weeks=year_weeks,
        )
        self._capacity_counts_cache = counts
        return counts

    @extend_schema_field(
        # Precise shape instead of OpenApiTypes.OBJECT: the generic OBJECT
        # generated ``{[key: string]: unknown}`` and forced every frontend
        # consumer to hand-declare (and keep in sync) the {occupied, free}
        # entry shape. Keys are "<year>-<week>" strings; None when no
        # year/week context is on the request.
        serializers.DictField(child=CapacityWeekEntrySerializer(), allow_null=True)
    )
    def get_capacity_by_week(self, obj):
        year, start_week, num_weeks = self._get_year_and_weeks()
        if year is None or start_week is None:
            return None
        year_weeks = self._build_year_weeks(year, start_week, num_weeks)
        counts = self._batched_capacity_counts(year_weeks)
        result = {}
        for current_year, week in year_weeks:
            occupied = counts.get((obj.id, current_year, week), 0)
            free = None if obj.capacity is None else max(0, obj.capacity - occupied)
            result[f"{current_year}-{week}"] = {"occupied": occupied, "free": free}
        return result

    def to_representation(self, instance):
        """Allow dynamic variation_* fields for tour overview."""
        ret = super().to_representation(instance)

        # If dict data (from tour overview), preserve variation fields
        if isinstance(instance, dict):
            for key, value in instance.items():
                if key.startswith("variation_") and key not in ret:
                    ret[key] = value

        # Public registration (anonymous) reads: availability only — no exact
        # occupancy/cap, and no internal route logistics.
        mask_capacity_for_anonymous(
            ret,
            self.context.get("request"),
            internal_fields=("special_instructions", "tour_number", "stop_order"),
        )
        return ret


# ========================================
# TOUR UPDATE SERIALIZERS (POST/PUT)
# ========================================


class DeliveryTourPositionSerializer(serializers.Serializer):
    """Serializer for a single position in a tour (for updates)."""

    position = serializers.IntegerField(min_value=1)
    delivery_station_id = serializers.CharField()

    def validate_delivery_station_id(self, value):
        # Guard the WRITE path: update_tours feeds this id straight into
        # DeliveryStationDay.update_or_create, which doesn't full_clean — so a
        # bogus id would otherwise surface as a generic 409, not a field 400.
        from ..errors import DeliveryStationNotFound

        if not DeliveryStation.objects.filter(id=value).exists():
            raise DeliveryStationNotFound(
                message="Delivery station does not exist.",
                field="delivery_station_id",
            )
        return value


class DeliveryTourPositionResponseSerializer(serializers.Serializer):
    """Serializer for a single position in a tour (response)."""

    position = serializers.IntegerField()
    delivery_station_id = serializers.CharField()
    delivery_station_name = serializers.CharField()
    delivery_station_day_id = serializers.CharField()


class DeliveryTourResponseSerializer(serializers.Serializer):
    """Serializer for a single tour in the list response."""

    tour_number = serializers.IntegerField()
    positions = DeliveryTourPositionResponseSerializer(many=True)


class DeliveryTourUpdateSerializer(serializers.Serializer):
    """Serializer for updating a single tour (POST/PUT)."""

    tour_number = serializers.IntegerField(min_value=1)
    positions = DeliveryTourPositionSerializer(many=True)

    def validate_positions(self, positions):
        # Check for duplicate positions
        position_numbers = [pos["position"] for pos in positions]
        if len(position_numbers) != len(set(position_numbers)):
            raise serializers.ValidationError(
                "Duplicate positions are not allowed within the same tour"
            )

        # Check for duplicate stations
        station_ids = [pos["delivery_station_id"] for pos in positions]
        if len(station_ids) != len(set(station_ids)):
            raise serializers.ValidationError(
                "Duplicate delivery stations are not allowed within the same tour"
            )

        return positions


class DeliveryToursUpdateSerializer(serializers.Serializer):
    """Serializer for bulk tour updates (POST/PUT)."""

    delivery_day = serializers.CharField()
    tours = DeliveryTourUpdateSerializer(many=True)

    def validate_tours(self, tours):
        # Check for duplicate tour numbers
        tour_numbers = [tour["tour_number"] for tour in tours]
        if len(tour_numbers) != len(set(tour_numbers)):
            raise serializers.ValidationError("Duplicate tour numbers are not allowed")

        # Check for duplicate stations across all tours
        all_station_ids = []
        for tour in tours:
            for position in tour["positions"]:
                all_station_ids.append(position["delivery_station_id"])

        if len(all_station_ids) != len(set(all_station_ids)):
            raise serializers.ValidationError(
                "A delivery station cannot be assigned to multiple tours"
            )

        return tours


# ========================================
# TOUR OVERVIEW SERIALIZERS (GET)
# ========================================


class ShareTypeVariationMetadataSerializer(serializers.Serializer):
    """Metadata about a share type variation for tour overview."""

    id = serializers.CharField()
    share_type_id = serializers.CharField()
    share_type_name = serializers.CharField(help_text="Share type name (e.g., Gemüse)")
    size = serializers.CharField(help_text="Variation size (S, M, L, etc.)")
    display_name = serializers.CharField()
    key = serializers.CharField(
        help_text="Key in station objects (e.g., variation_k3m9P2nQx7YZ)"
    )


class StationOverviewSerializer(serializers.Serializer):
    """Stable fields of a single station in the tour overview (GET).

    In addition to the stable fields below, each station dict carries dynamic
    keys read by iteration on the frontend (not declared here): per-variation
    ``variation_<share_type_variation_id>`` counts AND per-box-combination
    ``combo_<key>`` counts. A plain declared-field ``Serializer`` would DROP
    these undeclared keys, so ``to_representation`` re-attaches them.
    """

    delivery_station_day_id = serializers.CharField()
    delivery_station_id = serializers.CharField()
    delivery_station_name = serializers.CharField(allow_null=True)
    delivery_station_short_name = serializers.CharField(
        allow_null=True, allow_blank=True
    )
    stop_order = serializers.IntegerField(allow_null=True)
    capacity = serializers.IntegerField(allow_null=True)
    pickup_time_begin = serializers.TimeField(allow_null=True)
    pickup_time_end = serializers.TimeField(allow_null=True)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Re-attach the dynamic per-variation / per-combination count keys the
        # declared fields above would otherwise strip.
        if isinstance(instance, dict):
            for key, value in instance.items():
                if key.startswith(("variation_", "combo_")) and key not in ret:
                    ret[key] = value
        return ret


class TourOverviewSerializer(serializers.Serializer):
    """Serializer for a tour in the overview (GET)."""

    tour_number = serializers.IntegerField()
    # Box-combination columns for THIS tour (they differ across tours). The
    # station rows carry matching dynamic ``combo_<key>`` counts.
    columns = PackingBoxesMatrixColumnSerializer(many=True)
    stations = StationOverviewSerializer(
        many=True,
        help_text="List of stations with dynamic variation_* + combo_* fields",
    )


class DeliveryStationsToursOverviewResponseSerializer(serializers.Serializer):
    """Complete response for delivery stations and tours overview (GET)."""

    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField(help_text="ISO week number (1-53)")
    day_number = serializers.IntegerField(help_text="Day of week (0=Monday, 6=Sunday)")
    delivery_day_id = serializers.CharField()
    number_of_tours = serializers.IntegerField()
    # Only tours with box combinations (deliveries) are returned; each carries
    # its own ``columns``. Iterate ``tours`` directly rather than 1..number_of_tours.
    tours = TourOverviewSerializer(many=True)
    variations = ShareTypeVariationMetadataSerializer(many=True)


class WeeklyComboMatrixRowSerializer(serializers.Serializer):
    """One AmountShares row: a delivery day, optionally split per tour or per
    delivery station. Besides the stable fields below it carries dynamic count
    keys matching the ``columns`` — ``combo_<key>`` for subscription box
    combinations, ``variation_<id>`` for the flat per-variation (import) columns;
    a plain declared-field ``Serializer`` would drop them, so ``to_representation``
    re-attaches them."""

    id = serializers.CharField()
    day_number = serializers.IntegerField(help_text="Day of week (0=Monday, 6=Sunday)")
    tour = serializers.IntegerField(allow_null=True)
    delivery_station_id = serializers.CharField(allow_null=True)
    delivery_station_name = serializers.CharField(allow_null=True, allow_blank=True)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if isinstance(instance, dict):
            for key, value in instance.items():
                if key.startswith(("combo_", "variation_")) and key not in ret:
                    ret[key] = value
        return ret


class WeeklyComboMatrixResponseSerializer(serializers.Serializer):
    """Whole-week box-combination matrix for AmountShares — the SAME box
    combination ``columns`` as PackingListBoxes, with one ROW per delivery day
    (or day × tour / day × station)."""

    columns = PackingBoxesMatrixColumnSerializer(many=True)
    rows = WeeklyComboMatrixRowSerializer(many=True)


# ========================================
# DELIVERY EXCEPTION ("Lieferpause") SERIALIZER
# ========================================


class DeliveryExceptionPeriodSerializer(serializers.ModelSerializer):
    """A whole-week ``[valid_from (Monday) … valid_until (Sunday)]`` range during
    which a ShareTypeVariation is not delivered. Bounds must align to whole
    weeks and must not overlap another pause for the same variation."""

    share_type_variation_string = serializers.SerializerMethodField()
    # A pause must be a bounded whole-week range. The model's ``valid_until`` is
    # nullable (TimeBoundMixin allows open-ended rows), but an open-ended pause
    # is meaningless here — it suppresses nothing (weeks_in_range(from, None) is
    # empty) and would make paused_weeks_for_variation compare against None.
    # Require it at the API boundary.
    valid_until = serializers.DateField(required=True, allow_null=False)
    # Read-only: lets the UI grey out the edit/delete affordances on a pause that
    # has already started (the write endpoints reject those anyway).
    is_locked = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryExceptionPeriod
        fields = [
            "id",
            "share_type_variation",
            "share_type_variation_string",
            "valid_from",
            "valid_until",
            "note",
            "is_locked",
        ]

    def get_share_type_variation_string(self, obj: DeliveryExceptionPeriod) -> str:
        # Combined "ShareType - Size" label — matches the abos tables' variation
        # column (``SubscriptionSerializer.share_type_variation_string``) so a
        # pause reads the same way as the subscription it affects.
        variation = obj.share_type_variation
        if variation is None:
            return ""
        return f"{variation.share_type.name} - {variation.size}"

    def get_is_locked(self, obj: DeliveryExceptionPeriod) -> bool:
        return obj.has_started() if obj.valid_from else False

    def to_representation(self, instance: DeliveryExceptionPeriod) -> dict:
        data = super().to_representation(instance)
        # ``note`` is an office-internal free-text field (authored + shown only
        # on the staff-gated ListDeliveryExceptions page). Members may read a
        # pause's dates for their own subscriptions, but never the office note —
        # drop it for non-staff (and fail closed when there's no request).
        request = self.context.get("request")
        if request is None or not has_any_role(request, *IsStaff.required_roles):
            data.pop("note", None)
        return data

    def validate(self, attrs: dict) -> dict:
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get(
            "valid_until", getattr(self.instance, "valid_until", None)
        )
        variation = attrs.get(
            "share_type_variation",
            getattr(self.instance, "share_type_variation", None),
        )

        # A started (active or past) pause is frozen — reject any edit up front so
        # the office gets a clean 409 instead of a partial resync.
        if self.instance is not None and self.instance.has_started():
            raise DeliveryExceptionPeriodLocked(
                "This delivery pause has already started and can no longer be "
                "changed or deleted."
            )
        # Keep pauses entirely in the future: a pause starting today-or-earlier is
        # (partly) already running, which the future-only resync can't suppress —
        # and it would be frozen on arrival by the rule above.
        if valid_from and valid_from <= timezone.localdate():
            raise DeliveryExceptionInvalidRange(
                "valid_from must be in the future.", field="valid_from"
            )

        if valid_from and valid_from.weekday() != 0:
            raise DeliveryExceptionInvalidRange(
                "valid_from must be a Monday.", field="valid_from"
            )
        if valid_until and valid_until.weekday() != 6:
            raise DeliveryExceptionInvalidRange(
                "valid_until must be a Sunday.", field="valid_until"
            )
        if valid_from and valid_until and valid_until < valid_from:
            raise DeliveryExceptionInvalidRange(
                "valid_until must be on or after valid_from.", field="valid_until"
            )

        if variation and valid_from and valid_until:
            overlapping = DeliveryExceptionPeriod.objects.filter(
                share_type_variation=variation,
                valid_from__lte=valid_until,
                valid_until__gte=valid_from,
            )
            if self.instance is not None:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            if overlapping.exists():
                raise DeliveryExceptionOverlap(
                    "This variation already has an overlapping delivery-exception "
                    "period.",
                    field="valid_from",
                )
        return attrs


# ========================================
# DELIVERY STATION FEES (read-only report)
# ========================================


class DeliveryStationFeesLineSerializer(serializers.Serializer):
    """One per-week box-count line (only populated for per_box stations)."""

    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField()
    boxes = serializers.IntegerField()


class DeliveryStationFeesSerializer(serializers.Serializer):
    """What the solawi owes one pickup station over a date range. Money is NET
    and sent as 2-decimal strings."""

    delivery_station = serializers.CharField()
    delivery_station_name = serializers.CharField(allow_null=True)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    fee_type = serializers.ChoiceField(
        choices=["per_box", "per_month", "per_year", "none"]
    )
    quantity = serializers.IntegerField()
    quantity_unit = serializers.CharField(allow_blank=True)
    rate_net = serializers.CharField()
    total_net = serializers.CharField()
    lines = DeliveryStationFeesLineSerializer(many=True)
