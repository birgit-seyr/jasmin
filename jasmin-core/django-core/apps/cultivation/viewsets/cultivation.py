from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import CanEditCultivation, IsStaff, RolePermissionsMixin

from ..models import CultivationBatch
from ..query_params import validate_query_params
from ..schemas import get_is_greenhouse_parameter, get_year_parameter
from ..serializers import CultivationBatchSerializer


class CultivationBatchViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = CanEditCultivation
    serializer_class = CultivationBatchSerializer

    def get_queryset(self):
        qs = CultivationBatch.objects.select_related(
            "vegetable", "vegetable_set", "used_bed_type"
        ).order_by("planting_week", "id")
        params = validate_query_params(self.request, optional=["year", "is_greenhouse"])
        if params["year"] is not None:
            qs = qs.filter(year=params["year"])
        if params["is_greenhouse"] is not None:
            qs = qs.filter(is_greenhouse=params["is_greenhouse"])
        return qs

    @extend_schema(
        parameters=[
            get_year_parameter(required=False),
            get_is_greenhouse_parameter(),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)
