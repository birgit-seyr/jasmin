from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import viewsets

from apps.authz.permissions import IsAdmin, IsStaff, RolePermissionsMixin

from ..models import LabelTemplate
from ..serializers import LabelTemplateSerializer


class LabelTemplateViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """The farm's label layout: read by whoever prints the labels, kept by an
    admin in the configuration. The first active template is the farm's."""

    read_permission = IsStaff
    write_permission = IsAdmin
    serializer_class = LabelTemplateSerializer
    # A template is replaced by editing it; there is no second one to delete to.
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[LabelTemplate]:
        return LabelTemplate.objects.filter(is_active=True).order_by("name", "id")
