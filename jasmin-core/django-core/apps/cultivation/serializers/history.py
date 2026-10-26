from rest_framework import serializers

from ..models import HistoricalPlanting


class HistoricalPlantingSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricalPlanting
        fields = "__all__"
