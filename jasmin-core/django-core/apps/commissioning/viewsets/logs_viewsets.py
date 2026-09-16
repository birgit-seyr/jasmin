from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsStaff, RolePermissionsMixin
from apps.shared.request_utils import auth_user
from core.pagination import OptionalLimitOffsetPagination

from ..schemas import get_share_article_parameter, get_year_parameter
from ..serializers import (
    TheoreticalCleanAmountSerializer,
    TheoreticalHarvestSerializer,
    TheoreticalPurchaseSerializer,
    TheoreticalWashAmountSerializer,
)
from ..utils.query_params import validate_query_params
from .base_viewsets import serializer_model

_DEFAULT_WEEKS_BACK = 2


class _TheoreticalBaseViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    pagination_class = OptionalLimitOffsetPagination

    """Base viewset for theoretical amount models filtered by year and share article."""

    read_permission = IsStaff
    write_permission = IsStaff

    def get_queryset(self) -> QuerySet:
        queryset = serializer_model(self.serializer_class).objects.all()

        params = validate_query_params(self.request, optional=["year", "share_article"])
        year = params["year"]
        share_article = params["share_article"]

        if year is not None:
            queryset = queryset.filter(year=year)

        # The recency window trims the LIST payload only — a detail route must
        # still reach a row outside it, or editing/deleting an older entry 404s.
        if getattr(self, "action", None) == "list":
            today = timezone.localdate()
            current_year, current_week = today.isocalendar()[:2]
            if year is None:
                # Default: only return data from the last N weeks. The cutoff
                # falls in the PREVIOUS ISO year during weeks 1-N, so the window
                # has to span the year boundary — pinning it to the cutoff year
                # alone would hide every current-year row each January. It stops
                # at the current year: planning rows exist for future years and
                # this list is unpaginated unless the caller asks for a limit.
                cutoff = today - datetime.timedelta(weeks=_DEFAULT_WEEKS_BACK)
                cutoff_year, cutoff_week = cutoff.isocalendar()[:2]
                queryset = queryset.filter(
                    Q(year=current_year)
                    | Q(year=cutoff_year, delivery_week__gte=cutoff_week)
                )
            elif year == current_year:
                # Same N-week floor for an explicitly requested current year,
                # to keep payloads small.
                min_week = current_week - _DEFAULT_WEEKS_BACK
                if min_week > 0:
                    queryset = queryset.filter(delivery_week__gte=min_week)

        if share_article is not None:
            queryset = queryset.filter(share_article__id=share_article)

        # Deterministic ordering so LIMIT/OFFSET pagination can't overlap or
        # skip rows (Postgres gives no order guarantee without an ORDER BY).
        return queryset.annotate(share_article_name=F("share_article__name")).order_by(
            "year", "delivery_week", "day_number", "id"
        )

    @extend_schema(
        parameters=[
            get_year_parameter(required=False),
            get_share_article_parameter(required=False),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        # Authorship is read-only on the serializer — stamp it here.
        serializer.save(created_by=auth_user(self.request))

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
        fk_name = fk_by_model[serializer_model(self.serializer_class)]
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
