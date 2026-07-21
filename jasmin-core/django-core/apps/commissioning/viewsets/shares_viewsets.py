from __future__ import annotations

import csv
from collections.abc import Iterator
from typing import Any

from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    Count,
    F,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Concat
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import (
    IsOffice,
    IsOfficeOrMember,
    IsStaff,
    IsStaffOrMember,
    RolePermissionsMixin,
)
from apps.shared.csv_safety import CsvEchoBuffer, escape_csv_row
from core.errors import ForbiddenError
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer

from ..errors import (
    CommissioningError,
    RequiredFieldMissing,
    ShareArticleNotFound,
    ShareTypeVariationNotFound,
    VirtualComponentNotPhysical,
)
from ..models import (
    Share,
    ShareArticle,
    ShareContent,
    ShareDelivery,
    ShareType,
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
    Subscription,
    VirtualVariationComponent,
)
from ..models.choices import ShareOptions
from ..schemas import (
    EXPORT_DATE_RANGE_PARAMETERS,
    catalogue_param,
    get_active_at_date_parameter,
    get_day_number_parameter,
    get_delivery_day_parameter,
    get_delivery_station_parameter,
    get_delivery_week_parameter,
    get_member_parameter,
    get_share_option_parameter,
    get_share_type_parameter,
    get_share_type_variation_parameter,
    get_year_parameter,
)
from ..scoping import enforce_privileged, is_privileged, scope_to_member
from ..serializers import (
    DefaultShareContentRequestSerializer,
    DefaultShareContentResponseSerializer,
    ShareContentSerializer,
    ShareDayPlanningRowSerializer,
    ShareDeliveryOverviewSerializer,
    ShareDeliverySerializer,
    ShareSerializer,
    ShareTypeSerializer,
    ShareTypeVariationGrossPriceSerializer,
    ShareTypeVariationSerializer,
    VirtualVariationComponentListItemSerializer,
    VirtualVariationComponentsRequestSerializer,
    VirtualVariationComponentsResponseSerializer,
    WeeklyComboMatrixResponseSerializer,
)
from ..serializers.shares_serializer import (
    DeliveryExceptionGapSerializer,
    ShareDeliveryDetailsRowSerializer,
    StationMemberMatrixSerializer,
)
from ..services import (
    DefaultShareContentService,
    PackingListBoxesMatrixService,
    ShareDeliveryService,
    SharesDayChangeService,
)
from ..utils.basic_utils import size_order_annotation
from ..utils.composite_id_utils import parse_composite_pk
from ..utils.iso_week_utils import week_day_to_date
from ..utils.lookup import get_or_404
from ..utils.query_params import validate_query_params
from ..utils.weight import quantize_weight
from .base_viewsets import BaseArchivableViewSet


def _validate_share_option(value: str) -> str | None:
    """Uppercase and validate a share_option value. Returns None if invalid."""
    upper = value.upper()
    valid = {v for v, _l in ShareOptions.choices}
    return upper if upper in valid else None


class ShareTypeViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    # Members need to read this on their MemberDetail page (the
    # subscription flow lists share types). ``ShareTypeVariation``
    # below is already ``IsStaffOrMember``; matching that here.
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    # The public registration wizard lists the share catalog to prospective
    # (anonymous) members. LIST only — retrieve/write stay member/office-gated.
    # The serializer exposes catalog fields only (no PII / banking).
    public_read_actions = frozenset({"list"})
    serializer_class = ShareTypeSerializer

    @extend_schema(
        parameters=[
            get_active_at_date_parameter(),
            get_share_option_parameter(),
            catalogue_param(
                "include_future",
                required=False,
                description="Widen the validity filter to current + future share "
                "types (active on the reference date OR starting after "
                "it), excluding only already-ended ones. Reference date "
                "= active_at_date if given, else today.",
            ),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        today = timezone.localdate().isoformat()

        # One query over the active variations instead of one per share type;
        # the serializer reads this map via context.
        sizes_by_share_type: dict[str, list[str]] = {}
        active_variation_rows = (
            ShareTypeVariation.current.active_at_date(today)
            .values_list("share_type_id", "size")
            .distinct()
        )
        for share_type_id, size in active_variation_rows:
            if size:
                sizes_by_share_type.setdefault(share_type_id, []).append(size)
        sizes_in_use_by_share_type = {
            share_type_id: ", ".join(sizes)
            for share_type_id, sizes in sizes_by_share_type.items()
        }

        # Per-share-type valid_until lower bound: the latest variation end + a
        # flag for any open-ended (never-ending) variation. One aggregate over
        # ALL variations (matching ``ShareType.clean``'s stranding query) so the
        # datepicker can disable end dates the backend would reject. Max ignores
        # NULLs; the open-ended count catches them.
        variation_bounds_by_share_type = {
            row["share_type_id"]: {
                "max_valid_until": row["max_valid_until"],
                "has_open_ended": row["open_count"] > 0,
            }
            for row in (
                ShareTypeVariation.objects.filter(share_type__in=queryset)
                .values("share_type_id")
                .annotate(
                    max_valid_until=Max("valid_until"),
                    open_count=Count("pk", filter=Q(valid_until__isnull=True)),
                )
            )
        }

        serializer = self.get_serializer(
            queryset,
            many=True,
            context={
                **self.get_serializer_context(),
                "sizes_in_use_by_share_type": sizes_in_use_by_share_type,
                "variation_bounds_by_share_type": variation_bounds_by_share_type,
            },
        )
        return Response(serializer.data)

    def get_queryset(self) -> QuerySet[ShareType]:
        queryset = ShareType.objects.all()

        params = validate_query_params(
            self.request,
            optional=["active_at_date", "include_future", "share_option"],
        )
        active_at_date = params["active_at_date"]  # a date (or None), 400 on bad format
        include_future = params["include_future"]
        share_option = params["share_option"]  # validated against ShareOptions, or None

        # ``include_future`` widens "active on the reference date" to "active on
        # it OR starting after it" — current + upcoming share types, excluding
        # only the already-ended ones. Reference date = ``active_at_date`` if
        # given, else today. (Mirrors ShareTypeVariationViewSet so the abos
        # picker can show future share types AND their future variations.)
        if include_future:
            reference_date = active_at_date or timezone.localdate()
            queryset = ShareType.current.active_at_date_or_future(reference_date)
        elif active_at_date:
            queryset = ShareType.current.active_at_date(active_at_date)

        if share_option:
            queryset = queryset.filter(share_option=share_option)

        return queryset

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data.copy()

        if "share_option" in data and data["share_option"]:
            validated = _validate_share_option(data["share_option"])
            if validated is None:
                raise CommissioningError(
                    f"ShareOption '{data['share_option'].upper()}' is not a valid choice.",
                    field="share_option",
                    code="share_type.invalid_share_option",
                )
            data["share_option"] = validated

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data.copy()

        if "share_option" in data and data["share_option"]:
            validated = _validate_share_option(data["share_option"])
            if validated is None:
                raise CommissioningError(
                    f"ShareOption '{data['share_option'].upper()}' is not a valid choice.",
                    field="share_option",
                    code="share_type.invalid_share_option",
                )
            data["share_option"] = validated

        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)


class ShareTypeVariationViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaffOrMember
    write_permission = IsOffice
    # Public registration wizard lists variations (with prices + advisory
    # per-week capacity) to prospective anonymous members. LIST only —
    # retrieve/write stay member/office-gated. Catalog fields only.
    public_read_actions = frozenset({"list"})
    serializer_class = ShareTypeVariationSerializer

    @extend_schema(
        parameters=[
            get_active_at_date_parameter(),
            get_share_option_parameter(required=False),
            get_share_type_parameter(required=False),
            catalogue_param(
                "include_future",
                required=False,
                description="Widen the validity filter to current + future "
                "variations (active on the reference date OR starting "
                "after it), excluding only already-ended ones. Reference "
                "date = active_at_date if given, else today.",
            ),
            catalogue_param(
                "physical",
                required=False,
                description="Filter for physical variations only",
            ),
            catalogue_param(
                "virtual",
                required=False,
                description="Filter for virtual variations only",
            ),
            catalogue_param(
                "is_packed_bulk",
                required=False,
                description="Filter by per-variation bulk-packing flag. "
                "Only meaningful in MIXED packing mode; omit to "
                "return all variations.",
            ),
            # Window for the per-week ``capacity_by_week`` field (same contract
            # as the delivery-station-days endpoint). Omit all three → the field
            # is null (no term-aware capacity requested).
            get_year_parameter(required=False),
            get_delivery_week_parameter(required=False),
            catalogue_param(
                "num_weeks",
                required=False,
                description="Number of weeks of per-variation capacity_by_week to "
                "return (default: 52). Needs year + delivery_week.",
            ),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ShareTypeVariation]:
        queryset = ShareTypeVariation.objects.select_related("share_type")

        params = validate_query_params(
            self.request,
            optional=[
                "active_at_date",
                "include_future",
                "physical",
                "virtual",
                "share_option",
                "share_type",
                "is_packed_bulk",
            ],
        )
        active_at_date = params["active_at_date"]
        include_future = params["include_future"]
        physical = params["physical"]
        virtual = params["virtual"]
        share_option = params["share_option"]
        share_type = params["share_type"]
        is_packed_bulk = params["is_packed_bulk"]

        if share_option is not None:
            queryset = queryset.filter(share_type__share_option=share_option)
        if share_type is not None:
            queryset = queryset.filter(share_type=share_type)

        # ``include_future`` widens the validity filter from "active on the
        # reference date" to "active on it OR starting after it" — i.e. current
        # + upcoming variations, excluding only the already-ended ones. The
        # reference date is the explicit ``active_at_date`` if given, else today.
        if include_future:
            reference_date = active_at_date or timezone.now().date()
            queryset = queryset.filter(
                id__in=ShareTypeVariation.current.active_at_date_or_future(
                    reference_date
                ).values_list("id", flat=True)
            )
        elif active_at_date is not None:
            queryset = queryset.filter(
                id__in=ShareTypeVariation.current.active_at_date(
                    active_at_date
                ).values_list("id", flat=True)
            )

        # Truthiness, NOT ``is not None``: these are strict bools, so
        # ``?physical=false`` parses to ``False`` (present-but-false). Keying on
        # presence would wrongly restrict to PHYSICAL for ``physical=false`` and
        # return an empty set for ``physical=true&virtual=true``. Only an
        # explicit true opts into either filter.
        if physical:
            queryset = queryset.filter(
                variation_type=ShareTypeVariation.VariationType.PHYSICAL
            )
        if virtual:
            queryset = queryset.filter(
                variation_type=ShareTypeVariation.VariationType.VIRTUAL
            )
        if is_packed_bulk is not None:
            queryset = queryset.filter(is_packed_bulk=is_packed_bulk)

        queryset = queryset.annotate(share_type_name=F("share_type__name"))

        lookup_date = (
            active_at_date if active_at_date else timezone.localdate().isoformat()
        )

        # Newest-effective-wins is the caller's job (see ``active_on_date_q``):
        # without the explicit ordering the ``[:1]`` pick is non-deterministic
        # when validity windows overlap on the reference date.
        active_price_subquery = (
            ShareTypeVariationGrossPrice.current.active_at_date(lookup_date)
            .filter(share_type_variation=OuterRef("pk"))
            .order_by("-valid_from")
            .values("price_per_delivery")[:1]
        )

        active_price_sum_articles_subquery = (
            ShareTypeVariationGrossPrice.current.active_at_date(lookup_date)
            .filter(share_type_variation=OuterRef("pk"))
            .order_by("-valid_from")
            .values("price_sum_articles")[:1]
        )

        active_solidarity_min_subquery = (
            ShareTypeVariationGrossPrice.current.active_at_date(lookup_date)
            .filter(share_type_variation=OuterRef("pk"))
            .order_by("-valid_from")
            .values("solidarity_min_price_per_delivery")[:1]
        )

        queryset = queryset.annotate(
            active_price_per_delivery=Subquery(active_price_subquery),
            active_price_sum_articles=Subquery(active_price_sum_articles_subquery),
            active_solidarity_min_price_per_delivery=Subquery(
                active_solidarity_min_subquery
            ),
        )

        queryset = queryset.annotate(
            size_order=size_order_annotation(),
        ).order_by("-valid_from", "sort_order", "size_order")

        return queryset


class _ShareDeliveryWriteChoreographyMixin:
    """Shared write choreography for the ShareDelivery-editing viewsets.

    Every write on a ShareDelivery runs the same sequence inside one
    transaction: capacity guard (create/move only) -> write ->
    ``notify_subscription_changed`` (payments re-plans the charge schedule)
    -> ``recompute_shares`` (planning rebuild).
    ``perform_create``/``perform_destroy`` are identical
    for both viewsets and live here in full; ``perform_update`` stays on
    each viewset (divergent extras: ``apply_to_future`` propagation on
    ShareDeliveryViewSet, share reassignment on ShareDeliveryOverviewViewSet)
    and composes the helpers below.
    """

    def perform_create(self, serializer):
        from ..services.recompute import recompute_shares

        with transaction.atomic():
            self._assert_capacity_for_new_delivery(serializer)
            instance = serializer.save()
            # Adding a delivery changes the billable set — without the notify
            # the new delivery under-bills until some other change happens to
            # re-trigger charge regeneration.
            self._notify_subscription_changed_for(instance)
            if instance.share_id:
                recompute_shares([instance.share_id])

    def perform_destroy(self, instance):
        from apps.shared.subscription_hooks import notify_subscription_changed

        from ..services.recompute import recompute_shares

        share_id = instance.share_id
        # Capture before delete — only the ShareDelivery is removed; the
        # subscription row survives and still needs its charges re-planned.
        subscription = instance.subscription
        with transaction.atomic():
            instance.delete()
            if subscription is not None:
                notify_subscription_changed(subscription)
            if share_id:
                recompute_shares([share_id])

    @staticmethod
    def _assert_capacity_for_new_delivery(serializer) -> None:
        """Block creating a (harvest) delivery onto a full station-day.

        Resolves from ``validated_data`` (no instance yet); a fresh slot →
        ``moving_delivery_id=None`` (incoming quantity 1). No-op for
        non-harvest options / uncapped station-days; ``select_for_update``
        inside is race-safe.
        """
        from ..services import CapacityReservationService

        share = serializer.validated_data.get("share")
        target_delivery_station_day = serializer.validated_data.get(
            "delivery_station_day"
        )
        if share is not None and target_delivery_station_day is not None:
            CapacityReservationService.assert_share_delivery_fits(
                delivery_station_day_id=target_delivery_station_day.id,
                year=share.year,
                week=share.delivery_week,
                is_additional_share_type=(
                    share.share_type_variation.share_type.is_additional_share_type
                ),
                moving_delivery_id=None,
            )

    @staticmethod
    def _assert_capacity_for_station_day_move(
        instance, target_delivery_station_day
    ) -> None:
        """Block moving an existing delivery onto a full station-day
        (race-safe, harvest only). No-op when the station-day is unchanged or
        unset, or when the row has no share to derive year/week/option from.
        Call BEFORE ``serializer.save()`` — it reads the pre-save instance.
        """
        from ..services import CapacityReservationService

        if (
            target_delivery_station_day is not None
            and target_delivery_station_day.id != instance.delivery_station_day_id
            and instance.share_id
        ):
            CapacityReservationService.assert_share_delivery_fits(
                delivery_station_day_id=target_delivery_station_day.id,
                year=instance.share.year,
                week=instance.share.delivery_week,
                is_additional_share_type=(
                    instance.share.share_type_variation.share_type.is_additional_share_type
                ),
                moving_delivery_id=instance.pk,
            )

    @staticmethod
    def _notify_subscription_changed_for(instance) -> None:
        """``joker_taken`` / ``is_opted_in`` / adding a delivery change which
        deliveries count toward this period's bill — notify payments (via the
        shared hook) to re-plan the charge schedule so a jokered/skipped week
        isn't still charged. Mirrors OptinService.toggle. Unconditional notify
        is safe: the charge service diffs + preserves locked rows.
        """
        from apps.shared.subscription_hooks import notify_subscription_changed

        if instance.subscription_id:
            notify_subscription_changed(instance.subscription)

    @staticmethod
    def _share_for_delivery_day(share, target_delivery_day):
        """The shared planning unit (``Share``) for the same (year, week,
        variation) but a possibly different ``delivery_day``. Moving a delivery
        to a station-day on another weekday means its Share must move too (a
        Share is per year/week/day/variation) — get-or-create the target day's
        Share, creating it the first time a delivery lands on that day."""
        if share.delivery_day_id == target_delivery_day.id:
            return share
        new_share, _ = Share.objects.get_or_create(
            year=share.year,
            delivery_week=share.delivery_week,
            delivery_day=target_delivery_day,
            share_type_variation=share.share_type_variation,
        )
        return new_share


class ShareDeliveryViewSet(
    _ShareDeliveryWriteChoreographyMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    """CRUD for a subscription's per-week ShareDelivery rows, plus the
    member-facing opt-in actions. Writes re-plan charges and rebuild the
    week's planning data."""

    read_permission = IsStaffOrMember
    # Members may ONLY reach the opt-in actions (see get_permissions). All
    # standard CRUD + the office @actions require IsOffice. Previously
    # IsOfficeOrMember applied to every write verb, letting a member
    # POST/PATCH/DELETE arbitrary ShareDelivery rows — bypassing OptinService's
    # deadline checks, pointing rows at any tenant subscription, and silently
    # dropping deliveries they're owed (breaking billing materialisation).
    write_permission = IsOffice
    serializer_class = ShareDeliverySerializer
    pagination_class = OptionalLimitOffsetPagination

    # Member-reachable actions: the opt-in writes (toggle_optin / pending_optin)
    # plus the read-only exception_gaps lookup (a member views their own
    # delivery gaps on their member detail). Each self-scopes the member to
    # their OWN data in its body — without being listed here the member is
    # rejected by write_permission = IsOffice before that self-check can run.
    # Everything else falls through to write_permission = IsOffice.
    _MEMBER_ACTIONS = frozenset({"toggle_optin", "pending_optin", "exception_gaps"})

    def get_permissions(self):
        if getattr(self, "action", None) in self._MEMBER_ACTIONS:
            base = [permission() for permission in self.permission_classes]
            return base + [IsOfficeOrMember()]
        return super().get_permissions()

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=False),
            get_member_parameter(),
            get_share_type_parameter(required=False),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ShareDelivery]:
        # drf-spectacular introspects get_queryset with a fake request carrying
        # no query params; the year-required validation below would raise and
        # emit a "Failed to obtain model" schema warning. Short-circuit it.
        if getattr(self, "swagger_fake_view", False):
            return ShareDelivery.objects.none()
        queryset = ShareDelivery.objects.select_related(
            "share",
            "share__delivery_day",
            "share__share_type_variation__share_type",
            "subscription__member",
            "subscription__share_type_variation__share_type",
            "delivery_station_day__delivery_station",
        ).prefetch_related(
            "share__sharecontent_set",
            "share__sharecontent_set__share_article",
            # The serializer derefs ``seller.name_for_member_pages`` per
            # ShareContent; without this prefetch each non-null seller FK
            # lazy-loads (one query per row).
            "share__sharecontent_set__seller",
        )
        # ``year`` is required when LISTING (a week-scoped list, matching the
        # @extend_schema); the retrieve/detail path looks up by pk and the
        # shared get_queryset must not 400 it.
        is_list = self.action == "list"
        params = validate_query_params(
            self.request,
            required=["year"] if is_list else [],
            optional=(
                ["delivery_week", "member", "share_type"]
                if is_list
                else ["year", "delivery_week", "member", "share_type"]
            ),
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        member = params["member"]
        share_type = params["share_type"]

        if year is not None:
            queryset = queryset.filter(share__year=year)

        if delivery_week is not None:
            queryset = queryset.filter(share__delivery_week=delivery_week)

        if member is not None:
            queryset = queryset.filter(subscription__member=member)

        if share_type is not None:
            queryset = queryset.filter(
                subscription__share_type_variation__share_type=share_type
            )

        return scope_to_member(
            queryset,
            self.request,
            path="subscription__member",
        )

    # ---- On-off opt-in actions ----------------------------------- #

    @extend_schema(
        description=(
            "Toggle the on-off opt-in flag on a single ShareDelivery. "
            'Body: ``{"opt_in": true | false}``. Permissions: office '
            "OR the delivery's owning member. Refuses on non-on-off "
            "variations (use ``joker_taken`` for those) and after the "
            "variation's configured deadline."
        ),
        request=inline_serializer(
            name="ToggleOptinRequest",
            fields={"opt_in": drf_serializers.BooleanField()},
        ),
        responses={
            200: ShareDeliverySerializer,
            # ``OptinNotApplicable`` (non-on-off variation) / missing flag.
            400: ErrorResponseSerializer,
            # ``OptinDeadlinePassed``.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="toggle_optin")
    def toggle_optin(self, request: Request, pk: str | None = None) -> Response:
        from apps.commissioning.services.optin_service import OptinService

        share_delivery: ShareDelivery = self.get_object()
        # ``get_object`` already runs the queryset's
        # ``scope_to_member`` filter — a member can only fetch their
        # own deliveries, so reaching this point means the actor is
        # office or the row's owning member. No extra permission
        # check needed.

        opt_in = request.data.get("opt_in")
        if not isinstance(opt_in, bool):
            raise RequiredFieldMissing(
                "'opt_in' (boolean) is required.", field="opt_in"
            )

        OptinService.toggle(share_delivery, opt_in=opt_in, actor=request.user)
        return Response(
            self.get_serializer(share_delivery).data, status=status.HTTP_200_OK
        )

    @extend_schema(
        description=(
            "Upcoming on-off deliveries this member can still toggle "
            "(variation has ``requires_optin=True`` AND deadline is "
            "today or later). Office may pass ``?member=`` for any "
            "member; non-office callers MUST ask for themselves only "
            "— a cross-member request returns 403."
        ),
        parameters=[get_member_parameter(required=False)],
        responses={
            200: ShareDeliverySerializer(many=True),
            # Caller is staff without a linked Member and passed no ?member=.
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"], url_path="pending_optin")
    def pending_optin(self, request: Request) -> Response:
        from apps.commissioning.models import Member
        from apps.commissioning.services.optin_service import OptinService

        # Resolve the requesting user's own Member row (None when the
        # caller is staff without a linked Member).
        self_member = Member.objects.filter(user=request.user).first()
        # Explicit roles matching what get_permissions grants for this action
        # (IsOfficeOrMember = OFFICE/ADMIN/MEMBER). The default privileged set
        # also includes MANAGEMENT, but a MANAGEMENT-only user is rejected at
        # the permission layer and can never reach this branch — scoping the
        # check to the reachable roles keeps the two layers honest.
        from apps.authz.roles import Role

        privileged = is_privileged(request, privileged_roles=(Role.OFFICE, Role.ADMIN))

        member_id = validate_query_params(request, optional=["member"])["member"]
        if member_id:
            # Non-office callers can ONLY ask for their own member id
            # — a cross-member request is a permission leak. Office
            # bypasses this check (they manage on behalf of anyone).
            if not privileged and (
                self_member is None or str(self_member.pk) != str(member_id)
            ):
                raise ForbiddenError("You may only request your own opt-in deliveries.")
            member = Member.objects.filter(pk=member_id).first()
            if member is None:
                return Response([], status=status.HTTP_200_OK)
        else:
            # Member-scoped fallback: derive Member from request.user.
            if self_member is None:
                raise CommissioningError(
                    "No member context.", code="optin.no_member_context"
                )
            member = self_member

        rows = OptinService.list_pending_for_member(member)
        return Response(
            self.get_serializer(rows, many=True).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[
            get_member_parameter(required=True),
            get_year_parameter(required=True),
        ],
        responses={
            200: DeliveryExceptionGapSerializer(many=True),
            400: ErrorResponseSerializer,
        },
        description=(
            "Weeks this member's confirmed subscriptions WOULD deliver but "
            "don't, because a delivery exception (Lieferpause) removed the "
            "ShareDelivery. Returns pseudo-deliveries for ``year`` and "
            "``year+1`` so the deliveries card can surface the paused weeks — "
            "there is no ShareDelivery row for them."
        ),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="exception_gaps",
        pagination_class=None,
    )
    def exception_gaps(self, request: Request) -> Response:
        from apps.authz.roles import Role
        from apps.commissioning.models import Member
        from apps.commissioning.services.delivery_exceptions import (
            member_exception_gaps,
        )

        params = validate_query_params(request, required=["member", "year"])
        member_id = params["member"]
        year = params["year"]

        # Same self-vs-office scoping as ``pending_optin``: a member may only
        # ask for their own gaps; office asks for anyone.
        privileged = is_privileged(request, privileged_roles=(Role.OFFICE, Role.ADMIN))
        if not privileged:
            self_member = Member.objects.filter(user=request.user).first()
            if self_member is None or str(self_member.pk) != str(member_id):
                raise ForbiddenError("You may only request your own delivery gaps.")

        gaps = member_exception_gaps(member_id, years={year, year + 1})
        return Response(
            DeliveryExceptionGapSerializer(gaps, many=True).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            catalogue_param("for_tours", required=False),
            catalogue_param("for_stations", required=False),
            catalogue_param("is_packed_bulk", required=False),
            catalogue_param("joker", required=False),
        ],
        responses={
            200: WeeklyComboMatrixResponseSerializer,
            400: ErrorResponseSerializer,
        },
        description=(
            "Whole-week matrix for AmountShareTypeVariations: one row per "
            "delivery day (or day×tour / day×station). Subscription tenants get "
            "box-combination columns (combo_<key>, each cell the box count); "
            "import (external-demand) tenants get flat per-variation columns "
            "(variation_<id>) sourced from weekly demand. Both render through "
            "the same frontend hook. ``joker=true`` counts the boxes skipped via "
            "a taken joker instead of the shipping ones (same columns)."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def box_combination_matrix(self, request: Request) -> Response:
        enforce_privileged(request, "Staff only.")
        params = validate_query_params(
            request,
            required=["year", "delivery_week"],
            optional=["for_tours", "for_stations", "is_packed_bulk", "joker"],
        )
        mode = "day"
        if params["for_stations"]:
            mode = "stations"
        elif params["for_tours"]:
            mode = "tours"

        joker = bool(params["joker"])

        # Import (external-demand) tenants have no ShareDelivery rows, so their
        # matrix is FLAT per-variation columns (from the demand port); everyone
        # else gets the real box combinations. Both render through the same
        # frontend hook, so AmountShareTypeVariations stays one code path.
        from ..services.share_demand_service import (
            ExternalDemandBackend,
            _resolve_backend,
        )

        if isinstance(_resolve_backend(), ExternalDemandBackend):
            result = ShareDeliveryService.get_weekly_variation_count_matrix(
                year=params["year"],
                delivery_week=params["delivery_week"],
                mode=mode,
                joker=joker,
            )
        else:
            result = PackingListBoxesMatrixService.get_weekly_combination_matrix(
                year=params["year"],
                delivery_week=params["delivery_week"],
                mode=mode,
                is_packed_bulk=params["is_packed_bulk"],
                joker=joker,
            )
        serializer = WeeklyComboMatrixResponseSerializer(result)
        return Response(serializer.data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # ShareDelivery rows are system-managed; only staff may create them.
        enforce_privileged(request, "Staff only.")
        return super().create(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Members may not delete their own deliveries.
        enforce_privileged(request, "Staff only.")
        return super().destroy(request, *args, **kwargs)

    def perform_update(self, serializer):
        from ..models import DeliveryStationDay
        from ..services import CapacityReservationService
        from ..services.recompute import recompute_shares

        instance = serializer.instance
        target_delivery_station_day = serializer.validated_data.get(
            "delivery_station_day", instance.delivery_station_day
        )
        # Same share type across the subscription → one flag drives the capacity
        # check for the primary delivery and any future ones. No share to place
        # → treat as non-capacity-consuming so the check is skipped.
        is_additional_share_type = (
            instance.share.share_type_variation.share_type.is_additional_share_type
            if instance.share_id
            else True
        )
        apply_to_future = self.request.data.get("apply_to_future", False)

        with transaction.atomic():
            self._assert_capacity_for_station_day_move(
                instance, target_delivery_station_day
            )

            # The delivery's ORIGINAL day/week — captured before we re-point the
            # Share, so the apply-to-future scan still finds this member's other
            # deliveries on their existing weekday.
            original_share = instance.share if instance.share_id else None
            affected_share_ids: set = set()

            # Cross-day move: the target station-day is on another weekday, so
            # re-point THIS delivery's Share to that day's planning unit BEFORE
            # saving — otherwise ``ShareDelivery.clean`` refuses the mismatch.
            if (
                target_delivery_station_day
                and original_share
                and target_delivery_station_day.delivery_day_id
                != original_share.delivery_day_id
            ):
                affected_share_ids.add(original_share.id)
                repointed_share = self._share_for_delivery_day(
                    original_share, target_delivery_station_day.delivery_day
                )
                instance.share = repointed_share
                # The client round-trips the ORIGINAL ``share`` id back in the
                # PATCH body, so ``serializer.save()`` would re-set instance.share
                # to the old day's Share (via update()) and ShareDelivery.clean
                # would then reject the day mismatch. Force the re-pointed Share
                # into validated_data so the save persists the move, not the echo.
                serializer.validated_data["share"] = repointed_share

            instance = serializer.save()
            if instance.share_id:
                affected_share_ids.add(instance.share_id)

            self._notify_subscription_changed_for(instance)

            if not apply_to_future or not instance.subscription or not original_share:
                recompute_shares(affected_share_ids)
                return

            new_delivery_station_day = instance.delivery_station_day
            if not new_delivery_station_day:
                recompute_shares(affected_share_ids)
                return

            # The weekday we're moving TO (same as the original for a plain
            # station change; a different weekday for a cross-day move).
            target_delivery_day = new_delivery_station_day.delivery_day
            future_deliveries = (
                ShareDelivery.objects.filter(
                    subscription=instance.subscription,
                    share__delivery_day=original_share.delivery_day,
                    share__year__gte=original_share.year,
                )
                .exclude(pk=instance.pk)
                .exclude(
                    share__year=original_share.year,
                    share__delivery_week__lt=original_share.delivery_week,
                )
                .select_related("share", "share__delivery_day")
            )

            # Hoist the per-delivery DeliveryStationDay lookup out of the loop:
            # every future delivery resolves within ONE (station, target-day)
            # succession chain. Fetch it once and resolve each delivery's week in
            # Python — mirrors delivery_viewsets._migrate_succession_children.
            dsd_chain = list(
                DeliveryStationDay.objects.filter(
                    delivery_station=new_delivery_station_day.delivery_station,
                    delivery_day=target_delivery_day,
                ).order_by("-valid_from")
            )

            def _resolve_dsd(on_date):
                for dsd in dsd_chain:
                    if dsd.valid_from <= on_date and (
                        dsd.valid_until is None or dsd.valid_until >= on_date
                    ):
                        return dsd
                return None

            for delivery in future_deliveries:
                delivery_date = week_day_to_date(
                    delivery.share.year,
                    delivery.share.delivery_week,
                    delivery.share.delivery_day.day_number,
                )

                matching_delivery_station_day = _resolve_dsd(delivery_date)
                if matching_delivery_station_day:
                    if (
                        matching_delivery_station_day.id
                        != delivery.delivery_station_day_id
                    ):
                        CapacityReservationService.assert_share_delivery_fits(
                            delivery_station_day_id=matching_delivery_station_day.id,
                            year=delivery.share.year,
                            week=delivery.share.delivery_week,
                            is_additional_share_type=is_additional_share_type,
                            moving_delivery_id=delivery.pk,
                        )
                    # Re-point the Share too when the move crosses weekdays.
                    if delivery.share.delivery_day_id != target_delivery_day.id:
                        affected_share_ids.add(delivery.share_id)
                        delivery.share = self._share_for_delivery_day(
                            delivery.share, target_delivery_day
                        )
                    delivery.delivery_station_day = matching_delivery_station_day
                    delivery.save(update_fields=["delivery_station_day", "share"])
                    if delivery.share_id:
                        affected_share_ids.add(delivery.share_id)

            recompute_shares(affected_share_ids)


class ShareContentViewSet(BaseArchivableViewSet):
    serializer_class = ShareContentSerializer
    queryset = ShareContent.objects.filter(is_finalized=True)

    def apply_filters(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(is_finalized=True)

    def perform_create(self, serializer):
        from ..services.recompute import recompute_shares

        with transaction.atomic():
            instance = serializer.save()
            if instance.share_id:
                recompute_shares([instance.share_id])

    def perform_update(self, serializer):
        from ..services.recompute import recompute_shares

        with transaction.atomic():
            instance = serializer.save()
            if instance.share_id:
                recompute_shares([instance.share_id])

    def perform_destroy(self, instance):
        from ..models import MovementShareArticle
        from ..services.recompute import recompute_shares
        from ..services.snapshot_service import SnapshotService
        from ..services.theoretical_objects import recalculate_actual_corrections

        share_id = instance.share_id
        with transaction.atomic():
            # instance.delete() cascade-removes this row's SHARECONTENT movements
            # AND its theoretical HARVEST/PURCHASE/WASH/CLEAN movements (those
            # carry share_content=NULL, reached via their Theoretical* parent's
            # share_content link). recompute_for_shares only re-cascades the
            # SURVIVING ShareContents, so a storage this row UNIQUELY fed would
            # keep a stale snapshot AND a stale actual correction (entity total !=
            # counted). Capture BOTH halves before the delete, then re-cascade +
            # re-derive corrections (mirrors the service-layer delete_share_planning).
            deleted_movements = list(
                MovementShareArticle.objects.for_share_contents(instance)
            )
            instance.delete()
            if share_id:
                recompute_shares([share_id])
            if deleted_movements:
                SnapshotService.cascade_for_movements(deleted_movements)
                recalculate_actual_corrections(deleted_movements)


class ShareViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = ShareSerializer

    @extend_schema(
        parameters=[
            get_year_parameter(required=False),
            get_delivery_week_parameter(required=False),
            get_delivery_day_parameter(required=False),
            get_share_type_parameter(required=False),
            get_share_type_variation_parameter(),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Share]:
        queryset = Share.objects.all()
        params = validate_query_params(
            self.request,
            optional=[
                "year",
                "delivery_week",
                "delivery_day",
                "share_type",
                "share_type_variation",
            ],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        delivery_day = params["delivery_day"]
        share_type = params["share_type"]
        share_type_variation = params["share_type_variation"]

        if year is not None:
            queryset = queryset.filter(year=year)
        if delivery_week is not None:
            queryset = queryset.filter(delivery_week=delivery_week)
        if delivery_day is not None:
            queryset = queryset.filter(delivery_day=delivery_day)
        if share_type is not None:
            queryset = queryset.filter(share_type_variation__share_type=share_type)
        if share_type_variation is not None:
            queryset = queryset.filter(share_type_variation=share_type_variation)

        queryset = queryset.annotate(
            delivery_day_number=F("delivery_day__day_number"),
            share_type_name=F("share_type_variation__share_type__name"),
            share_type_variation_size=F("share_type_variation__size"),
            share_type_variation_average_weight=F(
                "share_type_variation__average_weight"
            ),
        )
        # Order by ``sort_order`` on the underlying variation so
        # ShareWeights.tsx (and any other consumer of the shares list)
        # matches the office's configured display order. ``id`` is the
        # final tiebreaker for stability when ``sort_order`` ties.
        queryset = queryset.order_by(
            "share_type_variation__sort_order",
            "id",
        )
        return queryset

    @extend_schema(
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            get_day_number_parameter(required=False),
        ],
        responses={200: ShareDayPlanningRowSerializer(many=True)},
        description="Get day-level planning data for shares in a given week.",
    )
    @action(detail=False, methods=["get"])
    def get_days(self, request: Request, filter_day: int | None = None) -> Response:
        params = validate_query_params(
            request, optional=["year", "delivery_week", "day_number"]
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        delivery_day = params["day_number"]

        days_to_process = [delivery_day] if delivery_day is not None else list(range(7))
        if filter_day is not None:
            days_to_process = [int(filter_day)]

        # One windowed query for every requested weekday (with delivery_day
        # select_related so _build_day_data doesn't lazy-load it per row),
        # instead of a query per day + a lazy FK load each. Index by day_number,
        # keeping the first share per day (Share is one-per (year, week, day)).
        shares_by_day: dict[int, Share] = {}
        for share in (
            Share.objects.filter(
                year=year,
                delivery_week=delivery_week,
                delivery_day__day_number__in=days_to_process,
            )
            .select_related("delivery_day")
            .order_by("id")
        ):
            if share.delivery_day is not None:
                shares_by_day.setdefault(share.delivery_day.day_number, share)

        result = []
        for day_num in days_to_process:
            share = shares_by_day.get(day_num)
            if share is not None:
                result.append(_build_day_data(share, day_num))

        return Response(result)

    @extend_schema(
        # The body carries the editable day-level fields (any subset); the
        # service merges only the keys present. Mirrors ``SHARE_DAY_FIELDS`` in
        # ``shares_day_change_service`` — keep in sync.
        request=inline_serializer(
            name="ShareBulkDayUpdateRequest",
            fields={
                # changed_day_number IS honoured by SharesDayChangeService.apply
                # (it's in SHARE_DAY_FIELDS) and edited via ShareDays.tsx, so it
                # must be in the documented schema too (MEM-9).
                "changed_day_number": drf_serializers.IntegerField(
                    required=False, allow_null=True
                ),
                "harvesting_day": drf_serializers.IntegerField(
                    required=False, allow_null=True
                ),
                "packing_day": drf_serializers.IntegerField(
                    required=False, allow_null=True
                ),
                "washing_day": drf_serializers.IntegerField(
                    required=False, allow_null=True
                ),
                "cleaning_day": drf_serializers.IntegerField(
                    required=False, allow_null=True
                ),
                "get_current_stock_day": drf_serializers.IntegerField(
                    required=False, allow_null=True
                ),
            },
        ),
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            get_day_number_parameter(required=False),
            catalogue_param(
                "force",
                required=False,
                description="Apply the change even when the week is in the past.",
            ),
        ],
        responses={
            200: ShareDayPlanningRowSerializer(many=True),
            # Missing year / delivery_week query params.
            400: ErrorResponseSerializer,
            # ``PastWeekError`` — week already past/current and force not set.
            409: ErrorResponseSerializer,
        },
        description=(
            "Bulk update day-level fields on shares for a given week. "
            "If harvesting/packing/washing/cleaning_day changes, the "
            "linked theoretical objects and movements are recreated."
        ),
    )
    @action(detail=False, methods=["put"])
    def bulk_update(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week"],
            optional=["day_number", "force"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        delivery_day = params["day_number"]
        force = params["force"] or False

        # ``PastWeekError`` (409) propagates to the exception handler.
        SharesDayChangeService.apply(
            year=year,
            delivery_week=delivery_week,
            day_number=delivery_day,
            data=request.data,
            force=force,
        )

        return self.get_days(request, filter_day=delivery_day)

    @extend_schema(
        description="Export share weight averages as CSV for a date range, grouped by week.",
        parameters=EXPORT_DATE_RANGE_PARAMETERS,
        responses={
            (200, "text/csv"): OpenApiTypes.BINARY,
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def export_csv(self, request: Request) -> StreamingHttpResponse:
        params = validate_query_params(request, required=["date_from", "date_to"])
        start = params["date_from"]
        end = params["date_to"]

        start_iso = start.isocalendar()
        end_iso = end.isocalendar()

        # Narrow to the (ISO year, ISO week) window in SQL rather than pulling
        # whole calendar years and discarding weeks in Python. Share.year /
        # delivery_week are ISO (week_day_to_date reads them as ISO), so the
        # (year, week) tuple orders monotonically with the date and this
        # lexicographic range is a safe superset of the exact day-level filter
        # applied below.
        if start_iso[0] == end_iso[0]:
            week_window = Q(
                year=start_iso[0],
                delivery_week__gte=start_iso[1],
                delivery_week__lte=end_iso[1],
            )
        else:
            week_window = (
                Q(year=start_iso[0], delivery_week__gte=start_iso[1])
                | Q(year__gt=start_iso[0], year__lt=end_iso[0])
                | Q(year=end_iso[0], delivery_week__lte=end_iso[1])
            )

        shares = (
            Share.objects.select_related(
                "share_type_variation__share_type",
            )
            .filter(week_window)
            .order_by("year", "delivery_week")
        )

        # Filter to exact week range
        filtered = []
        for s in shares:
            try:
                week_start = week_day_to_date(s.year, s.delivery_week, 0)
                if start <= week_start <= end:
                    filtered.append(s)
            except (ValueError, TypeError):
                continue

        # Collect all unique variations (sorted)
        variations: dict[str, dict] = {}
        for s in filtered:
            v = s.share_type_variation
            key = f"{v.share_type.name} {v.get_size_display()}"
            if key not in variations:
                variations[key] = {
                    "label": key,
                    # Keep the target as Decimal (it's a DecimalField); the
                    # CSV formatter quantizes it. Casting to float here and
                    # round-tripping through ``Decimal(f"{t:.3f}")`` below
                    # was the money/quantity-rule violation.
                    "target": v.average_weight or None,
                }

        sorted_variations = sorted(variations.keys())

        # Collect all unique weeks (sorted)
        weeks: list[tuple[int, int]] = sorted(
            {(s.year, s.delivery_week) for s in filtered}
        )

        # Build averages: (year, week, variation_key) -> avg
        avg_data: dict[tuple[int, int, str], list[float]] = {}
        for s in filtered:
            v = s.share_type_variation
            key = f"{v.share_type.name} {v.get_size_display()}"
            weights = [
                w
                for w in [s.weight1, s.weight2, s.weight3, s.weight4]
                if w is not None and w > 0
            ]
            if weights:
                avg = sum(weights) / len(weights)
                avg_data.setdefault((s.year, s.delivery_week, key), []).append(avg)

        from ..utils.csv_format import get_csv_dialect

        dialect = get_csv_dialect()
        writer = csv.writer(CsvEchoBuffer(), delimiter=dialect.delimiter)

        # ``variations`` / ``weeks`` / ``avg_data`` are already materialized
        # above, so the generator streams the output rows without touching the
        # DB after the view returns.
        def rows() -> Iterator[str]:
            yield "\ufeff"  # BOM first so Excel opens UTF-8 correctly.

            # Header: KW | Variation1 | Variation2 | ...
            header = ["KW"]
            for variation in sorted_variations:
                header.append(variations[variation]["label"])
            yield writer.writerow(escape_csv_row(header))

            # Target weight row
            target_row = ["Soll"]
            for variation in sorted_variations:
                t = variations[variation]["target"]
                target_row.append(dialect.format(quantize_weight(t)) if t else "")
            yield writer.writerow(escape_csv_row(target_row))

            # Data rows per week
            for year, week in weeks:
                row = [f"KW {week}/{year}"]
                for variation in sorted_variations:
                    avgs = avg_data.get((year, week, variation), [])
                    if avgs:
                        overall = sum(avgs) / len(avgs)
                        row.append(dialect.format(quantize_weight(overall)))
                    else:
                        row.append("")
                yield writer.writerow(escape_csv_row(row))

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        filename = f"anteilsgewichte_{start.isoformat()}_{end.isoformat()}"
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return response


# Composite id schema for a default-share-content slot:
# ``{year}_{share_article}_{unit}_{size}``.
_DEFAULT_SHARE_CONTENT_ID_FIELDS = [
    ("year", int),
    ("share_article", str),
    ("unit", str),
    ("size", str),
]


class DefaultShareContentViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    # Pure ViewSet — every @action below has its own @extend_schema.
    # This placeholder silences spectacular's class-level "unable to
    # guess serializer" warning without affecting the actual schema.
    serializer_class = DefaultShareContentResponseSerializer

    @extend_schema(
        parameters=[
            get_year_parameter(),
            get_share_option_parameter(),
        ],
        description="List default share content grouped by article/unit/size.",
        responses={
            200: DefaultShareContentResponseSerializer(many=True),
            # Non-integer ``year`` query param.
            400: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def bulk_list(self, request: Request) -> Response:
        params = validate_query_params(request, optional=["year", "share_option"])
        year = params["year"]
        share_option = params["share_option"]

        results = DefaultShareContentService.get_default_share_content_list(year)

        # Filter to the requested share type
        results = [r for r in results if r.get("share_option") == share_option]

        return Response(results, status=status.HTTP_200_OK)

    @extend_schema(
        description="Create default share content entries.",
        request=DefaultShareContentRequestSerializer,
        responses={
            200: DefaultShareContentResponseSerializer,
            # ``ShareArticleNotFound`` — collection POST, no auto-404.
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"])
    def bulk_create(self, request: Request) -> Response:
        serializer = DefaultShareContentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        # ``validated`` carries the dynamic ``amount_<variation_id>`` cells:
        # ``DynamicAmountKeysMixin`` validates and merges them back in, so the
        # service reads the amounts straight from the validated payload.
        DefaultShareContentService.create_default_share_content(validated)

        result_data = DefaultShareContentService.get_default_share_content(
            validated.get("year"),
            validated.get("share_article"),
            validated.get("unit"),
            validated.get("size"),
        )

        return Response(result_data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "Update a SINGLE default-share-content slot. Despite the "
            "``bulk_update`` route name this is not a bulk operation: each "
            "call rewrites exactly one composite slot identified by "
            "``year_shareArticleId_unit_size``."
        ),
        request=DefaultShareContentRequestSerializer,
        responses={200: DefaultShareContentResponseSerializer},
    )
    @action(
        detail=False,
        methods=["put", "patch"],
        url_path="bulk_update/(?P<composite_id>[^/.]+)",
    )
    def bulk_update(
        self, request: Request, composite_id: str | None = None
    ) -> Response:
        """Update ONE ``(year, share_article, unit, size)`` slot.

        Not a bulk endpoint — the ``bulk_update`` route name is historical.
        The composite id pins a single slot; the body carries the new
        per-variation amounts for that slot.
        """
        parsed = parse_composite_pk(
            composite_id,
            fields=_DEFAULT_SHARE_CONTENT_ID_FIELDS,
            code="default_share_content.invalid_composite_id",
        )
        year = parsed["year"]
        share_article_id = parsed["share_article"]
        unit = parsed["unit"]
        size = parsed["size"]

        data = request.data.copy()
        data["share_article"] = share_article_id
        data["year"] = year
        data["unit"] = unit
        data["size"] = size

        # ``partial=True``: the composite id already supplies the slot identity,
        # so a PATCH body needn't repeat every required field. ``validated_data``
        # carries the dynamic ``amount_<variation_id>`` cells (merged by
        # ``DynamicAmountKeysMixin``) alongside the injected slot fields.
        serializer = DefaultShareContentRequestSerializer(data=data, partial=True)
        serializer.is_valid(raise_exception=True)

        DefaultShareContentService.update_default_share_content(
            year, share_article_id, serializer.validated_data
        )

        result_data = DefaultShareContentService.get_default_share_content(
            year, share_article_id, unit, size
        )
        return Response(result_data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "Delete a SINGLE default-share-content slot. Despite the "
            "``bulk_delete`` route name this is not a bulk operation: each "
            "call targets exactly one composite slot identified by "
            "``year_shareArticleId_unit_size`` (``deleted_count`` counts the "
            "per-variation rows composing that slot)."
        ),
        responses={
            200: inline_serializer(
                name="DefaultShareContentBulkDeleteResponse",
                fields={
                    "message": drf_serializers.CharField(),
                    "deleted_count": drf_serializers.IntegerField(),
                },
            ),
            # ``CommissioningError`` — missing/malformed composite ID
            # (DELETE has no request body, so no auto-400).
            400: ErrorResponseSerializer,
            # ``ShareArticleNotFound``.
            404: ErrorResponseSerializer,
        },
    )
    @action(
        detail=False,
        methods=["delete"],
        url_path="bulk_delete/(?P<composite_id>[^/.]+)",
    )
    def bulk_delete(
        self, request: Request, composite_id: str | None = None
    ) -> Response:
        """Delete ONE ``(year, share_article, unit, size)`` slot.

        Not a bulk endpoint — the ``bulk_delete`` route name is historical.
        The composite id pins a single slot; the service removes every
        per-variation row composing it (hence ``deleted_count``) and
        cascades to the future ShareContent the slot materialised.
        """
        parsed = parse_composite_pk(
            composite_id,
            fields=_DEFAULT_SHARE_CONTENT_ID_FIELDS,
            code="default_share_content.invalid_composite_id",
        )
        year = parsed["year"]
        share_article_id = parsed["share_article"]
        unit = parsed["unit"]
        size = parsed["size"]
        share_article = get_or_404(
            ShareArticle,
            share_article_id,
            "Share article",
            error_cls=ShareArticleNotFound,
        )

        deleted_count = DefaultShareContentService.delete_default_share_content_bulk(
            year, share_article, unit, size
        )

        return Response(
            {
                "message": f"Successfully deleted {deleted_count} default share content objects",
                "deleted_count": deleted_count,
            },
            status=status.HTTP_200_OK,
        )


class ShareDeliveryOverviewViewSet(
    _ShareDeliveryWriteChoreographyMixin, RolePermissionsMixin, viewsets.ModelViewSet
):
    """Office grid over ShareDeliveries (Abos > ShareDeliveries): list with
    member/year filters and full CRUD, including moving a delivery to another
    share/week. Writes re-plan charges and rebuild the week's planning data."""

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = ShareDeliveryOverviewSerializer

    @extend_schema(
        parameters=[
            get_year_parameter(required=False),
            get_member_parameter(),
            get_delivery_station_parameter(required=False),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_update(self, serializer):
        from ..services.recompute import recompute_shares

        instance = serializer.instance
        # Capture the pre-save share: the serializer is fields="__all__", so a
        # PATCH can also reassign ``share`` — both the old and the new share
        # then need a rebuild (the old one lost a delivery, the new one gained).
        old_share_id = instance.share_id
        target_delivery_station_day = serializer.validated_data.get(
            "delivery_station_day", instance.delivery_station_day
        )
        # Effective share after save: an explicit ``share`` reassignment in the
        # body wins, otherwise the row keeps its current Share. The grid
        # round-trips the current ``share`` id back with a station-day edit, so
        # moving a delivery to a station-day on ANOTHER weekday would leave the
        # old-weekday Share on the row and trip ShareDelivery.clean
        # ("Delivery day of Share and DeliveryStationDay must match"). Re-point
        # the Share to the target station-day's weekday (get-or-create) so the
        # move persists — the physical delivery slot drives the day.
        effective_share = serializer.validated_data.get("share") or instance.share
        if (
            target_delivery_station_day
            and effective_share
            and target_delivery_station_day.delivery_day_id
            != effective_share.delivery_day_id
        ):
            serializer.validated_data["share"] = self._share_for_delivery_day(
                effective_share, target_delivery_station_day.delivery_day
            )
        with transaction.atomic():
            self._assert_capacity_for_station_day_move(
                instance, target_delivery_station_day
            )
            instance = serializer.save()
            self._notify_subscription_changed_for(instance)
            # delivery_station_day / joker_taken / is_opted_in are all demand
            # inputs — rebuild the share's theoreticals + SHARECONTENT movements
            # so harvest/packing/stock match the edit. Without it the office's
            # edits on the Abos > ShareDeliveries grid leave planning stale.
            # recompute_shares drops None + dedups, so {old, new} is safe.
            recompute_shares({old_share_id, instance.share_id})

    def get_queryset(self) -> QuerySet[ShareDelivery]:
        queryset = ShareDelivery.objects.all()
        params = validate_query_params(
            self.request, optional=["year", "member", "delivery_station"]
        )
        year = params["year"]
        member = params["member"]
        delivery_station = params["delivery_station"]

        # Filter each param independently so the view works with year alone
        # (all members for that year), year + member (one member), or neither.
        # The previous ``if year and member`` returned the *whole* table when a
        # member wasn't supplied — ignoring the year entirely.
        if year:
            queryset = queryset.filter(share__year=year)
        if member:
            queryset = queryset.filter(subscription__member=member)
        if delivery_station:
            queryset = queryset.filter(
                delivery_station_day__delivery_station=delivery_station
            )

        # ``select_related`` because the serializer's ``get_delivery_date``
        # walks ``share`` → ``share.delivery_day`` per row — without this the
        # all-members result set is a textbook N+1.
        queryset = (
            queryset.select_related("share", "share__delivery_day")
            .annotate(
                share_type_variation_string=Concat(
                    F("subscription__share_type_variation__share_type__name"),
                    Value(" - "),
                    F("subscription__share_type_variation__size"),
                    output_field=CharField(),
                ),
                quantity=F("subscription__quantity"),
                delivery_week=F("share__delivery_week"),
            )
            .order_by("share__delivery_week")
        )

        return queryset


class ShareDeliveryDetailsViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = ShareDeliveryOverviewSerializer
    # Read-only: the UI consumes only the aggregated ``list`` grid below. The
    # inherited create/update/destroy verbs would mutate demand-driving
    # ShareDelivery fields (delivery_station_day / joker_taken / is_opted_in)
    # WITHOUT a recompute — close that latent gap by disabling them. Editing
    # goes through the recompute-aware ShareDeliveryViewSet /
    # ShareDeliveryOverviewViewSet.
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        parameters=[
            get_year_parameter(),
            get_delivery_week_parameter(),
            get_day_number_parameter(),
            get_delivery_station_parameter(),
        ],
        responses={200: ShareDeliveryDetailsRowSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.get_queryset()

        result: dict[str, dict[str, Any]] = {}
        for delivery in queryset:
            member_name = delivery.name
            if member_name not in result:
                result[member_name] = {"id": delivery.id, "name": member_name}
            result[member_name][
                f"variation_{delivery.share_type_variation_id}"
            ] = delivery.quantity

        return Response(list(result.values()))

    @extend_schema(
        parameters=[
            get_year_parameter(required=True),
            get_delivery_week_parameter(required=True),
            get_day_number_parameter(required=True),
            get_delivery_station_parameter(required=True),
        ],
        responses={200: StationMemberMatrixSerializer},
        description=(
            "Member × box-combination matrix for one delivery station: one row "
            "per member, one column per box combination (a base box plus its "
            "packed-in add-ons), each cell the member's box count of that "
            "combination. Uses the SAME combination columns as the packing "
            "boxes matrix."
        ),
    )
    @action(detail=False, methods=["get"], url_path="matrix")
    def matrix(self, request: Request) -> Response:
        params = validate_query_params(
            request,
            required=["year", "delivery_week", "day_number", "delivery_station"],
        )
        result = PackingListBoxesMatrixService.get_station_member_matrix(
            year=params["year"],
            delivery_week=params["delivery_week"],
            day_number=params["day_number"],
            delivery_station=params["delivery_station"],
        )
        return Response(result, status=status.HTTP_200_OK)

    def get_queryset(self) -> QuerySet[ShareDelivery]:
        # Only deliveries that actually ship belong on a station pickup sheet —
        # ``.shippable()`` excludes jokered + opted-out (on-off) rows via the
        # canonical ship predicate, the same rule demand/billing enforce.
        # Without it a jokered or not-confirmed delivery prints at full quantity.
        queryset = ShareDelivery.objects.shippable()
        params = validate_query_params(
            self.request,
            optional=["year", "delivery_week", "day_number", "delivery_station"],
        )
        year = params["year"]
        delivery_week = params["delivery_week"]
        day_number = params["day_number"]
        delivery_station = params["delivery_station"]

        if year and delivery_week and day_number is not None and delivery_station:
            queryset = queryset.filter(
                share__year=year,
                share__delivery_week=delivery_week,
                share__delivery_day__day_number=day_number,
                delivery_station_day__delivery_station=delivery_station,
            ).order_by(
                "subscription__member__last_name",
                "subscription__member__first_name",
            )

        queryset = queryset.annotate(
            name=Case(
                When(
                    subscription__member__pickup_name__isnull=False,
                    then=F("subscription__member__pickup_name"),
                ),
                default=Concat(
                    F("subscription__member__last_name"),
                    Value(" "),
                    F("subscription__member__first_name"),
                    output_field=CharField(),
                ),
                output_field=CharField(),
            ),
            share_type_variation_id=F("subscription__share_type_variation__id"),
            share_type_variation_string=Concat(
                F("subscription__share_type_variation__share_type__name"),
                Value(" - "),
                F("subscription__share_type_variation__size"),
                output_field=CharField(),
            ),
            quantity=F("subscription__quantity"),
        )

        return queryset


class ShareTypeVariationGrossPriceViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = ShareTypeVariationGrossPriceSerializer

    @extend_schema(parameters=[get_share_type_variation_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        # One query telling which of the listed variations already have a
        # subscription; the serializer reads it via context to mark those
        # variations' prices non-deletable without an N+1.
        variation_ids = list(
            queryset.values_list("share_type_variation_id", flat=True).distinct()
        )
        variation_ids_with_subscriptions = set(
            Subscription.objects.filter(
                share_type_variation_id__in=variation_ids
            ).values_list("share_type_variation_id", flat=True)
        )
        serializer = self.get_serializer(
            queryset,
            many=True,
            context={
                **self.get_serializer_context(),
                "variation_ids_with_subscriptions": variation_ids_with_subscriptions,
            },
        )
        return Response(serializer.data)

    def get_queryset(self) -> QuerySet[ShareTypeVariationGrossPrice]:
        queryset = ShareTypeVariationGrossPrice.objects.all()

        share_type_variation = validate_query_params(
            self.request, optional=["share_type_variation"]
        )["share_type_variation"]
        if share_type_variation is not None:
            queryset = queryset.filter(share_type_variation=share_type_variation)

        # Latest first — modals scroll through price history newest-on-top.
        # Tie-break on id so the order is stable when two rows share a date.
        return queryset.annotate(
            share_type_variation_size=F("share_type_variation__size")
        ).order_by("-valid_from", "-id")


class VirtualComponentsViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """ViewSet for managing VirtualVariationComponent relationships."""

    read_permission = IsStaff
    write_permission = IsOffice

    @extend_schema(
        parameters=[
            catalogue_param(
                "virtual_variation",
                required=False,
                description="Virtual variation ID to list components for",
            ),
            catalogue_param(
                "physical_variation",
                required=False,
                description="Physical variation ID to find parent virtual variations",
            ),
        ],
        responses=VirtualVariationComponentListItemSerializer(many=True),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.get_queryset()

        result = [
            {
                "id": c.id,
                "virtual_variation": c.virtual_variation_id,
                "physical_variation": c.physical_variation_id,
                "physical_variation_name": c.physical_variation.size,
                "quantity": float(c.quantity),
            }
            for c in queryset
        ]

        return Response(result)

    def get_queryset(self) -> QuerySet[VirtualVariationComponent]:
        queryset = VirtualVariationComponent.objects.all()

        params = validate_query_params(
            self.request, optional=["virtual_variation", "physical_variation"]
        )
        virtual_variation = params["virtual_variation"]
        if virtual_variation:
            queryset = queryset.filter(virtual_variation_id=virtual_variation)

        physical_variation = params["physical_variation"]
        if physical_variation:
            queryset = queryset.filter(physical_variation_id=physical_variation)

        return queryset

    @extend_schema(
        description="Bulk create/replace virtual variation components.",
        request=VirtualVariationComponentsRequestSerializer,
        responses={
            200: VirtualVariationComponentsResponseSerializer,
            201: VirtualVariationComponentsResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = VirtualVariationComponentsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        virtual_variation_id = serializer.validated_data["virtual_variation"]
        components = serializer.validated_data["components"]

        virtual_variation = get_or_404(
            ShareTypeVariation,
            virtual_variation_id,
            "Share type variation",
            error_cls=ShareTypeVariationNotFound,
        )

        # Capture the OLD components' physical variations BEFORE the rewrite —
        # changing this virtual variation's component config re-weights how its
        # demand fans into its physical variations, so the materialised Shares
        # of BOTH the old and the new physical variations go stale (demand input
        # via batch_get_physical_variation_totals) and must be recomputed.
        affected_physical_ids: set = set(
            VirtualVariationComponent.objects.filter(
                virtual_variation_id=virtual_variation_id
            ).values_list("physical_variation_id", flat=True)
        )

        VirtualVariationComponent.objects.filter(
            virtual_variation_id=virtual_variation_id
        ).delete()

        if not components:
            virtual_variation.variation_type = ShareTypeVariation.VariationType.PHYSICAL
            virtual_variation.save()
            self._recompute_for_physical_variations(affected_physical_ids)
            return Response(
                {
                    "virtual_variation": virtual_variation_id,
                    "variation_type": ShareTypeVariation.VariationType.PHYSICAL,
                    "components": [],
                },
                status=status.HTTP_200_OK,
            )

        virtual_variation.variation_type = ShareTypeVariation.VariationType.VIRTUAL
        virtual_variation.save()

        created_components = []
        for component_data in components:
            physical_variation_id = component_data.get("physical_variation")
            quantity = component_data.get("quantity", 1.0)

            if not physical_variation_id:
                continue

            try:
                physical_variation = ShareTypeVariation.objects.get(
                    id=physical_variation_id
                )
            except ShareTypeVariation.DoesNotExist as exc:
                raise CommissioningError(
                    f"ShareTypeVariation with id {physical_variation_id} does not exist",
                    code="virtual_component.physical_variation_not_found",
                ) from exc

            if (
                physical_variation.variation_type
                != ShareTypeVariation.VariationType.PHYSICAL
            ):
                raise VirtualComponentNotPhysical(
                    f"Variation {physical_variation_id} is not a physical variation"
                )

            component = VirtualVariationComponent.objects.create(
                virtual_variation=virtual_variation,
                physical_variation=physical_variation,
                quantity=quantity,
            )
            affected_physical_ids.add(physical_variation.id)
            created_components.append(
                {
                    "id": component.id,
                    "physical_variation": physical_variation_id,
                    "physical_variation_name": physical_variation.size,
                    "quantity": float(component.quantity),
                }
            )

        self._recompute_for_physical_variations(affected_physical_ids)
        return Response(
            {
                "virtual_variation": virtual_variation_id,
                "variation_type": ShareTypeVariation.VariationType.VIRTUAL,
                "components": created_components,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _recompute_for_physical_variations(physical_variation_ids: set) -> None:
        """Rebuild theoreticals/SHARECONTENT movements for every current-or-
        future Share of the given physical variations, after a virtual
        variation's component config changed how virtual demand fans into them.
        Scoped to ``year >= current`` so historical seasons aren't re-walked."""
        if not physical_variation_ids:
            return
        from django.utils import timezone

        from ..services.recompute import recompute_shares

        share_ids = list(
            Share.objects.filter(
                share_type_variation_id__in=physical_variation_ids,
                year__gte=timezone.now().year,
            ).values_list("id", flat=True)
        )
        recompute_shares(share_ids)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

_DAY_CHANGE_DEFAULTS = {
    "harvesting_day": "default_harvesting_day",
    "packing_day": "default_packing_day",
    "washing_day": "default_washing_day",
    "cleaning_day": "default_cleaning_day",
    "get_current_stock_day": "default_get_current_stock_day",
}


def _build_day_data(share: Share, day_num: int) -> dict[str, Any]:
    """Build day-level planning data dict from a Share instance."""
    delivery_day = share.delivery_day

    data: dict[str, Any] = {
        "id": day_num + 1,
        "delivery_day": day_num,
        "changed_day_number": share.changed_day_number,
    }

    for field, default_attr in _DAY_CHANGE_DEFAULTS.items():
        value = getattr(share, field)
        data[field] = value
        data[f"{field}_changed"] = (
            value != getattr(delivery_day, default_attr) if value is not None else False
        )

    return data
