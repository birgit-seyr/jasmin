"""Reuse the tenant + factory fixtures defined in apps/commissioning/tests."""

import pytest
from django.core.cache import cache

from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    api_client,
    api_request_factory,
    tenant,
    user,
)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Wipe DRF's throttle counters before + after every accounts
    test.

    The accounts views — login, register, password-reset — all carry
    ``ScopedRateThrottle`` scopes (``login``, ``register``,
    ``password_reset``). DRF stores the rate buckets in Django's
    default cache backend; without a clear, the buckets leak across
    test methods, and any test that's the Nth+1 invocation of a
    throttled endpoint within the test session gets a 429 instead of
    its expected response.

    Before the 2026-06 ``view.cls.throttle_scope = ...`` fix the
    throttles were a silent no-op, so this wasn't necessary — but now
    that they actually fire, every accounts test that POSTs to
    /login/, /register/, or the password-reset endpoints starts from
    a clean budget.
    """
    cache.clear()
    yield
    cache.clear()
