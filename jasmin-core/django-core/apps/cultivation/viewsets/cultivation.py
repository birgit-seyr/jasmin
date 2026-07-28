from rest_framework import viewsets

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import CultivationBatch
from ..serializers import CultivationBatchSerializer


class CultivationBatchViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = CultivationBatchSerializer
    queryset = CultivationBatch.objects.select_related(
        "vegetable", "vegetable_set", "used_bed_type"
    )
