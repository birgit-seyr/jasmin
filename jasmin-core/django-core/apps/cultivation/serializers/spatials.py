from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..models import BedType, Plot, PlotContent


# The commissioning app already exposes a "Plot" component (a different concept —
# a delivery/documentation plot). Disambiguate the cultivation growing plot so the
# generated OpenAPI component + frontend type is "CultivationPlot", not a clash.
@extend_schema_serializer(component_name="CultivationPlot")
class PlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plot
        fields = "__all__"


class BedTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BedType
        fields = "__all__"


class PlotContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotContent
        fields = "__all__"
