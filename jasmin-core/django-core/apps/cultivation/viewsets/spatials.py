from rest_framework import viewsets

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import BedType, Plot, PlotContent
from ..serializers import BedTypeSerializer, PlotContentSerializer, PlotSerializer


class PlotViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = PlotSerializer
    # One prefetch feeds both the bed count and the bed-type segments — an
    # aggregate could give only the count, and pairing it with this prefetch
    # would query the same rows twice.
    queryset = Plot.objects.prefetch_related("contents__bed_type")


class BedTypeViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = BedTypeSerializer
    queryset = BedType.objects.all()


class PlotContentViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = PlotContentSerializer
    queryset = PlotContent.objects.select_related("plot", "bed_type")
