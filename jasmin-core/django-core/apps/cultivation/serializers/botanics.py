from rest_framework import serializers

from ..models import CultivationBreakFamily, Vegetable, VegetableAggregation


class CultivationBreakFamilySerializer(serializers.ModelSerializer):
    class Meta:
        model = CultivationBreakFamily
        fields = "__all__"


class VegetableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vegetable
        fields = "__all__"


class VegetableAggregationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VegetableAggregation
        fields = "__all__"
