"""TEN-4: ``TenantScopedRateThrottle`` namespaces each scope's cache bucket by
schema so a shared egress IP can't burn one tenant's login/register limit and
429 another tenant's users through the shared Redis cache.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import connection
from rest_framework.throttling import ScopedRateThrottle

from core.throttling import TenantScopedRateThrottle


@pytest.mark.django_db
class TestTenantScopedRateThrottle:
    def test_cache_key_is_prefixed_with_current_schema(self, tenant):
        throttle = TenantScopedRateThrottle()
        with patch.object(
            ScopedRateThrottle, "get_cache_key", return_value="throttle_login_1.2.3.4"
        ):
            key = throttle.get_cache_key(request=None, view=None)

        # Same IP + scope resolves to a DIFFERENT bucket per tenant schema.
        assert key == f"{connection.schema_name}:throttle_login_1.2.3.4"
        assert connection.schema_name  # not the empty-prefix degenerate case

    def test_none_key_passes_through(self, tenant):
        """When the base returns None (unscoped view), stay None — don't
        fabricate a ``schema:None`` bucket."""
        throttle = TenantScopedRateThrottle()
        with patch.object(ScopedRateThrottle, "get_cache_key", return_value=None):
            assert throttle.get_cache_key(request=None, view=None) is None
