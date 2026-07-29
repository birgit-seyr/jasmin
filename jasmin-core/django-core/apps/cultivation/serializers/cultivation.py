from rest_framework import serializers

from ..models import CultivationBatch


class CultivationBatchSerializer(serializers.ModelSerializer):
    # Denormalised for display: the planner palette and batch lists label a
    # batch by its crop, and would otherwise need a lookup per row.
    vegetable_name = serializers.CharField(source="vegetable.name", read_only=True)

    class Meta:
        model = CultivationBatch
        fields = "__all__"
