from rest_framework import viewsets

from apps.authz.permissions import CanEditCultivation, IsStaff, RolePermissionsMixin

from ..models import CultivationBreakFamily, Vegetable, VegetableAggregation
from ..serializers import (
    CultivationBreakFamilySerializer,
    VegetableAggregationSerializer,
    VegetableSerializer,
)


class CultivationBreakFamilyViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = CanEditCultivation
    serializer_class = CultivationBreakFamilySerializer
    queryset = CultivationBreakFamily.objects.all()


class VegetableViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = CanEditCultivation
    serializer_class = VegetableSerializer
    queryset = Vegetable.objects.select_related("cultivation_break_family")


class VegetableAggregationViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = CanEditCultivation
    serializer_class = VegetableAggregationSerializer
    queryset = VegetableAggregation.objects.all()
