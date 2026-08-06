from drf_spectacular.utils import extend_schema_field
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


class SolutionMetricsSerializer(serializers.Serializer):
    """Quality numbers for comparing candidate plans — see services/metrics.py."""

    planted_cell_weeks = serializers.IntegerField()
    bed_weeks_opened = serializers.IntegerField()
    wasted_cell_weeks = serializers.IntegerField()
    efficiency_percent = serializers.FloatField()
    plots_used = serializers.IntegerField()
    beds_touched = serializers.IntegerField()
    peak_week = serializers.IntegerField()
    peak_cells_used = serializers.IntegerField()
    successions = serializers.IntegerField()


class CultivationPlanSolutionSerializer(serializers.ModelSerializer):
    """A candidate plan header (no placements — fetch those via ``details``)."""

    placement_count = serializers.IntegerField(read_only=True)
    metrics = serializers.SerializerMethodField()

    class Meta:
        model = CultivationPlanSolution
        fields = [
            "id",
            "year",
            "version",
            "chosen",
            "cells_per_bed",
            "placement_count",
            "metrics",
        ]
        read_only_fields = fields

    @extend_schema_field(SolutionMetricsSerializer())
    def get_metrics(self, obj: CultivationPlanSolution) -> dict:
        from ..services.metrics import solution_metrics

        return solution_metrics(obj)


class CarryoverBlockSerializer(serializers.Serializer):
    """Ground still held at the start of the year by last year's overwintering
    crop. Not part of this plan — the solver treats it as occupied — but the
    grid must draw it, or those cells look free."""

    plot = serializers.CharField()
    start_cell = serializers.IntegerField()
    cell_count = serializers.IntegerField()
    until_week = serializers.IntegerField()
    label = serializers.CharField()


class CultivationPlanSolutionWithDetailsSerializer(CultivationPlanSolutionSerializer):
    """The full plan — header, every placement, and the carryover it had to work
    around."""

    details = CultivationPlanSolutionDetailSerializer(many=True, read_only=True)
    carryover = serializers.SerializerMethodField()

    class Meta(CultivationPlanSolutionSerializer.Meta):
        fields = CultivationPlanSolutionSerializer.Meta.fields + [
            "details",
            "carryover",
        ]
        read_only_fields = fields

    @extend_schema_field(CarryoverBlockSerializer(many=True))
    def get_carryover(self, obj: CultivationPlanSolution) -> list[dict]:
        # Deliberately the SAME loader the solver used, so the grid can never
        # disagree with the constraints about which cells were unavailable.
        from ..optimizer.loading import load_carryover

        return [
            {
                "plot": c.plot_id,
                "start_cell": c.start_cell,
                "cell_count": c.cell_count,
                "until_week": c.until_week,
                "label": c.label,
            }
            for c in load_carryover(obj.year)
        ]
