from rest_framework import serializers

from apps.commissioning.serializers.serializers_mixin import DeletableMixin

from ..errors import StaffError
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

    def validate_max_lines(self, value):
        # A category needs at least one grid row to be usable — ``max_lines``
        # drives ``range(category.max_lines)`` when the week grid is built, so
        # 0 or a negative count renders a category no one can fill. A stored
        # row that already carries such a count stays editable while the count
        # itself is left untouched: the list page echoes every column back on
        # save, so refusing the unchanged value would freeze the whole row.
        if value < 1 and (self.instance is None or value != self.instance.max_lines):
            message = "max_lines must be at least 1."
            # ``details`` keeps the per-field map DRF's own field errors produce,
            # so the grid keeps rendering the message against the right column.
            raise StaffError(
                message, field="max_lines", details={"max_lines": [message]}
            )
        return value


class AbsenceCategorySerializer(DeletableMixin, serializers.ModelSerializer):
    class Meta:
        model = AbsenceCategory
        fields = "__all__"
