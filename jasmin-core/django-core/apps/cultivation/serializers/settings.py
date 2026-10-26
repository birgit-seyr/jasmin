from rest_framework import serializers

from ..models import SolverSettings


class SolverSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolverSettings
        fields = "__all__"
        # System-owned: the singleton flag is never client-settable (flipping it
        # would orphan the active row or trip the partial-unique constraint).
        read_only_fields = ["id", "is_active", "updated_at"]
