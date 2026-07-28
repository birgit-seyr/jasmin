from rest_framework import serializers

from ..models import SeedlingsVendor, SeedsVendor


class SeedlingsVendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeedlingsVendor
        fields = "__all__"


class SeedsVendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeedsVendor
        fields = "__all__"
