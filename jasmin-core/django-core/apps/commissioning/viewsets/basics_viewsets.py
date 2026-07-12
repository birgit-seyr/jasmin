from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.db.models import (
    BooleanField,
    Case,
    DecimalField,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer

from ..errors import CommissioningError, InvalidQueryParam, ShareArticleNotFound
from ..models import (
    Crate,
    CrateNetPrice,
    DefaultShareArticleInShare,
    Season,
    ShareArticle,
    ShareArticleNetPrice,
    ShareType,
    Storage,
)
from ..models.choices_text import ShareOptions
from ..models.managers import active_on_date_q
from ..schemas import (
    get_active_at_date_parameter,
    get_current_parameter,
    get_is_active_parameter,
    get_price_info_parameter,
    get_share_article_parameter,
    get_share_type_parameter,
    get_share_type_variation_parameter,
)
from ..serializers import (
    CrateSerializer,
    DefaultShareArticleInShareBulkUpsertRequestSerializer,
    DefaultShareArticleInShareSerializer,
    SeasonSerializer,
    ShareArticleNetPriceSerializer,
    ShareArticleSerializer,
    StorageSerializer,
)
from ..utils.query_params import validate_query_params

_SHARE_OPTION_FIELDS: list[str] = ["share_option", "share_option2", "share_option3"]


def _share_option_q(harvest_values: list[str]) -> Q:
    """Build a Q filter matching articles that have any of *harvest_values*
    in one of the share_option fields, or have all three fields null."""
    return (
        Q(share_option__in=harvest_values)
        | Q(share_option2__in=harvest_values)
        | Q(share_option3__in=harvest_values)
        | (
            Q(share_option__isnull=True)
            & Q(share_option2__isnull=True)
            & Q(share_option3__isnull=True)
        )
    )


class SeasonViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing seasons.

    Seasons represent time periods for harvest planning and pricing.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = SeasonSerializer
    queryset = Season.objects.all()


@extend_schema_view(
    create=extend_schema(responses=StorageSerializer),
    retrieve=extend_schema(responses=StorageSerializer),
    update=extend_schema(responses=StorageSerializer),
    partial_update=extend_schema(responses=StorageSerializer),
)
class StorageViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing storage locations.
    """

    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = StorageSerializer

    @extend_schema(
        parameters=[get_is_active_parameter()],
        description="Get all storage locations, optionally filtered by active status",
        responses=StorageSerializer(many=True),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Storage]:
        queryset = Storage.objects.all()
        params = validate_query_params(self.request, optional=["is_active"])
        is_active = params["is_active"]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        queryset = queryset.order_by("name")

        return queryset


class ShareArticleViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing share articles (vegetables, fruits, and other products).

    Supports filtering by:
    - Active status
    - Purchase status
    - Share option associations
    - Price information
    """

    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = ShareArticleSerializer
    pagination_class = OptionalLimitOffsetPagination

    @extend_schema(
        parameters=[
            get_is_active_parameter(),
            OpenApiParameter(
                name="is_purchased",
                type=OpenApiTypes.BOOL,
                required=False,
            ),
            OpenApiParameter(
                name="is_harvest_share_article",
                type=OpenApiTypes.BOOL,
                description=(
                    "Filter to articles used by share options that are planned "
                    "complexly (ShareType.needs_complex_planning=True)."
                ),
                required=False,
            ),
            OpenApiParameter(
                name="share_option",
                type=OpenApiTypes.STR,
                description=(
                    "Filter to articles assigned to this exact share option "
                    "(matches share_option / share_option2 / share_option3)."
                ),
                required=False,
            ),
            get_price_info_parameter(),
            OpenApiParameter(
                name="price_date",
                type=OpenApiTypes.DATE,
                required=False,
            ),
            OpenApiParameter(
                name="is_data_list",
                type=OpenApiTypes.BOOL,
                required=False,
            ),
            OpenApiParameter(
                name="is_sold_to_resellers",
                type=OpenApiTypes.BOOL,
                required=False,
            ),
            OpenApiParameter(
                name="is_extra",
                type=OpenApiTypes.BOOL,
                required=False,
            ),
            OpenApiParameter(
                name="include_extra",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "When true, the ``is_extra`` filter is bypassed and both "
                    "regular and extra share articles are returned. Used by "
                    "Orders / DeliveryNote / Invoice flows where the user "
                    "picks from all articles."
                ),
            ),
        ],
        description="Get all share articles with optional filtering and annotations",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @transaction.atomic
    @extend_schema(
        description="Create a new share article with share option assignments",
        responses={
            201: ShareArticleSerializer,
            # ``CommissioningError`` — invalid share_option_list values.
            400: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data

        share_option_list = validated_data.pop("share_option_list", [])
        share_option_values = self._validate_share_options(share_option_list)
        self._assign_share_options(validated_data, share_option_values)

        instance = ShareArticle.objects.create(**validated_data)
        updated_instance = self._annotated_response_instance(instance.pk)

        response_serializer = self.get_serializer(updated_instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description="Update a share article and its share option assignments",
        responses={
            200: ShareArticleSerializer,
            # ``CommissioningError`` — invalid share_option_list values.
            400: ErrorResponseSerializer,
        },
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data

        share_option_list = validated_data.pop("share_option_list", [])
        share_option_values = self._validate_share_options(share_option_list)
        self._assign_share_options(validated_data, share_option_values)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        updated_instance = self._annotated_response_instance(instance.pk)

        response_serializer = self.get_serializer(updated_instance)
        return Response(response_serializer.data)

    def get_price_annotations(
        self,
        price_date: datetime.date | str,
    ) -> dict[str, Subquery]:
        pricing_at_date = ShareArticleNetPrice.objects.filter(
            active_on_date_q(price_date),
            share_article=OuterRef("pk"),
        ).order_by("-valid_from")

        price_fields = [
            field.name
            for field in ShareArticleNetPrice._meta.fields
            if isinstance(field, DecimalField)
        ]

        return {
            name: Subquery(pricing_at_date.values(name)[:1]) for name in price_fields
        }

    def get_share_options_annotation(self) -> dict[str, Case]:
        """Create boolean annotations for each share option."""
        annotations: dict[str, Case] = {}

        for value, _label in ShareOptions.choices:
            annotations[value.lower()] = Case(
                When(
                    Q(share_option=value)
                    | Q(share_option2=value)
                    | Q(share_option3=value),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )

        return annotations

    def _annotated_response_instance(self, pk: str) -> ShareArticle | None:
        """Refetch a row carrying the data-list annotations (share-option
        booleans + crate names) for create/update responses.

        The list view only adds these under ``?is_data_list=true``, but a
        mutation request doesn't carry that param — so without this the
        create/update response omits the boolean fields, and EditableTable
        patches the row in-place from that response, leaving the checkboxes
        looking unchanged until a hard refresh.
        """
        return (
            ShareArticle.objects.filter(pk=pk)
            .annotate(
                **self.get_share_options_annotation(),
                default_crate_harvest_name=F("default_crate_harvest__short_name"),
                default_crate_reseller_name=F("default_crate_reseller__short_name"),
            )
            .first()
        )

    def get_queryset(self) -> QuerySet[ShareArticle]:
        queryset = ShareArticle.objects.all()

        params = validate_query_params(
            self.request,
            optional=[
                "is_active",
                "is_extra",
                "include_extra",
                "is_purchased",
                "is_harvest_share_article",
                "get_price_info",
                "price_date",
                "is_data_list",
                "is_sold_to_resellers",
                "share_option",
            ],
        )
        is_active = params["is_active"]
        is_extra = params["is_extra"]
        include_extra = params["include_extra"]
        is_purchased = params["is_purchased"]
        is_harvest_share_article = params["is_harvest_share_article"]
        get_price_info = params["get_price_info"]
        # ``price_date`` defaults to today when not supplied (catalogue default
        # is ``None``); the annotation below only fires when it's non-null.
        price_date = params["price_date"] or timezone.now().date()
        is_data_list = params["is_data_list"]
        is_sold_to_resellers = params["is_sold_to_resellers"]
        share_option = params["share_option"]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        # ``include_extra=true`` bypasses the is_extra filter entirely so the
        # caller (Orders, DeliveryNote, Invoice flows) sees both regular and
        # extra share articles. Otherwise we default to ``is_extra=False`` so
        # standard pages only see regular share articles unless they ask for
        # the extras explicitly via ``is_extra``.
        # Detail actions (retrieve/update/partial_update/destroy) must never
        # filter by ``is_extra`` — the row is addressed by primary key and
        # the caller (e.g. ListExtraArticles editing a row) shouldn't have
        # to remember to pass ``include_extra``.
        if self.action in ("list",):
            if not include_extra:
                if is_extra is None:
                    queryset = queryset.filter(is_extra=False)
                else:
                    queryset = queryset.filter(is_extra=is_extra)

        if is_purchased is not None:
            queryset = queryset.filter(is_purchased=is_purchased)

        if get_price_info is not None and price_date is not None:
            queryset = queryset.annotate(**self.get_price_annotations(price_date))

        if is_harvest_share_article is not None:
            # Articles used by any share option that is planned complexly
            # (week-by-week harvest-style planning) — derived from
            # ``ShareType.needs_complex_planning`` rather than a hardcoded
            # HARVEST_SHARE / HARVEST_SHARE_FRUIT list, so a complexly-planned
            # chicken / grain share's articles are included automatically.
            complex_options = list(
                ShareType.objects.filter(needs_complex_planning=True)
                .exclude(share_option__isnull=True)
                .values_list("share_option", flat=True)
                .distinct()
            )
            queryset = queryset.filter(_share_option_q(complex_options))

        # Strict filter to a single share option (matches any of the three
        # share_option fields). Unlike the harvest helpers above it does NOT
        # include articles with all options null — the planning pages want only
        # articles actually assigned to that option (no broccoli on honey).
        if share_option:
            queryset = queryset.filter(
                Q(share_option=share_option)
                | Q(share_option2=share_option)
                | Q(share_option3=share_option)
            )

        if is_sold_to_resellers is not None:
            queryset = queryset.filter(is_sold_to_resellers=is_sold_to_resellers)

        if is_data_list is not None:
            queryset = queryset.annotate(
                **self.get_share_options_annotation(),
                default_crate_harvest_name=F("default_crate_harvest__short_name"),
                default_crate_reseller_name=F("default_crate_reseller__short_name"),
            )

        return queryset.order_by("is_extra", "name")

    @staticmethod
    def _validate_share_options(share_option_list: list[str]) -> list[str]:
        """Validate share option strings against ShareOptions choices."""
        if not share_option_list:
            return []

        valid_values = {v for v, _l in ShareOptions.choices}
        invalid = set(share_option_list) - valid_values

        if invalid:
            # A bare ValueError here would surface as an undeclared 500 —
            # this is caller input, so it must be a 400 with a stable code.
            raise CommissioningError(
                f"Invalid share options: {sorted(invalid)}. "
                f"Valid: {sorted(valid_values)}",
                field="share_option_list",
                code="share_article.invalid_share_option",
            )

        return list(share_option_list)

    @staticmethod
    def _assign_share_options(
        validated_data: dict[str, Any],
        share_option_values: list[str],
    ) -> None:
        """Assign share option strings to share_option, share_option2, share_option3 fields."""
        for field in _SHARE_OPTION_FIELDS:
            validated_data[field] = None

        # strict=False on purpose: callers may send fewer share_option values
        # than there are fields (extras stay None from the reset above).
        for field, value in zip(
            _SHARE_OPTION_FIELDS, share_option_values, strict=False
        ):
            validated_data[field] = value


class ShareArticleNetPriceViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing share article prices.

    Prices are time-bound with valid_from and valid_until dates.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = ShareArticleNetPriceSerializer

    @extend_schema(
        parameters=[
            get_share_article_parameter(required=False),
            get_current_parameter(),
            get_active_at_date_parameter(),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ShareArticleNetPrice]:
        params = validate_query_params(
            self.request,
            optional=["share_article", "current", "active_at_date"],
        )
        share_article = params["share_article"]
        current = params["current"]
        active_at_date = params["active_at_date"]

        if active_at_date:
            queryset = ShareArticleNetPrice.current.active_at_date(active_at_date)
        else:
            queryset = ShareArticleNetPrice.objects.all()
            # Truthiness, not ``is not None``: ``current`` is a strict bool, so
            # ``?current=false`` must NOT restrict to the open record.
            if current:
                queryset = queryset.filter(valid_until__isnull=True)

        if share_article is not None:
            try:
                queryset = queryset.filter(share_article=share_article)
            except (ValueError, TypeError) as exc:
                raise InvalidQueryParam(
                    "Invalid value for share_article.", field="share_article"
                ) from exc

        # Latest first — modals scroll through price history newest-on-top.
        # Tie-break on id so the order is stable when two rows share a date.
        # select_related the parent: the serializer's get_can_be_deleted calls
        # parent_in_use(obj.share_article) for each distinct active-priced
        # article, which would otherwise lazy-load the article per row.
        return (
            queryset.select_related("share_article")
            .annotate(share_article_name=F("share_article__name"))
            .order_by("-valid_from", "-id")
        )


class CrateViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing crates (containers for delivery).
    """

    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = CrateSerializer

    @extend_schema(
        parameters=[
            get_price_info_parameter(),
            get_is_active_parameter(),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_current_price_annotations(self) -> dict[str, Subquery]:
        today = timezone.now().date()
        current_pricing = CrateNetPrice.objects.filter(
            active_on_date_q(today),
            crate=OuterRef("pk"),
        ).order_by("-valid_from")

        return {
            "price": Subquery(current_pricing.values("price")[:1]),
            "tax_rate": Subquery(current_pricing.values("tax_rate")[:1]),
        }

    def get_queryset(self) -> QuerySet[Crate]:
        queryset = Crate.objects.all()

        params = validate_query_params(
            self.request, optional=["get_price_info", "is_active"]
        )
        get_price_info = params["get_price_info"]
        is_active = params["is_active"]

        if get_price_info is not None:
            queryset = queryset.annotate(**self.get_current_price_annotations())
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        return queryset


class DefaultShareArticleInShareViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Default quantity of a ``ShareArticle`` inside each ``ShareTypeVariation``.

    Edited from the ``DefaultShareArticlesInShare`` configuration page as a
    pivot table: rows are share articles, columns are share-type variations
    (grouped by their share type). Each cell stores the quantity in the
    underlying ``DefaultShareArticleInShare`` row.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = DefaultShareArticleInShareSerializer

    @extend_schema(
        parameters=[
            get_share_article_parameter(required=False),
            get_share_type_variation_parameter(required=False),
            get_share_type_parameter(required=False),
        ],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[DefaultShareArticleInShare]:
        queryset = DefaultShareArticleInShare.objects.select_related(
            "share_article", "share_type_variation", "share_type_variation__share_type"
        )
        params = validate_query_params(
            self.request,
            optional=["share_article", "share_type_variation", "share_type"],
        )
        share_article = params["share_article"]
        share_type_variation = params["share_type_variation"]
        share_type = params["share_type"]
        if share_article:
            queryset = queryset.filter(share_article_id=share_article)
        if share_type_variation:
            queryset = queryset.filter(share_type_variation_id=share_type_variation)
        if share_type:
            queryset = queryset.filter(share_type_variation__share_type_id=share_type)
        return queryset.order_by(
            "share_article__name",
            "share_type_variation__share_type__name",
            "share_type_variation__size",
        )

    @extend_schema(
        summary="Bulk upsert default-shares for one share article",
        request=DefaultShareArticleInShareBulkUpsertRequestSerializer,
        responses={
            200: DefaultShareArticleInShareSerializer(many=True),
            # ``ShareArticleNotFound`` — collection POST, no auto-404.
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk_upsert")
    @transaction.atomic
    def bulk_upsert(self, request: Request) -> Response:
        payload_serializer = DefaultShareArticleInShareBulkUpsertRequestSerializer(
            data=request.data
        )
        payload_serializer.is_valid(raise_exception=True)
        data = payload_serializer.validated_data

        share_article = ShareArticle.objects.filter(pk=data["share_article"]).first()
        if share_article is None:
            raise ShareArticleNotFound(
                f"ShareArticle {data['share_article']} not found"
            )

        fallback_unit = share_article.default_movement_unit

        for entry in data["entries"]:
            variation_id = entry["share_type_variation"]
            quantity = entry.get("quantity")
            unit = entry.get("unit") or fallback_unit

            if quantity is None or quantity <= 0:
                DefaultShareArticleInShare.objects.filter(
                    share_article=share_article,
                    share_type_variation_id=variation_id,
                ).delete()
                continue

            DefaultShareArticleInShare.objects.update_or_create(
                share_article=share_article,
                share_type_variation_id=variation_id,
                defaults={"quantity": quantity, "unit": unit},
            )

        rows = (
            DefaultShareArticleInShare.objects.filter(share_article=share_article)
            .select_related("share_type_variation")
            .order_by(
                "share_type_variation__share_type__name", "share_type_variation__size"
            )
        )
        return Response(
            DefaultShareArticleInShareSerializer(rows, many=True).data,
            status=status.HTTP_200_OK,
        )
