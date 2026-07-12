from __future__ import annotations

import logging

from django.contrib.postgres.aggregates import JSONBAgg
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Q, QuerySet, Subquery
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
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
    SharesDeliveryDayShorteningStrandsChildren,
)
from ..models import (
    DeliveryStationDay,
    OrdersDeliveryDay,
    PaymentCycle,
    SharesDeliveryDay,
)
from ..schemas import (
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
            OpenApiParameter(
                name="get_delivery_stations",
                type=OpenApiTypes.BOOL,
                required=False,
                description="Include active delivery stations in the response.",
            ),
            OpenApiParameter(
                name="future",
                type=OpenApiTypes.BOOL,
                required=False,
                description="Return only future delivery days (not yet active at active_at_date).",
            ),
            OpenApiParameter(
                name="need_info_on_tours",
                type=OpenApiTypes.BOOL,
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

        if active_at_date:
            queryset = SharesDeliveryDay.current.active_at_date(
                active_at_date
            ).order_by("day_number")

        if active_at_date_or_future:
            queryset = SharesDeliveryDay.current.active_at_date_or_future(
                active_at_date_or_future
            ).order_by("day_number")

        if need_info_on_tours is not None and active_at_date is not None:
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
        if future and active_at_date is not None:
            future_queryset = SharesDeliveryDay.objects.filter(valid_until__isnull=True)
            active_records = SharesDeliveryDay.current.active_at_date(active_at_date)
            queryset = future_queryset.exclude(id__in=active_records)

        if get_delivery_stations is not None:
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
        # SUC-5: a standalone close/shorten via a direct PATCH would strand this
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
        description="Create a new orders delivery day, automatically closing any "
        "existing delivery day with the same day_number.",
        responses={400: ErrorResponseSerializer},
    )
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
