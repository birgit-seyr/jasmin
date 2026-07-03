from __future__ import annotations

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import NotFoundError
from core.serializers import ErrorResponseSerializer

from .errors import NoTenantContext
from .models import Tenant
from .serializers import CurrentTenantSerializer


class CurrentTenantView(APIView):
    """Get current tenant information."""

    permission_classes = []  # Allow unauthenticated access for tenant detection
    # Anti-flood: this AllowAny bootstrap endpoint is otherwise unthrottled.
    # The global ScopedRateThrottle is a no-op until a scope is set; naming one
    # opts this view in (rate in settings DEFAULT_THROTTLE_RATES, keyed by IP).
    throttle_scope = "current_tenant"

    @extend_schema(
        tags=["tenants"],
        summary="Get current tenant",
        responses={
            200: CurrentTenantSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        schema_name = connection.schema_name

        if schema_name == "public":
            raise NoTenantContext("No tenant context")

        try:
            tenant = Tenant.objects.get(schema_name=schema_name)
        except Tenant.DoesNotExist:
            raise NotFoundError("Tenant not found") from None

        return Response(CurrentTenantSerializer(tenant).data)
