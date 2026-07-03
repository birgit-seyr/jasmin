from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import BillingProfileViewSet, BillingRunViewSet, ChargeScheduleViewSet

router = DefaultRouter()
router.register(r"billing_profiles", BillingProfileViewSet, basename="billing_profile")
router.register(r"charge_schedules", ChargeScheduleViewSet, basename="charge_schedule")
router.register(r"billing_runs", BillingRunViewSet, basename="billing_run")

urlpatterns = [
    path("", include(router.urls)),
]
