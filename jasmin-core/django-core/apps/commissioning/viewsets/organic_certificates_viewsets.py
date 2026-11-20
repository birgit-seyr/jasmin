from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin

from ..models import OrganicCertificate
from ..schemas import get_reseller_parameter
from ..serializers import OrganicCertificateSerializer
from ..utils.query_params import validate_query_params


class OrganicCertificateViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """CRUD for a reseller's time-bound organic certificates (office-managed).

    Drives the ListSellers certificate modal; filter the list by ``?reseller=``.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = OrganicCertificateSerializer

    @extend_schema(parameters=[get_reseller_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[OrganicCertificate]:
        queryset = OrganicCertificate.objects.select_related("reseller").order_by(
            "-valid_from"
        )
        params = validate_query_params(self.request, optional=["reseller"])
        reseller = params["reseller"]
        if reseller is not None:
            queryset = queryset.filter(reseller_id=reseller)
        return queryset
