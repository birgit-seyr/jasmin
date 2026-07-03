"""Shared serializers — kept tiny on purpose.

Anything app-specific belongs in the app. Only put things here that every
app may produce or every API client may receive.
"""

from __future__ import annotations

from rest_framework import serializers


class ErrorResponseSerializer(serializers.Serializer):
    """Canonical error payload returned by ``core.exception_handler``.

    Use in ``@extend_schema(responses={400: ErrorResponseSerializer, ...})``
    so the generated OpenAPI types match what the client actually receives.
    """

    code = serializers.CharField()
    message = serializers.CharField()
    field = serializers.CharField(required=False, allow_null=True)
    details = serializers.DictField(required=False)
    request_id = serializers.CharField(required=False)
