from rest_framework import serializers

from apps.commissioning.serializers.serializers_mixin import DeletableMixin

from ..models import AbsenceCategory, Employee, WeeklyPlanCategory


class EmployeeSerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = "__all__"

    def validate_employee_number(self, value):
        # ``employee_number`` is unique but optional. A blank entry must land as
        # NULL (which Postgres treats as distinct) — otherwise a second employee
        # left blank would collide on an empty string.
        return value or None


class WeeklyPlanCategorySerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = WeeklyPlanCategory
        fields = "__all__"


class AbsenceCategorySerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = AbsenceCategory
        fields = "__all__"
