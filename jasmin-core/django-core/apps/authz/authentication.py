"""Tenant-bound JWT authentication.

A token issued for tenant `acme` must NOT authenticate against tenant `globex`.
SimpleJWT does not enforce this on its own — a stolen token from one tenant's
schema would otherwise resolve a user with the same `id` in another schema.

The login flow (host app) is responsible for putting `tenant_id` (= the schema
name) on the token. Here we verify, on every request, that the token's
`tenant_id` matches `connection.schema_name`.
"""

from __future__ import annotations

from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class TenantBoundJWTAuthentication(JWTAuthentication):
    def get_validated_token(self, raw_token):  # type: ignore[override]
        token = super().get_validated_token(raw_token)
        token_tenant = token.get("tenant_id")
        current_schema = getattr(connection, "schema_name", None)

        if token_tenant is None:
            raise InvalidToken("Token is missing the tenant_id claim.")

        # Fail CLOSED when the schema can't be resolved: a falsy
        # ``current_schema`` must reject the token, not silently skip the
        # binding check. (django-tenants normally sets "public" here when no
        # tenant resolves, but don't depend on that — match the refresh
        # path, which already raises in this case.)
        if not current_schema:
            raise InvalidToken("Tenant could not be resolved.")

        if token_tenant != current_schema:
            raise InvalidToken("Token does not belong to this tenant.")

        return token
