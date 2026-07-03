"""Shared infrastructure for the super-admin tenant management API.

The actual endpoints have moved to ``apps.shared.super_admin.viewsets``
(see :class:`TenantManagementViewSet`). This module retains only
:class:`SuperAdminJWTAuthentication` — the JWT auth class that resolves
the ``user_id`` claim against the public-schema ``SuperAdmin`` model.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django_tenants.utils import schema_context
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token


class SuperAdminJWTAuthentication(JWTAuthentication):
    """JWT auth that fetches super-admin users from the public schema."""

    def get_user(self, validated_token: Token) -> Any:
        try:
            user_id = validated_token.get("user_id")

            with schema_context("public"):
                from apps.shared.super_admin.models import SuperAdmin

                user = SuperAdmin.objects.get(id=user_id)
        except (ObjectDoesNotExist, ValueError, TypeError) as e:
            # DoesNotExist: missing / None / deleted user_id. ValueError/TypeError:
            # a malformed (but validly-signed) user_id that fails PK coercion.
            # A bare ``except Exception`` here would also swallow programming /
            # infra errors (ImportError, OperationalError, AttributeError) as a
            # 401 — let those surface as 500 instead.
            raise AuthenticationFailed("Invalid token or user not found") from e

        # Mirror the base SimpleJWT ``get_user``, which we fully override:
        # a super-admin deactivated or deleted AFTER login must lose access
        # immediately, not keep full platform reach for the token lifetime.
        if not user.is_active:
            raise AuthenticationFailed("User account is disabled")

        # TEN-1: derive privilege from the fetched row, not the token claim.
        # ``user`` IS a ``SuperAdmin`` (we loaded it from that table), so the
        # answer is unconditionally True — trusting the claim would let any
        # future non-super-admin token-mint path smuggle the flag in.
        user.is_super_admin = True
        user.user_role = validated_token.get("user_role", None)
        return user
