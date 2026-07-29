from django.db.models import Sum
from rest_framework import viewsets

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import BedType, Plot, PlotContent
from ..serializers import BedTypeSerializer, PlotContentSerializer, PlotSerializer


class PlotViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = PlotSerializer
    queryset = Plot.objects.annotate(total_beds_annotated=Sum("contents__amount"))


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
