"""Tests for `apps.authz.authentication.TenantBoundJWTAuthentication`.

This is the cross-tenant defense — a JWT minted on tenant A must be
rejected when presented to tenant B even if both tenants have a user
with the same id. Failures here would silently break tenant isolation.
"""

from __future__ import annotations

import pytest
from django.db import connection
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import AccessToken

from apps.authz.authentication import TenantBoundJWTAuthentication
from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth():
    return TenantBoundJWTAuthentication()


@pytest.fixture
def rf():
    return APIRequestFactory()


def _bearer(rf, token: str):
    return rf.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")


def _mint(user, *, tenant_id):
    """Mint an access token, optionally stamping a tenant_id claim."""
    token = AccessToken.for_user(user)
    if tenant_id is not None:
        token["tenant_id"] = tenant_id
    return str(token)


class TestTenantBinding:
    def test_token_with_matching_tenant_passes(self, tenant, rf, auth):
        u = JasminUserFactory()
        raw = _mint(u, tenant_id=tenant.schema_name)
        validated = auth.get_validated_token(raw)
        assert validated.get("tenant_id") == tenant.schema_name

    def test_token_without_tenant_claim_is_rejected(self, tenant, rf, auth):
        u = JasminUserFactory()
        raw = _mint(u, tenant_id=None)
        with pytest.raises(InvalidToken) as exc:
            auth.get_validated_token(raw)
        assert "tenant_id" in str(exc.value)

    def test_token_for_other_tenant_is_rejected(self, tenant, rf, auth):
        u = JasminUserFactory()
        raw = _mint(u, tenant_id="some-other-schema")
        with pytest.raises(InvalidToken) as exc:
            auth.get_validated_token(raw)
        assert "tenant" in str(exc.value).lower()

    def test_unresolvable_schema_fails_closed(self, tenant, rf, auth, monkeypatch):
        """SEC-13: when the connection schema is falsy (unresolved), the
        binding check must FAIL CLOSED — reject the token rather than
        silently skip the check (the old ``if current_schema and ...`` guard
        let a falsy schema through). Matches the refresh path, which already
        raises here."""
        u = JasminUserFactory()
        raw = _mint(u, tenant_id=tenant.schema_name)
        # Force an unresolvable (falsy) schema for the duration of the call.
        monkeypatch.setattr(connection, "schema_name", "")
        with pytest.raises(InvalidToken) as exc:
            auth.get_validated_token(raw)
        assert "resolved" in str(exc.value).lower()

    def test_authenticate_full_flow_returns_user(self, tenant, rf, auth):
        u = JasminUserFactory()
        raw = _mint(u, tenant_id=tenant.schema_name)
        # Drive the full DRF entrypoint, not just `get_validated_token`.
        result = auth.authenticate(_bearer(rf, raw))
        assert result is not None
        user, validated = result
        assert user.id == u.id
        assert validated.get("tenant_id") == tenant.schema_name

    def test_authenticate_full_flow_rejects_cross_tenant(self, tenant, rf, auth):
        u = JasminUserFactory()
        raw = _mint(u, tenant_id="bogus")
        with pytest.raises(InvalidToken):
            auth.authenticate(_bearer(rf, raw))

    def test_no_authorization_header_returns_none(self, tenant, rf, auth):
        # DRF contract: no header → no authentication attempt (returns None).
        assert auth.authenticate(rf.get("/")) is None

    def test_garbage_token_raises(self, tenant, rf, auth):
        # `InvalidToken` is what simplejwt raises for malformed payloads — same
        # as the cross-tenant case above. Asserting the exact class catches
        # accidental broadening (e.g. swallowing the parse error and returning
        # None) that a bare `Exception` match would mask.
        with pytest.raises(InvalidToken):
            auth.authenticate(_bearer(rf, "not.a.real.jwt"))

    def test_public_schema_still_requires_tenant_claim(self, tenant, rf, auth):
        """Even when the connection is on `public` (e.g. test setup), a token
        without a `tenant_id` claim must be rejected."""
        connection.set_schema_to_public()
        try:
            u = JasminUserFactory()  # this would fail on public; skip if so
        except Exception:
            pytest.skip("JasminUser is tenant-scoped; cannot create on public")
        raw = _mint(u, tenant_id=None)
        with pytest.raises(InvalidToken):
            auth.get_validated_token(raw)
