from rest_framework import serializers

# --------------------------------------------------------------------------- #
# Request payloads
# --------------------------------------------------------------------------- #


class WeeklyPlanAssignmentSerializer(serializers.Serializer):
    """One filled cell in a replace-all payload."""

    category_id = serializers.CharField()
    row_index = serializers.IntegerField(min_value=0)
    day = serializers.IntegerField(min_value=0, max_value=6)
    employee_id = serializers.CharField()


class WeeklyPlanReplaceSerializer(serializers.Serializer):
    """Whole-week replace-all: the full grid state for one ``(year, week)``."""

    year = serializers.IntegerField(min_value=2000, max_value=2100)
    week = serializers.IntegerField(min_value=1, max_value=53)
    assignments = WeeklyPlanAssignmentSerializer(many=True)


class WeeklyPlanCopySerializer(serializers.Serializer):
    """Copy the plan of ``from_week`` into an empty ``to_week`` (same year)."""

    year = serializers.IntegerField(min_value=2000, max_value=2100)
    from_week = serializers.IntegerField(min_value=1, max_value=53)
    to_week = serializers.IntegerField(min_value=1, max_value=53)


# --------------------------------------------------------------------------- #
# Dense-grid response
# --------------------------------------------------------------------------- #


class WeeklyPlanEmployeeSerializer(serializers.Serializer):
    """Palette entry — the client resolves cell employee ids against this list."""

    id = serializers.CharField()
    short_name_for_weekly_plan = serializers.CharField()
    first_name = serializers.CharField(allow_null=True)
    last_name = serializers.CharField(allow_null=True)


class WeeklyPlanRowSerializer(serializers.Serializer):
    row_index = serializers.IntegerField()
    # ``{"0": employee_id|null, ... "6": employee_id|null}`` — one entry per weekday.
    days = serializers.DictField(child=serializers.CharField(allow_null=True))


class WeeklyPlanCategoryGridSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    max_lines = serializers.IntegerField()
    rows = WeeklyPlanRowSerializer(many=True)


class WeeklyPlanGridSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    week = serializers.IntegerField()
    categories = WeeklyPlanCategoryGridSerializer(many=True)
    employees = WeeklyPlanEmployeeSerializer(many=True)
