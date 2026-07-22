from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin

from ..query_params import validate_query_params
from ..schemas import get_week_parameter, get_year_parameter
from ..serializers import (
    WeeklyPlanCopySerializer,
    WeeklyPlanGridSerializer,
    WeeklyPlanReplaceSerializer,
)
from ..services import build_week_grid, copy_week, replace_week


class WeeklyPlanViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """The weekly-plan grid: a dense (category × row × weekday) matrix of
    employee assignments for one ISO week. The grid is materialized server-side
    from sparse ``WeeklyPlan`` rows; the client fetches it, edits locally, and
    writes the whole week back (replace-all)."""

    read_permission = IsStaff
    write_permission = IsOffice

    @extend_schema(
        parameters=[get_year_parameter(), get_week_parameter()],
        responses=WeeklyPlanGridSerializer,
    )
    @action(detail=False, methods=["get"], url_path="grid")
    def grid(self, request: Request) -> Response:
        # A named GET action (not ``list``) so the response is a single grid
        # object, not an array — drf-spectacular array-wraps the ``list`` action.
        params = validate_query_params(request, required=["year", "week"])
        grid = build_week_grid(params["year"], params["week"])
        return Response(WeeklyPlanGridSerializer(grid).data)

    @extend_schema(
        request=WeeklyPlanReplaceSerializer,
        responses=WeeklyPlanGridSerializer,
    )
    def create(self, request: Request) -> Response:
        serializer = WeeklyPlanReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        replace_week(data["year"], data["week"], data["assignments"])
        grid = build_week_grid(data["year"], data["week"])
        return Response(WeeklyPlanGridSerializer(grid).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=WeeklyPlanCopySerializer,
        responses=WeeklyPlanGridSerializer,
    )
    @action(detail=False, methods=["post"], url_path="copy")
    def copy(self, request: Request) -> Response:
        serializer = WeeklyPlanCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        copy_week(data["year"], data["from_week"], data["to_week"])
        grid = build_week_grid(data["year"], data["to_week"])
        return Response(WeeklyPlanGridSerializer(grid).data, status=status.HTTP_200_OK)
