from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsStaff, RolePermissionsMixin
from core.pagination import OptionalLimitOffsetPagination

from ..schemas import get_share_article_parameter, get_year_parameter
from ..serializers import (
    TheoreticalCleanAmountSerializer,
    TheoreticalHarvestSerializer,
    TheoreticalPurchaseSerializer,
    TheoreticalWashAmountSerializer,
)
from ..utils.query_params import validate_query_params

_LIST_PARAMETERS = [
    get_year_parameter(required=False),
    get_share_article_parameter(required=False),
]

_DEFAULT_WEEKS_BACK = 2


class _TheoreticalBaseViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    pagination_class = OptionalLimitOffsetPagination

    """Base viewset for theoretical amount models filtered by year and share article."""

    read_permission = IsStaff
    write_permission = IsStaff

    def get_queryset(self) -> QuerySet:
        queryset = self.serializer_class.Meta.model.objects.all()

        params = validate_query_params(self.request, optional=["year", "share_article"])
        year = params["year"]
        share_article = params["share_article"]

        if year is not None:
            queryset = queryset.filter(year=year)
        else:
            # Default: only return data from the last N weeks
            cutoff = timezone.localdate() - datetime.timedelta(
                weeks=_DEFAULT_WEEKS_BACK
            )
            iso = cutoff.isocalendar()
            queryset = queryset.filter(year=iso[0], delivery_week__gte=iso[1])

        # Always limit to last N weeks for the current year to keep payloads small
        today = timezone.localdate()
        current_iso = today.isocalendar()
        if year is not None and year == current_iso[0]:
            min_week = current_iso[1] - _DEFAULT_WEEKS_BACK
            if min_week > 0:
                queryset = queryset.filter(delivery_week__gte=min_week)

        if share_article is not None:
            queryset = queryset.filter(share_article__id=share_article)

        # Deterministic ordering so LIMIT/OFFSET pagination can't overlap or
        # skip rows (Postgres gives no order guarantee without an ORDER BY).
        return queryset.annotate(share_article_name=F("share_article__name")).order_by(
            "year", "delivery_week", "day_number", "id"
        )

    @extend_schema(parameters=_LIST_PARAMETERS)
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @transaction.atomic
    def perform_destroy(self, instance: Any) -> None:
        # Deleting a theoretical object cascade-deletes its is_theoretical stock
        # movement (theoretical_* FK on_delete=CASCADE), but plain DRF destroy
        # never recomputes — so the entity's actual-correction amount (stored as
        # counted - Σtheoretical) and its snapshots would be left stale. Capture
        # the movement BEFORE the delete (its dimension keys survive on the
        # in-memory object), then re-cascade + re-derive corrections (mirrors
        # ForecastViewSet.perform_destroy).
        from ..models import (
            MovementShareArticle,
            TheoreticalCleanAmount,
            TheoreticalHarvest,
            TheoreticalPurchase,
            TheoreticalWashAmount,
        )
        from ..services.snapshot_service import SnapshotService
        from ..services.theoretical_objects import recalculate_actual_corrections

        # Each theoretical model maps to exactly one source FK on the movement;
        # filter only that one (Django rejects an FK equality filter against a
        # different model type).
        fk_by_model = {
            TheoreticalHarvest: "theoretical_harvest",
            TheoreticalPurchase: "theoretical_purchase",
            TheoreticalWashAmount: "theoretical_wash_amount",
            TheoreticalCleanAmount: "theoretical_clean_amount",
        }
        fk_name = fk_by_model[self.serializer_class.Meta.model]
        affected_movements = list(
            MovementShareArticle.objects.filter(**{fk_name: instance})
        )

        super().perform_destroy(instance)

        if affected_movements:
            SnapshotService.cascade_for_movements(affected_movements)
            recalculate_actual_corrections(affected_movements)


class TheoreticalHarvestViewSet(_TheoreticalBaseViewSet):
    serializer_class = TheoreticalHarvestSerializer


class TheoreticalCleanAmountViewSet(_TheoreticalBaseViewSet):
    serializer_class = TheoreticalCleanAmountSerializer


class TheoreticalPurchaseViewSet(_TheoreticalBaseViewSet):
    serializer_class = TheoreticalPurchaseSerializer


class TheoreticalWashAmountViewSet(_TheoreticalBaseViewSet):
    serializer_class = TheoreticalWashAmountSerializer
