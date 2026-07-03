"""Tenant-aware DRF throttling."""

from __future__ import annotations

from django.db import connection
from rest_framework.throttling import ScopedRateThrottle


class TenantScopedRateThrottle(ScopedRateThrottle):
    """``ScopedRateThrottle`` whose cache key is namespaced by the current
    tenant schema.

    DRF keys anonymous scopes on the client IP with no host/schema component,
    and the backing store is a single shared Redis cache. Without a schema
    component, users of tenant A and tenant B behind ONE egress IP (corporate
    NAT, university, CGNAT mobile carrier) draw down the SAME ``login`` /
    ``register`` / ``current_tenant`` bucket — so one tenant's Monday-morning
    login load (or an attack against it) 429s another tenant's users who did
    nothing. Prefixing ``connection.schema_name`` gives every tenant its own
    bucket per scope.

    Authenticated scopes already key on ``user.pk`` (a globally-unique nanoid)
    so they never collided; the prefix is harmless there. Super-admin scopes run
    on the public schema, so they keep a single global bucket (the schema name
    is the constant public schema) — which is the desired platform-wide limit.
    """

    def get_cache_key(self, request, view):
        key = super().get_cache_key(request, view)
        if key is None:
            return None
        schema = getattr(connection, "schema_name", "") or ""
        return f"{schema}:{key}"
