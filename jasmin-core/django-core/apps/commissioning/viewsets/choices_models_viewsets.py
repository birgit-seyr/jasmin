from __future__ import annotations

import logging

from django.contrib.postgres.aggregates import JSONBAgg
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Q, QuerySet, Subquery
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from isoweek import Week
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import (
    IsOffice,
    IsStaffOrMember,
    IsStaffOrMemberOrCustomer,
    RolePermissionsMixin,
)
from core.serializers import ErrorResponseSerializer

from ..errors import (
    DeliveryDayValidFromInPast,
    DeliveryDayValidFromMoveIntoPast,
    InvalidQueryParam,
    SharesDeliveryDayShorteningStrandsChildren,
    SharesDeliveryDayStartMoveStrandsChildren,
)
from ..models import (
    DeliveryStationDay,
    OrdersDeliveryDay,
    PaymentCycle,
    SharesDeliveryDay,
)
from ..schemas import (
    catalogue_param,
    get_active_at_date_or_future_parameter,
    get_active_at_date_parameter,
    get_is_active_parameter,
)
from ..serializers import (
    OrdersDeliveryDaySerializer,
    PaymentCycleSerializer,
    SharesDeliveryDaySerializer,
)
from ..services import SharesDeliveryDayService
from ..services.onboarding_policy import onboarding_mode_enabled
from ..utils.iso_week_utils import previous_monday
from ..utils.query_params import validate_query_params

logger = logging.getLogger(__name__)


class SharesDeliveryDayViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    # Members read this to populate the subscription-flow choices on
    # their own MemberDetail page (delivery day, payment cycle, share
    # type). Write stays office-only — the catalogue itself is managed
    # from the office UI.
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    serializer_class = SharesDeliveryDaySerializer

    @extend_schema(
        parameters=[
            get_active_at_date_parameter(),
            get_active_at_date_or_future_parameter(),
            catalogue_param(
                "get_delivery_stations",
                required=False,
                description=(
                    "Include active delivery stations in the response. "
                    "Requires `active_at_date` — the stations are resolved as "
                    "of that date."
                ),
            ),
            catalogue_param(
                "future",
                required=False,
                description="Return only future delivery days (not yet active at active_at_date).",
            ),
            catalogue_param(
                "need_info_on_tours",
                required=False,
                description="Annotate each delivery day with its list of used tour numbers.",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[SharesDeliveryDay]:
        queryset = SharesDeliveryDay.objects.all()

        params = validate_query_params(
            self.request,
            optional=[
                "active_at_date",
                "active_at_date_or_future",
                "get_delivery_stations",
                "future",
                "need_info_on_tours",
            ],
        )
        active_at_date = params["active_at_date"]
        active_at_date_or_future = params["active_at_date_or_future"]
        get_delivery_stations: bool | None = params["get_delivery_stations"]
        future: bool | None = params["future"]
        need_info_on_tours: bool | None = params["need_info_on_tours"]

        # The two date windows are alternatives, not layers: chained so that a
        # request sending both gets the narrower ``active_at_date`` view rather
        # than whichever branch happens to run last. Mirrors the station-days
        # endpoint.
        if active_at_date:
            queryset = SharesDeliveryDay.current.active_at_date(
                active_at_date
            ).order_by("day_number")
        elif active_at_date_or_future:
            queryset = SharesDeliveryDay.current.active_at_date_or_future(
                active_at_date_or_future
            ).order_by("day_number")

        # Truthiness, not ``is not None``: ``need_info_on_tours`` is a strict
        # bool, so ``?need_info_on_tours=false`` must NOT add the tours
        # annotation.
        if need_info_on_tours and active_at_date is not None:
            queryset = queryset.annotate(
                used_tours=Subquery(
                    DeliveryStationDay.current.active_at_date(active_at_date)
                    .filter(delivery_day=OuterRef("pk"), tour_number__isnull=False)
                    .values("delivery_day")
                    .annotate(tour_list=JSONBAgg("tour_number", distinct=True))
                    .values("tour_list")
                )
            )

        # Truthiness, not ``is not None``: ``future`` is a strict bool, so
        # ``?future=false`` must NOT switch to the future-days view.
        if future:
            # "Future" is measured against a date — the view is the open-ended
            # days minus those already active at it — so there is no answer
            # without one. Say so instead of ignoring the flag and returning
            # the plain list the caller did not ask for.
            if active_at_date is None:
                raise InvalidQueryParam(
                    "Parameter 'active_at_date' is required when 'future' is requested",
                    field="active_at_date",
                )
            future_queryset = SharesDeliveryDay.objects.filter(valid_until__isnull=True)
            active_records = SharesDeliveryDay.current.active_at_date(active_at_date)
            queryset = future_queryset.exclude(id__in=active_records)

        # Truthiness, not ``is not None``: ``?get_delivery_stations=false``
        # must NOT prefetch the stations.
        if get_delivery_stations:
            # The prefetch resolves the stations active on a given day, so it
            # has no answer without one: ``active_at_date(None)`` builds a
            # comparison against NULL that the query layer rejects. Say so
            # instead of crashing — or silently prefetching today's stations
            # for a request about some other week.
            if active_at_date is None:
                raise InvalidQueryParam(
                    "Parameter 'active_at_date' is required when "
                    "'get_delivery_stations' is requested",
                    field="active_at_date",
                )
            queryset = queryset.prefetch_related(
                Prefetch(
                    "deliverystationday_set",
                    queryset=DeliveryStationDay.current.active_at_date(active_at_date)
                    .select_related("delivery_station")
                    .order_by("tour_number", "stop_order"),
                    to_attr="active_delivery_stations",
                )
            )

        queryset = queryset.order_by("day_number", "-valid_from")

        return queryset

    @extend_schema(
        description="Create a new shares delivery day, automatically closing any "
        "existing delivery day with the same day_number and cascading "
        "updates to delivery station days, shares, and share deliveries.",
        responses={400: ErrorResponseSerializer},
    )
    @transaction.atomic
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data: dict = serializer.validated_data

        valid_from = validated_data.get("valid_from")
        today = timezone.now().date()

        if valid_from and valid_from < today:
            raise DeliveryDayValidFromInPast(
                "Cannot create delivery day with valid_from date in the past.",
                field="valid_from",
            )

        existing_delivery_day = SharesDeliveryDay.handle_succession(validated_data)

        instance = serializer.save()

        # If no open predecessor was found, look for a recently closed one
        # with the same day_number (user manually set valid_until before creating new)
        if existing_delivery_day is None:
            existing_delivery_day = (
                SharesDeliveryDay.objects.filter(
                    day_number=validated_data.get("day_number"),
                    valid_until__isnull=False,
                )
                .exclude(pk=instance.pk)
                .order_by("-valid_until")
                .first()
            )

        if existing_delivery_day:
            updated_station_days = (
                SharesDeliveryDayService.update_delivery_station_days(
                    instance, existing_delivery_day, validated_data
                )
            )
            logger.info(
                "Created %d new delivery station days", len(updated_station_days)
            )

            updated_shares = SharesDeliveryDayService.update_shares_for_delivery_day(
                instance, existing_delivery_day
            )
            logger.info("Updated %d shares", updated_shares)

            updated_share_deliveries = (
                SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
                    instance, existing_delivery_day
                )
            )
            logger.info("Updated %d share deliveries", updated_share_deliveries)

        response_serializer = self.get_serializer(instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        # A standalone close/shorten via a direct PATCH would strand this
        # day's future children — the child-migration services run ONLY on the
        # create (succession) path, not here. Block it so the office succeeds via
        # a NEW SharesDeliveryDay (create), which closes this predecessor AND
        # migrates its children atomically. (The guard lives here, not in the
        # model's clean(), because handle_succession closes the predecessor via
        # save()/clean() during create — guarding clean() would break that.)
        instance = serializer.instance
        new_valid_until = serializer.validated_data.get(
            "valid_until", instance.valid_until
        )
        is_closing_or_shortening = new_valid_until is not None and (
            instance.valid_until is None or new_valid_until < instance.valid_until
        )
        if is_closing_or_shortening:
            stranded = instance.deliverystationday_set.filter(
                Q(valid_until__isnull=True) | Q(valid_until__gt=new_valid_until)
            ).count()
            # Shares store (iso year, week), not a date — a share is stranded if
            # its week starts after the new end (a Sunday). Compare iso tuples.
            vu_week = Week.withdate(new_valid_until)
            stranded += instance.share_set.filter(
                Q(year__gt=vu_week.year)
                | Q(year=vu_week.year, delivery_week__gt=vu_week.week)
            ).count()
            if stranded:
                raise SharesDeliveryDayShorteningStrandsChildren(
                    delivery_day=str(instance),
                    new_valid_until=new_valid_until,
                    stranded_count=stranded,
                )

        # Moving the start into a past week re-opens weeks the office has
        # already delivered and billed, so it is refused — except while the
        # tenant is onboarding, where the office enters a schedule that has been
        # running on paper for a while and must be able to date it back. The
        # flag is read here rather than in the model: recomputes must keep
        # behaving the same when it flips. Only a CHANGED start is judged, so
        # editing any other field of a long-running row stays possible.
        new_valid_from = serializer.validated_data.get(
            "valid_from", instance.valid_from
        )
        if (
            new_valid_from != instance.valid_from
            and new_valid_from < previous_monday(timezone.localdate())
            and not onboarding_mode_enabled()
        ):
            raise DeliveryDayValidFromMoveIntoPast(
                "Cannot move a delivery day's valid_from into a past week.",
                field="valid_from",
            )

        # The mirror case at the other end of the window: moving valid_from
        # LATER leaves everything before the new start with no day covering it.
        # The children keep pointing at this row — the child-migration services
        # run only on the create (succession) path — so they are silently
        # orphaned rather than re-homed. A start moved EARLIER only widens the
        # window and strands nothing, in every mode.
        if new_valid_from > instance.valid_from:
            stranded = instance.deliverystationday_set.filter(
                valid_from__lt=new_valid_from
            ).count()
            # Shares store (iso year, week), not a date — a share is uncovered
            # if its week starts before the new start. Compare iso tuples.
            vf_week = Week.withdate(new_valid_from)
            stranded += instance.share_set.filter(
                Q(year__lt=vf_week.year)
                | Q(year=vf_week.year, delivery_week__lt=vf_week.week)
            ).count()
            if stranded:
                raise SharesDeliveryDayStartMoveStrandsChildren(
                    delivery_day=str(instance),
                    new_valid_from=new_valid_from,
                    stranded_count=stranded,
                )
        serializer.save()

    def perform_destroy(self, instance):
        # Share.delivery_day CASCADEs — deleting a used delivery day would wipe
        # whole historical weeks of Shares + their deliveries + ShareContents
        # in one call, with no recompute. Refuse while any Share references it.
        from ..errors import SharesDeliveryDayInUse

        share_count = instance.share_set.count()
        if share_count:
            raise SharesDeliveryDayInUse(
                delivery_day=str(instance), share_count=share_count
            )
        instance.delete()


class OrdersDeliveryDayViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    # Catalogue endpoint read by every authenticated persona:
    #   * Members → MemberDetail subscription-flow choices
    #   * Customers → CustomerOrderPage day selector
    #   * Staff → office UI
    # Write stays office-only — the catalogue itself is configured
    # from the office UI.
    read_permission = IsStaffOrMemberOrCustomer
    write_permission = IsOffice
    serializer_class = OrdersDeliveryDaySerializer

    @extend_schema()
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[OrdersDeliveryDay]:
        queryset = OrdersDeliveryDay.objects.all()

        queryset = queryset.order_by("day_number")

        return queryset

    @extend_schema(
        description="Create a new orders delivery day. Unlike shares delivery "
        "days, an orders delivery day carries no validity window and there is "
        "no succession: day_number is unique, so a duplicate is rejected.",
        responses={400: ErrorResponseSerializer},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        instance = serializer.save()
        response_serializer = self.get_serializer(instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class PaymentCycleViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    # Members read this to populate the subscription-flow choices on
    # their own MemberDetail page (delivery day, payment cycle, share
    # type). Write stays office-only — the catalogue itself is managed
    # from the office UI.
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    # The public registration wizard's subscription modal lets the applicant
    # pick a payment cycle. LIST only — retrieve/write stay member/office-gated.
    public_read_actions = frozenset({"list"})
    serializer_class = PaymentCycleSerializer

    @extend_schema(
        parameters=[get_is_active_parameter()],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[PaymentCycle]:
        queryset = PaymentCycle.objects.all()

        params = validate_query_params(self.request, optional=["is_active"])
        is_active: bool | None = params["is_active"]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        return queryset
