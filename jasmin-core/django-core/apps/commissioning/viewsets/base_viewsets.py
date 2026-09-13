from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets

from apps.authz.permissions import IsStaff, RolePermissionsMixin
from core.pagination import OptionalLimitOffsetPagination

from ..schemas import get_is_past_parameter
from ..utils.query_params import validate_query_params


def serializer_model(serializer_class: Any) -> type[Any]:
    """Return the model a viewset's ``ModelSerializer`` is bound to.

    ``GenericAPIView.serializer_class`` is declared ``type[BaseSerializer] | None``
    — ``None`` because a view may build its serializer in
    ``get_serializer_class()`` instead, and ``BaseSerializer`` because the plain
    base class carries no ``Meta``. Neither case applies to the viewsets that
    call this: each pins one concrete ``ModelSerializer``. Resolving it here
    keeps that assumption in a single place, and turns a misconfigured viewset
    into a named startup-style error instead of an ``AttributeError`` raised from
    the middle of ``get_queryset``.

    Returns ``type[Any]``, not ``type[Model]``: which model comes back depends on
    the subclass that happens to be dispatching, and the stubs put ``objects`` /
    ``active`` on concrete model classes only — so a ``Model`` annotation would
    describe every caller's next line as an error.
    """
    model = getattr(getattr(serializer_class, "Meta", None), "model", None)
    if model is None:
        raise ImproperlyConfigured(
            f"{serializer_class!r} has no Meta.model; this viewset needs a "
            "ModelSerializer bound to a model."
        )
    return model


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
    def model(self) -> type[Any]:
        """Derive the model class from the serializer."""
        return serializer_model(self.serializer_class)
