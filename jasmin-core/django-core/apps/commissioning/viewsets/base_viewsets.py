from __future__ import annotations

from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets

from apps.authz.permissions import IsStaff, RolePermissionsMixin
from core.pagination import OptionalLimitOffsetPagination

from ..schemas import get_is_past_parameter
from ..utils.query_params import validate_query_params


class BaseArchivableViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Base ViewSet that selects the active or full-archive manager based on ``is_past``."""

    read_permission = IsStaff
    write_permission = IsStaff
    # ``is_past=true`` bypasses the active-manager cutoff and returns the full
    # multi-year archive; without a pagination class that list is unbounded (a
    # single GET can serialise the whole table). ``OptionalLimitOffsetPagination``
    # stays a plain array by default (``default_limit=None``) so existing callers
    # are unaffected, but lets a caller bound the response with ``?limit=`` —
    # capped at ``max_limit`` (1000).
    pagination_class = OptionalLimitOffsetPagination

    @extend_schema(parameters=[get_is_past_parameter()])
    def list(self, request, *args: Any, **kwargs: Any):
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet:
        params = validate_query_params(self.request, optional=["is_past"])
        is_past = params["is_past"]

        if self.action == "list":
            queryset = self.model.active.for_period(is_past=is_past)
        else:
            queryset = self.model.active.for_period(is_past=True)

        return self.apply_filters(queryset)

    def apply_filters(self, queryset: QuerySet) -> QuerySet:
        """Override in subclasses to apply specific filters."""
        return queryset

    @property
    def model(self) -> type[Model]:
        """Derive the model class from the serializer."""
        return self.serializer_class.Meta.model
