from rest_framework import serializers

from ..models import CultivationBatch


class CultivationBatchSerializer(serializers.ModelSerializer):
    # Denormalised for display: the planner palette and batch lists label a
    # batch by its crop, and would otherwise need a lookup per row.
    vegetable_name = serializers.CharField(source="vegetable.name", read_only=True)
    # The bed type the batch was sized against — the planner shades the grid by
    # it, so it needs the name without a second round trip. allow_null because
    # both the FK and BedType.name are nullable; without it DRF would drop the
    # key entirely for batches with no bed type rather than send null.
    used_bed_type_name = serializers.CharField(
        source="used_bed_type.name", read_only=True, allow_null=True
    )

    class Meta:
        model = CultivationBatch
        fields = "__all__"
