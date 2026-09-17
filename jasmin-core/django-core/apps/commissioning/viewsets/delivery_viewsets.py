from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
)
from isoweek import Week
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import (
    IsOffice,
    IsStaff,
    IsStaffOrMember,
    RolePermissionsMixin,
    has_any_role,
)
from apps.authz.scoping import enforce_owner
from core.serializers import ErrorResponseSerializer

from ..errors import (
    DeliveryDayNotFound,
    DeliveryDayValidFromInPast,
    DeliveryDayValidFromMoveIntoPast,
    DeliveryExceptionPeriodLocked,
    DeliveryStationDayShorteningStrandsChildren,
    DeliveryStationDayStartMoveStrandsChildren,
    DeliveryStationDayStartsBeforeDeliveryDay,
)
from ..models import (
    CapacityReservation,
    DeliveryExceptionPeriod,
    DeliveryStation,
    DeliveryStationDay,
    ShareDelivery,
    SharesDeliveryDay,
    Subscription,
)
from ..schemas import (
    catalogue_param,
    get_active_at_date_or_future_parameter,
    get_active_at_date_parameter,
    get_delivery_day_parameter,
    get_delivery_station_parameter,
    get_delivery_week_parameter,
    get_is_active_parameter,
    get_member_parameter,
    get_share_type_variation_parameter,
    get_year_parameter,
)
from ..serializers import (
    DeliveryExceptionPeriodSerializer,
    DeliveryStationDaySerializer,
    DeliveryStationSerializer,
    DeliveryTourResponseSerializer,
    DeliveryToursUpdateSerializer,
)
from ..services import (
    DefaultShareContentService,
    ResellerAndDeliveryStationService,
)
from ..services.delivery_exceptions import (
    resync_delivery_exception,
)
from ..services.onboarding_policy import onboarding_mode_enabled
from ..utils import get_contact_annotations
from ..utils.iso_week_utils import previous_monday, weeks_in_range
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params

logger = logging.getLogger(__name__)


# Contact fields whose rewrite needs a fresh identity proof.
_STEP_UP_CONTACT_FIELDS = ("iban",)


def _payload_sets_a_step_up_field(request: Request | None) -> bool:
    """True when the write body puts a non-empty value on a gated contact field.

    An empty string or ``null`` sets no bank account, so it is not a value the
    step-up challenge is there to protect.
    """
    data = getattr(request, "data", None) or {}
    return any(str(data.get(field) or "").strip() for field in _STEP_UP_CONTACT_FIELDS)


class DeliveryStationViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    # Members may READ delivery stations (their own page's stations card shows
    # pickup info / messenger link / map). Writes stay office-only.
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    serializer_class = DeliveryStationSerializer

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.service = ResellerAndDeliveryStationService()

    def get_permissions(self):
        from apps.accounts.permissions import requires_step_up_for_fields

        # A station writes through to its ContactEntity, the same row a linked
        # reseller shares — so rewriting the IBAN here redirects money just as
        # it does on the reseller, and trips the same step-up modal. Every
        # other station edit passes unprompted. On an update the gate compares
        # the submitted value with the stored one, so an unchanged IBAN is
        # free; a create has nothing to compare against and the gate there
        # fires on the key alone, so it is only attached when the payload
        # carries an actual bank account — a blank or null ``iban`` sets none.
        permissions = super().get_permissions()
        if self.action in {"update", "partial_update"} or (
            self.action == "create" and _payload_sets_a_step_up_field(self.request)
        ):
            permissions.append(requires_step_up_for_fields(*_STEP_UP_CONTACT_FIELDS)())
        return permissions

    @extend_schema(
        parameters=[
            get_is_active_parameter(),
            get_delivery_day_parameter(required=False),
            get_member_parameter(required=False),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[DeliveryStation]:
        # drf-spectacular sets ``swagger_fake_view`` while introspecting
        # the URL conf to build the OpenAPI schema. That introspection
        # runs on the public schema where tenant tables like
        # ``commissioning_sharesdeliveryday`` don't exist, so the
        # contact-annotation join below would crash. Returning an empty
        # queryset is the documented opt-out; the serializer class still
        # gets discovered via ``self.serializer_class``.
        if getattr(self, "swagger_fake_view", False):
            return DeliveryStation.objects.none()

        # ``linked_reseller`` (forward OneToOne) is dereferenced per row by
        # ``DeliveryStationSerializer.get_linked_reseller_can_be_deleted``;
        # select_related it so that access is query-free (otherwise it's an
        # extra query per station). Deletability itself is bulk-precomputed
        # by ``DeliveryStationListSerializer`` — locked by
        # apps/commissioning/tests/tests_viewsets/test_delivery_station_query_count.py.
        queryset = DeliveryStation.objects.select_related(
            "contact", "linked_reseller"
        ).all()

        params = validate_query_params(
            self.request, optional=["is_active", "delivery_day", "member"]
        )
        is_active = params["is_active"]
        delivery_day = params["delivery_day"]
        member = params["member"]
        # A non-staff member may only scope to their OWN stations — reject a
        # crafted ?member=<other id> so the member↔station association can't be
        # read cross-member. Staff (office/admin/…) bypass and may target anyone.
        # No ``member`` param = the plain (member-visible) station catalogue, so
        # only enforce when one is supplied.
        if member is not None:
            enforce_owner(
                self.request,
                member,
                user_attr="member_profile",
                privileged_roles=IsStaff.required_roles,
            )

        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        if delivery_day is not None:
            queryset = queryset.filter(deliverystationday__delivery_day=delivery_day)

        # Scope to the stations a member is subscribed to — the default station of
        # their active/upcoming confirmed subscriptions. ``default_delivery_station_day``
        # has related_name="+" (no reverse accessor), so filter FORWARD from
        # Subscription into a distinct station-id subquery rather than reverse-
        # joining (which also keeps the outer queryset free of row multiplication).
        if member is not None:
            today = timezone.now().date()
            member_station_ids = (
                Subscription.objects.filter(member=member, admin_confirmed=True)
                .filter(cancelled_at__isnull=True)
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
                .filter(default_delivery_station_day__isnull=False)
                .values_list(
                    "default_delivery_station_day__delivery_station", flat=True
                )
                .distinct()
            )
            queryset = queryset.filter(id__in=member_station_ids)

        contact_annotations = get_contact_annotations()
        queryset = queryset.annotate(**contact_annotations)

        return queryset

    @extend_schema(
        description="Create a delivery station with optional linked contact/reseller."
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        delivery_station = self.service.create_delivery_station(
            serializer.validated_data
        )
        updated_instance = self.get_queryset().get(pk=delivery_station.pk)
        response_serializer = self.get_serializer(updated_instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description="Update a delivery station and its linked contact/reseller."
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        updated_instance = self.service.update_delivery_station(
            instance, serializer.validated_data
        )
        annotated_instance = self.get_queryset().get(pk=updated_instance.pk)
        response_serializer = self.get_serializer(annotated_instance)
        return Response(response_serializer.data)

    @extend_schema(
        description="Delete a delivery station, cleaning up orphaned contacts/resellers."
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        self.service.delete_delivery_station(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeliveryToursViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """ViewSet for managing delivery tour orders and positions."""

    read_permission = IsStaff
    write_permission = IsOffice
    # Pure ViewSet — every @action below has its own @extend_schema.
    # Class-level placeholder silences spectacular's "unable to guess
    # serializer" warning without affecting the actual schema.
    serializer_class = DeliveryTourResponseSerializer

    @extend_schema(
        parameters=[
            get_delivery_day_parameter(required=True),
        ],
        responses=DeliveryTourResponseSerializer(many=True),
        description="Get delivery tours grouped by tour number for a delivery day.",
    )
    def list(self, request: Request) -> Response:
        params = validate_query_params(request, required=["delivery_day"])
        delivery_day = params["delivery_day"]

        delivery_station_days = (
            DeliveryStationDay.objects.filter(
                delivery_day__id=delivery_day,
                stop_order__isnull=False,
            )
            .select_related(
                "delivery_station", "delivery_day", "delivery_station__contact"
            )
            .order_by("tour_number", "stop_order")
        )

        tours_data: dict[int, dict[str, Any]] = {}
        for delivery_station_day in delivery_station_days:
            tour_num = delivery_station_day.tour_number
            if tour_num not in tours_data:
                tours_data[tour_num] = {"tour_number": tour_num, "positions": []}

            tours_data[tour_num]["positions"].append(
                {
                    "position": delivery_station_day.stop_order,
                    "delivery_station_id": str(
                        delivery_station_day.delivery_station.id
                    ),
                    "delivery_station_name": (
                        delivery_station_day.delivery_station.contact.name
                        if delivery_station_day.delivery_station.contact
                        else f"Station {delivery_station_day.delivery_station.id}"
                    ),
                    "delivery_station_day_id": str(delivery_station_day.id),
                }
            )

        # Serialize through the declared serializer so the response is enforced
        # against the documented schema rather than shipping raw dicts.
        serializer = DeliveryTourResponseSerializer(
            list(tours_data.values()), many=True
        )
        return Response(serializer.data)

    @extend_schema(
        request=DeliveryToursUpdateSerializer,
        responses={
            200: inline_serializer(
                name="UpdateToursResponse",
                fields={"message": drf_serializers.CharField()},
            ),
            404: ErrorResponseSerializer,
        },
        description="Bulk-update tour assignments for delivery stations on a given day.",
    )
    @action(detail=False, methods=["post"])
    def update_tours(self, request: Request) -> Response:
        serializer = DeliveryToursUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        delivery_day_id: str = data["delivery_day"]
        tours: list[dict[str, Any]] = data["tours"]

        shares_delivery_day = get_or_404(
            SharesDeliveryDay,
            delivery_day_id,
            "Delivery day",
            error_cls=DeliveryDayNotFound,
        )

        # The start a newly assigned station-day opens on. Clamped up to the
        # delivery day's own start so a tour built on a future-dated day does
        # not mint a station-day active on weeks that day does not run — the
        # window rule perform_create/perform_update enforce, which this path
        # bypasses by writing the model directly. Both operands are Mondays, as
        # valid_from must be.
        assignment_valid_from = max(
            previous_monday(timezone.localdate()), shares_delivery_day.valid_from
        )

        with transaction.atomic():
            # Only the CURRENTLY-OPEN station-day per (station, day) carries the
            # live tour assignment. DeliveryStationDay is TimeBoundMixin: closed
            # historical rows (valid_until set) legitimately coexist with the one
            # open row, so scope every write here to valid_until IS NULL. Without
            # it the reset below would rewrite tour_number/stop_order on closed
            # history rows, and the update_or_create further down would match
            # multiple rows on its implicit get() and raise MultipleObjectsReturned.
            all_delivery_station_days = DeliveryStationDay.objects.filter(
                delivery_day=shares_delivery_day, valid_until__isnull=True
            ).select_for_update()

            station_ids_in_tours: set[str] = set()
            for tour in tours:
                for position in tour["positions"]:
                    station_ids_in_tours.add(position["delivery_station_id"])

            all_delivery_station_days.exclude(
                delivery_station_id__in=station_ids_in_tours
            ).update(tour_number=1, stop_order=None)

            created_station_days: list[DeliveryStationDay] = []
            for tour in tours:
                tour_number: int = tour["tour_number"]
                for position in tour["positions"]:
                    # Scope the implicit get() to the open row (see comment
                    # above): a versioned (station, day) has >1 row and an
                    # unscoped update_or_create would raise MultipleObjectsReturned.
                    # The valid_until filter narrows the lookup only; a genuinely
                    # new station-day still creates an open row (valid_until NULL).

                    station_day, created = DeliveryStationDay.objects.filter(
                        valid_until__isnull=True
                    ).update_or_create(
                        delivery_station_id=position["delivery_station_id"],
                        delivery_day=shares_delivery_day,
                        defaults={
                            "tour_number": tour_number,
                            "stop_order": position["position"],
                            # Required on create: TimeBoundMixin.valid_from is
                            # NOT NULL with no default, and full_clean() also
                            # enforces the project-wide "valid_from is always a
                            # Monday" invariant, so omitting it makes the create
                            # branch a 400 "Validation failed". The current
                            # week's Monday (clamped — see above), because the
                            # update branch takes effect immediately (it just
                            # re-stamps the open row) and a newly assigned
                            # station should not behave differently from a
                            # reassigned one.
                            "valid_from": assignment_valid_from,
                        },
                    )
                    if created:
                        created_station_days.append(station_day)

            # A station newly added to a tour starts delivering — fan the
            # existing long-term plan (honey, etc.) out to it so its shares
            # are theoretically delivered there too. Future weeks only.
            for station_day in created_station_days:
                DefaultShareContentService.materialize_for_new_station_day(station_day)

        return Response(
            {"message": "Tours updated successfully"},
            status=status.HTTP_200_OK,
        )


def _bound_station_day(serializer: Any) -> DeliveryStationDay:
    """The station-day a BOUND serializer is updating.

    DRF types ``BaseSerializer.instance`` as ``Any | None`` because one
    serializer class serves both create (unbound) and update (bound).
    ``perform_update`` only ever runs bound, so the read is safe — taken once
    here, typed, instead of at every attribute access below.
    """
    return serializer.instance


class DeliveryStationDayViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    # Members read this to pick their delivery station + day combo in
    # the subscription flow on their MemberDetail page. Write stays
    # office-only (the schedule itself is configured by staff).
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    # Public registration wizard lists pickup stations + days (name, address,
    # coords, advisory capacity) to prospective anonymous members. LIST only —
    # retrieve/write stay member/office-gated. No PII beyond public pickup info.
    public_read_actions = frozenset({"list"})
    serializer_class = DeliveryStationDaySerializer

    @transaction.atomic
    def perform_create(self, serializer: DeliveryStationDaySerializer) -> None:
        # A new station-day means a station starts delivering — fan the
        # existing long-term plan out to it (future weeks only) so its shares
        # are theoretically delivered at the new station without re-running
        # planning by hand.
        valid_from = serializer.validated_data.get("valid_from")
        today = timezone.now().date()
        if valid_from and valid_from < today:
            raise DeliveryDayValidFromInPast(
                "Cannot create a station-day with valid_from in the past.",
                field="valid_from",
            )

        # A station-day lives inside its delivery day's window (the same rule
        # perform_update applies to a move): opening before the day's own start
        # would make it active on weeks the day does not run. Enforced here too
        # because a future-dated delivery day is offered alongside a valid_from
        # picker that only bounds the date at today — and once the row is saved
        # the office UI locks both fields, so an out-of-window row could not be
        # repaired from there.
        delivery_day = serializer.validated_data.get("delivery_day")
        if (
            valid_from
            and delivery_day is not None
            and valid_from < delivery_day.valid_from
        ):
            raise DeliveryStationDayStartsBeforeDeliveryDay(
                station_day=(
                    f"{serializer.validated_data.get('delivery_station')} - "
                    f"{delivery_day}"
                ),
                new_valid_from=valid_from,
                delivery_day=str(delivery_day),
                delivery_day_valid_from=delivery_day.valid_from,
            )

        station_day = serializer.save()
        DefaultShareContentService.materialize_for_new_station_day(station_day)

        # Creating a station-day for an EXISTING (station, day) pair runs
        # TimeBoundMixin.handle_succession, which CLOSES the open predecessor at
        # valid_from-1 — but nothing re-points the future ShareDeliveries /
        # CapacityReservations already materialized against it. Occupancy is
        # strictly delivery_station_day_id-keyed, so a stranded row would count
        # under the closed id while the new DSD shows the slot free (over-book).
        # Migrate post-boundary children onto the per-week-active successor.
        self._migrate_succession_children(station_day, valid_from)

    @staticmethod
    def _migrate_succession_children(
        station_day: DeliveryStationDay, valid_from: Any
    ) -> None:
        if valid_from is None:
            return
        today = timezone.now().date()
        predecessor = (
            DeliveryStationDay.objects.filter(
                delivery_station_id=station_day.delivery_station_id,
                delivery_day_id=station_day.delivery_day_id,
                valid_until=valid_from - timedelta(days=1),
            )
            .exclude(pk=station_day.pk)
            .order_by("-valid_until")
            .first()
        )
        if predecessor is None:
            return

        # The successor chain for this (station, day) covering weeks >= boundary
        # — resolve each child to the DSD active at ITS OWN week (the new day may
        # be a chain: the just-created row + later-dated rows).
        successors = list(
            DeliveryStationDay.objects.filter(
                delivery_station_id=station_day.delivery_station_id,
                delivery_day_id=station_day.delivery_day_id,
            ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=valid_from))
            # Deterministic tie-break — latest valid_from wins — matching the
            # materialisation path (_find_active_delivery_station_day). Without
            # it, a race-produced brief overlap could re-point migrated children
            # to a DIFFERENT DSD than the one deliveries materialise onto
            # (split per-DSD counts).
            .order_by("-valid_from")
        )

        def _resolve(monday):
            for delivery_station_day in successors:
                if delivery_station_day.valid_from <= monday and (
                    delivery_station_day.valid_until is None
                    or delivery_station_day.valid_until >= monday
                ):
                    return delivery_station_day
            return None

        affected_share_ids: set[str] = set()

        # Future ShareDeliveries stranded past the predecessor's new end.
        deliveries_to_update = []
        for share_delivery in ShareDelivery.objects.filter(
            delivery_station_day=predecessor
        ).select_related("share"):
            monday = Week(
                share_delivery.share.year, share_delivery.share.delivery_week
            ).monday()
            if monday < valid_from or monday <= today:
                continue  # still within the predecessor's window / not future
            resolved = _resolve(monday)
            if (
                resolved is not None
                and resolved.id != share_delivery.delivery_station_day_id
            ):
                share_delivery.delivery_station_day = resolved
                deliveries_to_update.append(share_delivery)
                if share_delivery.share_id:
                    affected_share_ids.add(share_delivery.share_id)
        if deliveries_to_update:
            ShareDelivery.objects.bulk_update(
                deliveries_to_update, fields=["delivery_station_day"]
            )

        # Future CapacityReservations likewise.
        reservations_to_update = []
        for reservation in CapacityReservation.objects.filter(
            delivery_station_day=predecessor
        ):
            monday = Week(reservation.year, reservation.week).monday()
            if monday < valid_from:
                continue
            resolved = _resolve(monday)
            if (
                resolved is not None
                and resolved.id != reservation.delivery_station_day_id
            ):
                reservation.delivery_station_day = resolved
                reservations_to_update.append(reservation)
        if reservations_to_update:
            CapacityReservation.objects.bulk_update(
                reservations_to_update, fields=["delivery_station_day"]
            )

        if affected_share_ids:
            from ..services.recompute import recompute_shares

            recompute_shares(affected_share_ids)

    def perform_update(self, serializer: DeliveryStationDaySerializer) -> None:
        # Mirror the SharesDeliveryDay guard for station-days: a standalone
        # close/shorten via a direct
        # PATCH would strand this DSD's future ShareDeliveries / CapacityReservations
        # — the create/succession path migrates them (perform_create above), a bare
        # close does not. Block it; the office should succeed via a NEW station-day.
        # (In perform_update, not clean(), because the create path closes the
        # predecessor via handle_succession→save()→clean() BEFORE the migration
        # runs — guarding clean() would break legitimate succession.)
        instance = _bound_station_day(serializer)
        new_valid_until = serializer.validated_data.get(
            "valid_until", instance.valid_until
        )
        is_closing_or_shortening = new_valid_until is not None and (
            instance.valid_until is None or new_valid_until < instance.valid_until
        )
        if is_closing_or_shortening:
            vu_week = Week.withdate(new_valid_until)
            stranded = (
                ShareDelivery.objects.filter(delivery_station_day=instance)
                .filter(
                    Q(share__year__gt=vu_week.year)
                    | Q(
                        share__year=vu_week.year,
                        share__delivery_week__gt=vu_week.week,
                    )
                )
                .count()
            )
            stranded += (
                CapacityReservation.objects.filter(delivery_station_day=instance)
                .filter(
                    Q(year__gt=vu_week.year)
                    | Q(year=vu_week.year, week__gt=vu_week.week)
                )
                .count()
            )
            if stranded:
                raise DeliveryStationDayShorteningStrandsChildren(
                    station_day=str(instance),
                    new_valid_until=new_valid_until,
                    stranded_count=stranded,
                )

        # Moving the start into a past week re-opens weeks that have already
        # been delivered and billed, so it is refused — except while the tenant
        # is onboarding, where the office enters a pickup schedule that has been
        # running on paper for a while. The flag is read here rather than in the
        # model: recomputes must keep behaving the same when it flips. Only a
        # CHANGED start is judged, so editing the capacity or the pickup times
        # of a long-running row stays possible.
        current_valid_from = instance.valid_from
        new_valid_from = serializer.validated_data.get("valid_from", current_valid_from)
        if (
            new_valid_from != current_valid_from
            and new_valid_from < previous_monday(timezone.localdate())
            and not onboarding_mode_enabled()
        ):
            raise DeliveryDayValidFromMoveIntoPast(
                "Cannot move a station-day's valid_from into a past week.",
                field="valid_from",
            )

        # A station-day lives inside its delivery day's window: reaching back
        # past the day's own start would make it active on weeks the day does
        # not run. The no-overlap check is scoped to (station, delivery_day), so
        # a row moved earlier can shadow a sibling on an OLDER delivery-day row
        # without tripping it. Judged only when the request actually moves the
        # start or repoints the day, in every mode — an already-out-of-window
        # historical row stays editable.
        delivery_day = serializer.validated_data.get(
            "delivery_day", instance.delivery_day
        )
        start_or_day_changed = (
            new_valid_from != current_valid_from
            or delivery_day.pk != instance.delivery_day_id
        )
        if start_or_day_changed and new_valid_from < delivery_day.valid_from:
            raise DeliveryStationDayStartsBeforeDeliveryDay(
                station_day=str(instance),
                new_valid_from=new_valid_from,
                delivery_day=str(delivery_day),
                delivery_day_valid_from=delivery_day.valid_from,
            )

        # Mirror at the other end of the window: moving valid_from LATER leaves
        # the deliveries/reservations before the new start with no station-day
        # covering them. They keep pointing at this row (the migration runs only
        # on the create/succession path), so they are orphaned rather than
        # re-homed. Moving the start EARLIER only widens the window, in every
        # mode.
        if new_valid_from > current_valid_from:
            vf_week = Week.withdate(new_valid_from)
            stranded = (
                ShareDelivery.objects.filter(delivery_station_day=instance)
                .filter(
                    Q(share__year__lt=vf_week.year)
                    | Q(
                        share__year=vf_week.year,
                        share__delivery_week__lt=vf_week.week,
                    )
                )
                .count()
            )
            stranded += (
                CapacityReservation.objects.filter(delivery_station_day=instance)
                .filter(
                    Q(year__lt=vf_week.year)
                    | Q(year=vf_week.year, week__lt=vf_week.week)
                )
                .count()
            )
            if stranded:
                raise DeliveryStationDayStartMoveStrandsChildren(
                    station_day=str(instance),
                    new_valid_from=new_valid_from,
                    stranded_count=stranded,
                )
        serializer.save()

    def perform_destroy(self, instance: DeliveryStationDay) -> None:
        # ShareDelivery.delivery_station_day CASCADEs — deleting a used pickup
        # day would silently wipe the deliveries that back billing/history with
        # no recompute. Refuse while any delivery references it (mirrors the
        # close/shorten guard in perform_update, which blocks the milder op).
        from ..errors import DeliveryStationDayInUse

        delivery_count = ShareDelivery.objects.filter(
            delivery_station_day=instance
        ).count()
        if delivery_count:
            raise DeliveryStationDayInUse(
                station_day=str(instance), delivery_count=delivery_count
            )
        instance.delete()

    @extend_schema(
        parameters=[
            get_active_at_date_parameter(),
            get_active_at_date_or_future_parameter(),
            get_delivery_station_parameter(),
            get_delivery_day_parameter(required=False),
            get_member_parameter(required=False),
            get_year_parameter(required=False),
            get_delivery_week_parameter(required=False),
            catalogue_param(
                "num_weeks",
                required=False,
                description="Number of weeks to return capacity for (default: 52)",
            ),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[DeliveryStationDay]:
        params = validate_query_params(
            self.request,
            optional=[
                "active_at_date",
                "active_at_date_or_future",
                "delivery_station",
                "delivery_day",
                "member",
            ],
        )
        active_at_date = params["active_at_date"]
        active_at_date_or_future = params["active_at_date_or_future"]
        delivery_station = params["delivery_station"]
        delivery_day = params["delivery_day"]
        member = params["member"]

        if getattr(self, "action", None) == "list":
            # The capacity window (year / delivery_week / num_weeks) is read by
            # the SERIALIZER, once per row. On a week with no rows nothing ever
            # looks at it, so a malformed value passes silently there while the
            # same call against a populated week 400s. Validate it here, where
            # the answer doesn't depend on how many rows come back.
            validate_query_params(
                self.request, optional=["year", "delivery_week", "num_weeks"]
            )
        # A non-staff member may only scope to their OWN station-days — reject a
        # crafted ?member=<other id>. Staff bypass. ``member is None`` (the
        # subscription-selector's "list all station-days" call) is allowed.
        if member is not None:
            enforce_owner(
                self.request,
                member,
                user_attr="member_profile",
                privileged_roles=IsStaff.required_roles,
            )

        _select = ("delivery_station", "delivery_day", "delivery_station__contact")

        if active_at_date is not None:
            queryset = (
                DeliveryStationDay.current.active_at_date(active_at_date)
                .select_related(*_select)
                .all()
            )
        elif active_at_date_or_future is not None:
            queryset = (
                DeliveryStationDay.current.active_at_date_or_future(
                    active_at_date_or_future
                )
                .select_related(*_select)
                .all()
            )
        else:
            queryset = DeliveryStationDay.objects.select_related(*_select).all()

        if delivery_station is not None:
            queryset = queryset.filter(delivery_station_id=delivery_station)

        if delivery_day is not None:
            queryset = queryset.filter(delivery_day=delivery_day)

        # Scope to the station-days a member is assigned to (their MemberDetail
        # "delivery stations" card lists these station×weekday combos). Two
        # sources, unioned:
        #   (a) the ``default_delivery_station_day`` of their active/upcoming
        #       confirmed subscriptions, and
        #   (b) any station-day they reassigned on an individual UPCOMING
        #       ShareDelivery (a per-delivery override of the subscription
        #       default — the member changed where one week's box goes).
        # ``default_delivery_station_day`` has related_name="+" (no reverse
        # accessor), so filter FORWARD from Subscription for (a).
        if member is not None:
            today = timezone.now().date()
            subscription_station_day_ids = (
                Subscription.objects.filter(member=member, admin_confirmed=True)
                .filter(cancelled_at__isnull=True)
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
                .filter(default_delivery_station_day__isnull=False)
                .values_list("default_delivery_station_day", flat=True)
            )
            current_week = Week.withdate(today)
            delivery_override_station_day_ids = (
                ShareDelivery.objects.filter(subscription__member=member)
                .filter(subscription__cancelled_at__isnull=True)
                .filter(
                    Q(share__year__gt=current_week.year)
                    | Q(
                        share__year=current_week.year,
                        share__delivery_week__gte=current_week.week,
                    )
                )
                .filter(delivery_station_day__isnull=False)
                .values_list("delivery_station_day", flat=True)
            )
            queryset = queryset.filter(
                Q(id__in=subscription_station_day_ids)
                | Q(id__in=delivery_override_station_day_ids)
            )

        queryset = queryset.annotate(
            delivery_station_short_name=F("delivery_station__short_name"),
            delivery_day_number=F("delivery_day__day_number"),
        )
        return queryset.order_by("delivery_day__day_number", "-valid_from")


class DeliveryExceptionPeriodViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """CRUD for delivery exceptions ("Lieferpausen"). Office writes; members
    read (so a member can see the pauses that affect their subscription).

    Every mutation resyncs the ALREADY-confirmed subscriptions of the affected
    variation: a created/extended pause deletes their future deliveries in the
    newly-paused weeks; a deleted/shortened pause re-materialises them in the
    freed weeks. Both recompute the affected shares and re-plan charges (future
    weeks only — an issued/paid week is never retro-edited).
    """

    read_permission = IsStaffOrMember
    write_permission = IsOffice
    # The subscription modal (incl. public registration) lists a chosen
    # variation's Lieferpausen. LIST is public but only returns rows for an
    # explicit ``?share_type_variation=`` filter (see get_queryset); the
    # unfiltered catalogue stays member/office-scoped.
    public_read_actions = frozenset({"list"})
    serializer_class = DeliveryExceptionPeriodSerializer

    @extend_schema(
        parameters=[get_share_type_variation_parameter(required=False)],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[DeliveryExceptionPeriod]:
        # Validate the filter through the central catalogue (matches the sibling
        # delivery viewsets) instead of a raw query_params.get.
        params = validate_query_params(self.request, optional=["share_type_variation"])
        # select_related through to share_type: the serializer builds the
        # "ShareType - Size" label per row (an N+1 lazy load otherwise).
        queryset = DeliveryExceptionPeriod.objects.select_related(
            "share_type_variation__share_type"
        ).order_by("-valid_from")
        variation_id = params["share_type_variation"]
        if variation_id:
            # An explicit single-variation query (the subscription modal showing
            # the pauses for the variation being chosen, incl. the public
            # registration flow) is not a catalogue leak — return it regardless
            # of role/membership.
            return queryset.filter(share_type_variation_id=variation_id)

        # ``IsStaffOrMember`` lets a member read, but the UNFILTERED row set must
        # be scoped to their OWN subscriptions' variations — otherwise a member
        # sees the entire cross-variation pause catalogue plus each pause's
        # office note. Staff (office/admin/…) see everything.
        if not has_any_role(self.request, *IsStaff.required_roles):
            member = getattr(self.request.user, "member_profile", None)
            subscribed_variation_ids = (
                Subscription.objects.filter(member=member).values_list(
                    "share_type_variation_id", flat=True
                )
                if member is not None
                else Subscription.objects.none().values_list(
                    "share_type_variation_id", flat=True
                )
            )
            queryset = queryset.filter(
                share_type_variation_id__in=subscribed_variation_ids
            )
        return queryset

    @transaction.atomic
    def perform_create(self, serializer: DeliveryExceptionPeriodSerializer) -> None:
        period = serializer.save()
        resync_delivery_exception(
            share_type_variation_id=period.share_type_variation_id,
            newly_paused_weeks=weeks_in_range(period.valid_from, period.valid_until),
            freed_weeks=set(),
        )

    @transaction.atomic
    def perform_update(self, serializer: DeliveryExceptionPeriodSerializer) -> None:
        instance = serializer.instance
        # A started (active/past) pause is frozen. The serializer.validate lock
        # already rejects this, but guard the mutation point too so the invariant
        # can't be bypassed by a code path that skips validation.
        if instance.has_started():
            raise DeliveryExceptionPeriodLocked(
                "This delivery pause has already started and can no longer be "
                "changed."
            )
        old_weeks = weeks_in_range(instance.valid_from, instance.valid_until)
        old_variation_id = instance.share_type_variation_id

        period = serializer.save()
        new_weeks = weeks_in_range(period.valid_from, period.valid_until)

        # A variation change frees every old week on the old variation and
        # pauses every new week on the new one (disjoint resyncs).
        if period.share_type_variation_id != old_variation_id:
            resync_delivery_exception(
                share_type_variation_id=old_variation_id,
                newly_paused_weeks=set(),
                freed_weeks=old_weeks,
            )
            resync_delivery_exception(
                share_type_variation_id=period.share_type_variation_id,
                newly_paused_weeks=new_weeks,
                freed_weeks=set(),
            )
            return

        resync_delivery_exception(
            share_type_variation_id=period.share_type_variation_id,
            newly_paused_weeks=new_weeks - old_weeks,
            freed_weeks=old_weeks - new_weeks,
        )

    @transaction.atomic
    def perform_destroy(self, instance: DeliveryExceptionPeriod) -> None:
        # A started (active/past) pause is frozen — its already-materialised
        # deliveries/billing stand; only future pauses may be deleted (which
        # re-installs their future weeks' deliveries via the resync below).
        if instance.has_started():
            raise DeliveryExceptionPeriodLocked(
                "This delivery pause has already started and can no longer be "
                "deleted."
            )
        variation_id = instance.share_type_variation_id
        freed = weeks_in_range(instance.valid_from, instance.valid_until)
        instance.delete()
        resync_delivery_exception(
            share_type_variation_id=variation_id,
            newly_paused_weeks=set(),
            freed_weeks=freed,
        )
