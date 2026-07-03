from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import BackgroundJobViewSet, EmailLogViewSet, EmailTemplateViewSet

router = DefaultRouter()
router.register(r"email-templates", EmailTemplateViewSet, basename="email-template")
router.register(r"jobs", BackgroundJobViewSet, basename="background-job")
router.register(r"email-logs", EmailLogViewSet, basename="email-log")

urlpatterns = [
    path("", include(router.urls)),
]
