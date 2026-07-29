from typing import Any

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import SolverSettings
from ..serializers import SolverSettingsSerializer


class SolverSettingsViewSet(RolePermissionsMixin, viewsets.GenericViewSet):
    """The tenant's placement-optimizer weights and feature flags.

    A tenant-schema singleton, so the surface is collection-level only: ``list``
    returns THE settings object (not an array) and ``save/`` patches it. Detail
    routes would carry a pk that ``get_object`` ignores, and ``create`` could
    never succeed against the single-active constraint.
    """

    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = SolverSettingsSerializer

    def get_queryset(self):
        return SolverSettings.objects.filter(is_active=True)

    def get_object(self) -> SolverSettings:
        """Always operate on the tenant's active row (get-or-create)."""
        return SolverSettings.get_active()

    @extend_schema(responses={200: SolverSettingsSerializer})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the single solver-settings row for the current tenant."""
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(
        request=inline_serializer(
            name="UpdateSolverSettingsRequest",
            fields={
                "settings": drf_serializers.DictField(
                    child=drf_serializers.JSONField(),
                    help_text="Key/value pairs of solver settings to update.",
                ),
            },
        ),
        responses={200: SolverSettingsSerializer},
    )
    @action(detail=False, methods=["put", "patch"], url_path="save")
    def save_settings(self, request: Request) -> Response:
        """PUT/PATCH the singleton without a pk in the URL.

        Accepts the ``{"settings": {...}}`` envelope the office settings pages
        already send, so the shared autosave hook works unchanged; a bare object
        is accepted too.
        """
        payload = request.data.get("settings", request.data)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
