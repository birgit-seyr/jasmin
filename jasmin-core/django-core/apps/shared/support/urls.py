"""Tenant-facing support routes — mounted in config/tenant_urls.py at
``/api/support/`` (so they land in the generated schema.yml / Orval client)."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import SupportTicketViewSet

app_name = "support"

router = DefaultRouter()
router.register("tickets", SupportTicketViewSet, basename="support-ticket")

urlpatterns = [path("", include(router.urls))]
