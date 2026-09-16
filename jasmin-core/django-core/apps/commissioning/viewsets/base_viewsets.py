from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsStaff, RolePermissionsMixin
from core.errors import ConflictError
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer

from ..schemas import get_is_past_parameter
from ..serializers.serializers_mixin import DeletableMixin
from ..utils.query_params import validate_query_params

# Enforce the serializer's ``can_be_deleted`` flag on ``destroy``.
#
# A ``DeletableMixin`` serializer reports ``can_be_deleted`` and the frontend
# hides the delete button when it is False, but DRF's stock ``destroy`` never
# looks at it — a direct ``DELETE`` bypasses the rule (and CASCADEs away any
# dependent rows). A viewset that mixes this in refuses such a delete with its
# ``not_deletable_error`` (a 409 ``ConflictError`` subclass carrying a per-model
# code). The check calls the very same ``get_can_be_deleted`` the UI flag comes
# from, so the server rule and the hidden button cannot drift.
#
# List it BEFORE ``RolePermissionsMixin`` / ``ModelViewSet`` in the bases.
# Deliberately a comment, not a docstring: drf-spectacular describes a viewset
# without its own docstring by the first docstring in its MRO, so a docstring
# here would replace those endpoints' published descriptions.
# Typed as a GenericAPIView for mypy (``get_serializer``), but a plain mixin at
# runtime, so it is not itself discovered as a view by the permission guard.
if TYPE_CHECKING:
    _DestroyBase = GenericAPIView
else:
    _DestroyBase = object


class CanBeDeletedDestroyMixin(mixins.DestroyModelMixin, _DestroyBase):
    not_deletable_error: type[ConflictError]

    @extend_schema(responses={204: None, 409: ErrorResponseSerializer})
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance: Any) -> None:
        with transaction.atomic():
            # Lock the row before checking: inserting a row that references it
            # takes a KEY SHARE lock on it, so a dependent row created
            # concurrently is either visible to the check or blocked until the
            # delete commits — it can't slip in between and be cascaded away.
            locked = (
                type(instance)._base_manager.select_for_update().get(pk=instance.pk)
            )
            serializer = self.get_serializer(locked)
            if not isinstance(serializer, DeletableMixin):
                raise ImproperlyConfigured(
                    f"{type(self).__name__} enforces can_be_deleted, but its "
                    "serializer is not a DeletableMixin."
                )
            if not serializer.get_can_be_deleted(locked):
                raise self.not_deletable_error(
                    f"{type(locked).__name__} '{locked}' is still in use and "
                    "cannot be deleted.",
                    details={"id": str(locked.pk)},
                )
            super().perform_destroy(locked)


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
        is_list = getattr(self, "action", None) == "list"

        if is_list:
            is_past = validate_query_params(self.request, optional=["is_past"])[
                "is_past"
            ]
            queryset = self.model.active.for_period(is_past=is_past)
        else:
            # A detail route addresses ONE row by id, so it reaches the whole
            # archive and reads no list parameter: a filter left on the URL (a
            # page that keeps its week selector in the query string, a stale
            # bookmark) must not turn an existing row into a 404, nor a valid
            # PATCH into a 400 over a parameter the write ignores.
            queryset = self.model.active.for_period(is_past=True)

        queryset = self.scope_queryset(queryset)
        return self.apply_list_filters(queryset) if is_list else queryset

    def scope_queryset(self, queryset: QuerySet) -> QuerySet:
        """Override to narrow or annotate on EVERY action — a permanent scope
        (what this viewset serves at all) plus the joins its serializer walks."""
        return queryset

    def apply_list_filters(self, queryset: QuerySet) -> QuerySet:
        """Override to apply the query-param filters of the LIST route. Only
        the list action calls this; see ``get_queryset``."""
        return queryset

    @property
    def model(self) -> type[Any]:
        """Derive the model class from the serializer."""
        return serializer_model(self.serializer_class)
