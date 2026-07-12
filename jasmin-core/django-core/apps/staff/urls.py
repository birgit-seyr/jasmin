from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import (
    AbsenceCategoryViewSet,
    EmployeeViewSet,
    WeeklyPlanCategoryViewSet,
)

router = DefaultRouter()
router.register(r"employees", EmployeeViewSet, basename="employees")
router.register(
    r"weekly_plan_categories",
    WeeklyPlanCategoryViewSet,
    basename="weekly_plan_categories",
)
router.register(
    r"absence_categories",
    AbsenceCategoryViewSet,
    basename="absence_categories",
)


urlpatterns = [
    path("", include(router.urls)),
]
