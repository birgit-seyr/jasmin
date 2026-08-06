from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import CultivationBatch
from ..schemas import get_year_parameter
from ..serializers import CultivationBatchSerializer

_IS_GREENHOUSE_PARAM = OpenApiParameter(
    name="is_greenhouse",
    type=OpenApiTypes.BOOL,
    required=False,
    description=(
        "Filter by protected cultivation. The indoor and outdoor batch pages "
        "each show one side; the placement optimizer only ever plans the "
        "outdoor ones."
    ),
)


class CultivationBatchViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = CultivationBatchSerializer

    def get_queryset(self):
        qs = CultivationBatch.objects.select_related(
            "vegetable", "vegetable_set", "used_bed_type"
        ).order_by("planting_week", "id")
        year = self.request.query_params.get("year")
        if year:
            qs = qs.filter(year=year)
        is_greenhouse = self.request.query_params.get("is_greenhouse")
        if is_greenhouse is not None:
            qs = qs.filter(is_greenhouse=is_greenhouse.lower() in ("1", "true", "yes"))
        return qs

    @extend_schema(
        parameters=[get_year_parameter(required=False), _IS_GREENHOUSE_PARAM]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)
