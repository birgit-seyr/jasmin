"""drf-spectacular extensions for this app.

Registers :class:`TenantBoundJWTAuthentication` with spectacular so it
shows up as a Bearer-JWT security scheme on every endpoint instead of
emitting a "could not resolve authenticator" warning during schema
generation.

The wire-style security scheme is identical to SimpleJWT's — Bearer
token in the ``Authorization`` header — because the tenant-binding is
a server-side validation on the existing claim, not a wire-format
change. The tenant-binding behaviour is documented inline.

Loaded from ``AuthzConfig.ready()``; importing this module is enough
to register the extension (drf-spectacular collects subclasses of
``OpenApiAuthenticationExtension`` via a class-level registry).
"""

from __future__ import annotations

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TenantBoundJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.authz.authentication.TenantBoundJWTAuthentication"
    name = "tenantBoundJwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Tenant-bound JWT. The token MUST carry a ``tenant_id`` "
                "claim matching the request's schema; see "
                "``apps/authz/authentication.py``."
            ),
        }
