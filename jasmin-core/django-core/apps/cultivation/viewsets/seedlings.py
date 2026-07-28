from rest_framework import viewsets

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..models import SeedlingsVendor, SeedsVendor
from ..serializers import SeedlingsVendorSerializer, SeedsVendorSerializer


class SeedlingsVendorViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = SeedlingsVendorSerializer
    queryset = SeedlingsVendor.objects.all()


class SeedsVendorViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = SeedsVendorSerializer
    queryset = SeedsVendor.objects.all()
