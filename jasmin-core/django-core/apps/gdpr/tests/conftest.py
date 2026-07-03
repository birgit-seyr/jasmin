"""Pytest fixtures for the gdpr app — re-exports the tenant + factory
stack from commissioning, same pattern as ``apps/payments/tests/conftest.py``.
"""

from __future__ import annotations

from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    anon_client,
    api_client,
    api_request_factory,
    member_user,
    step_up_client,
    tenant,
    user,
)
