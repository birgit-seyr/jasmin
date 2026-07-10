"""Reuse the tenant + user fixtures defined in apps/commissioning/tests."""

from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    tenant,
    user,
)
