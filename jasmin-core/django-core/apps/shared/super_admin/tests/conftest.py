"""Pytest fixtures for super_admin tests.

Re-exports the session-scoped tenant fixtures from the commissioning
app so we don't migrate the schema twice. Same pattern as
``apps/payments/tests/conftest.py``.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.commissioning.tests.conftest import (  # noqa: F401
    _silence_django_request_logging,
    _tenant_schema,
    tenant,
)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Wipe DRF's throttle counters before + after every super_admin test.

    ``super_admin_login_view`` / ``super_admin_step_up_view`` carry the
    strict ``super_admin_login`` ScopedRateThrottle scope (10/hour, keyed
    by IP / super-admin pk). DRF stores the rate buckets in the default
    cache; without a clear they leak across test methods, so the Nth+1
    invocation of a throttled endpoint in the session would get a 429
    instead of its expected response. Mirrors the accounts conftest."""
    cache.clear()
    yield
    cache.clear()
