from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..constants import CELLS_PER_BED
from ..models import BedType, Plot, PlotContent


# The commissioning app already exposes a "Plot" component (a different concept —
# a delivery/documentation plot). Disambiguate the cultivation growing plot so the
# generated OpenAPI component + frontend type is "CultivationPlot", not a clash.
@extend_schema_serializer(component_name="CultivationPlot")
class PlotSerializer(serializers.ModelSerializer):
    # Geometry the planner grid needs: how many beds this plot holds (summed
    # over its PlotContent rows) and the resulting cell capacity. The list
    # viewset annotates ``total_beds``; the fallback keeps single-object
    # create/update responses correct without an annotation.
    total_beds = serializers.SerializerMethodField()
    cell_capacity = serializers.SerializerMethodField()

    class Meta:
        model = Plot
        fields = "__all__"

    def _beds(self, obj: Plot) -> int:
        annotated = getattr(obj, "total_beds_annotated", None)
        if annotated is not None:
            return annotated
        return sum(content.amount for content in obj.contents.all())

    def get_total_beds(self, obj: Plot) -> int:
        return self._beds(obj)

    def get_cell_capacity(self, obj: Plot) -> int:
        return self._beds(obj) * CELLS_PER_BED


class BedTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BedType
        fields = "__all__"


class PlotContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotContent
        fields = "__all__"
