from rest_framework import viewsets

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import HistoricalPlanting
from ..serializers import HistoricalPlantingSerializer


class HistoricalPlantingViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = HistoricalPlantingSerializer
    queryset = HistoricalPlanting.objects.select_related(
        "plot", "cultivation_break_family", "vegetable"
    )
