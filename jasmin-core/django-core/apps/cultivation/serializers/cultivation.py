from rest_framework import serializers

from ..models import CultivationBatch


class CultivationBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = CultivationBatch
        fields = "__all__"
