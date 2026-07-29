from rest_framework import serializers

from ..models import CultivationPlanSolution, CultivationPlanSolutionDetail


class CultivationPlanSolutionDetailSerializer(serializers.ModelSerializer):
    """One placed batch. Carries the denormalised display fields the planner
    grid needs (crop name, week window, rotation family) so rendering a plan
    costs one request instead of a lookup per placement."""

    end_cell = serializers.IntegerField(read_only=True)
    vegetable_name = serializers.CharField(
        source="batch.vegetable.name", read_only=True
    )
    planting_week = serializers.IntegerField(
        source="batch.planting_week", read_only=True
    )
    end_week = serializers.IntegerField(source="batch.end_week", read_only=True)
    cultivation_break_family = serializers.CharField(
        source="batch.vegetable.cultivation_break_family_id",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = CultivationPlanSolutionDetail
        fields = [
            "id",
            "solution",
            "batch",
            "plot",
            "start_cell",
            "cell_count",
            "end_cell",
            "vegetable_name",
            "planting_week",
            "end_week",
            "cultivation_break_family",
        ]
        read_only_fields = ["id", "end_cell"]


class CultivationPlanSolutionSerializer(serializers.ModelSerializer):
    """A candidate plan header (no placements — fetch those via ``details``)."""

    placement_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = CultivationPlanSolution
        fields = [
            "id",
            "year",
            "version",
            "chosen",
            "cells_per_bed",
            "placement_count",
        ]
        read_only_fields = fields


class CultivationPlanSolutionWithDetailsSerializer(CultivationPlanSolutionSerializer):
    """The full plan — header plus every placement, for the planner grid."""

    details = CultivationPlanSolutionDetailSerializer(many=True, read_only=True)

    class Meta(CultivationPlanSolutionSerializer.Meta):
        fields = CultivationPlanSolutionSerializer.Meta.fields + ["details"]
        read_only_fields = fields
