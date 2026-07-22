from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin
from apps.commissioning.schemas import get_is_active_parameter
from apps.commissioning.utils.query_params import validate_query_params

from ..models import AbsenceCategory, Employee, WeeklyPlanCategory
from ..serializers import (
    AbsenceCategorySerializer,
    EmployeeSerializer,
    WeeklyPlanCategorySerializer,
)


class EmployeeViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = EmployeeSerializer

    @extend_schema(parameters=[get_is_active_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Employee]:
        queryset = Employee.objects.all()
        is_active = validate_query_params(self.request, optional=["is_active"])[
            "is_active"
        ]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset


class WeeklyPlanCategoryViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = WeeklyPlanCategorySerializer

    @extend_schema(parameters=[get_is_active_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[WeeklyPlanCategory]:
        queryset = WeeklyPlanCategory.objects.all()
        is_active = validate_query_params(self.request, optional=["is_active"])[
            "is_active"
        ]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset


class AbsenceCategoryViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = AbsenceCategorySerializer

    @extend_schema(parameters=[get_is_active_parameter()])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[AbsenceCategory]:
        queryset = AbsenceCategory.objects.all()
        is_active = validate_query_params(self.request, optional=["is_active"])[
            "is_active"
        ]
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return queryset
