from rest_framework import viewsets

from apps.authz.permissions import CanEditCultivation, IsStaff, RolePermissionsMixin

from ..models import HistoricalPlanting
from ..serializers import HistoricalPlantingSerializer


class HistoricalPlantingViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = CanEditCultivation
    serializer_class = HistoricalPlantingSerializer
    queryset = HistoricalPlanting.objects.select_related(
        "plot", "cultivation_break_family", "vegetable"
    )
