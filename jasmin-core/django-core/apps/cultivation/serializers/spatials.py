from django.db.models import Max
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from ..constants import CELLS_PER_BED
from ..models import BedType, Plot, PlotContent
from ..optimizer.loading import plot_segments


class BedSegmentSerializer(serializers.Serializer):
    """One block of same-type beds as a cell range on the plot's axis.

    Read-only projection of the plot's ``PlotContent`` rows — the planner grid
    needs it to label bed types and to grey out cells a batch may not start in.
    """

    bed_type = serializers.CharField(source="bed_type_id")
    bed_type_name = serializers.CharField()
    start_cell = serializers.IntegerField()
    cell_count = serializers.IntegerField()


# The commissioning app already exposes a "Plot" component (a different concept —
# a delivery/documentation plot). Disambiguate the cultivation growing plot so the
# generated OpenAPI component + frontend type is "CultivationPlot", not a clash.
@extend_schema_serializer(component_name="CultivationPlot")
class PlotSerializer(serializers.ModelSerializer):
    # Geometry the planner grid needs: how many beds this plot holds (summed
    # over its PlotContent rows), the resulting cell capacity, and which stretch
    # of cells is which bed type.
    total_beds = serializers.SerializerMethodField()
    cell_capacity = serializers.SerializerMethodField()
    bed_segments = serializers.SerializerMethodField()

    class Meta:
        model = Plot
        fields = "__all__"

    def _beds(self, obj: Plot) -> int:
        return sum(content.amount for content in obj.contents.all())

    def get_total_beds(self, obj: Plot) -> int:
        return self._beds(obj)

    def get_cell_capacity(self, obj: Plot) -> int:
        return self._beds(obj) * CELLS_PER_BED

    @extend_schema_field(BedSegmentSerializer(many=True))
    def get_bed_segments(self, obj: Plot) -> list[dict]:
        # Same loader the solver uses, so the grid can never draw a bed-type
        # layout the optimizer disagrees with.
        return BedSegmentSerializer(plot_segments(obj, CELLS_PER_BED), many=True).data


class BedTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BedType
        fields = "__all__"


class PlotContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotContent
        fields = "__all__"

    def validate(self, attrs: dict) -> dict:
        """Default a new block's ``position`` to the END of the plot.

        The model default is 0, which sorts FIRST — so a client that omits the
        field would push the new block in front of the existing ones, shifting
        every cell after it and silently re-aiming this plot's stored placements
        and rotation history at different beds. Appending leaves every existing
        cell index meaning what it meant. An explicit 0 is treated as "unset" for
        the same reason.
        """
        if self.instance is None and not attrs.get("position"):
            plot = attrs.get("plot")
            if plot is not None:
                last = PlotContent.objects.filter(plot_id=plot.pk).aggregate(
                    last=Max("position")
                )["last"]
                attrs["position"] = (last or 0) + 1
        return attrs
