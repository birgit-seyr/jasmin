"""Step-up authentication — permission + endpoint + integration tests.

Three layers tested:

  - ``RequiresStepUp`` permission class behaviour with a synthetic
    request (no claim → raise, expired → raise, fresh → pass).
  - ``POST /api/auth/step-up/`` happy path + bad-password path,
    asserting the rotated access token carries the new claim.
  - End-to-end: hitting a gated endpoint without step-up returns
    the canonical 403 ``auth.step_up_required`` body; the same
    request with a fresh step-up token succeeds.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.errors import StepUpRequired
from apps.accounts.permissions import RequiresStepUp
from apps.commissioning.tests.factories import JasminUserFactory

# Module-level mark: every HTTP-level test in this file hits middleware
# that queries the DB (tenant resolution, throttle cache). The pure-
# permission unit tests above don't need it, but the mark is idempotent.
pytestmark = pytest.mark.django_db

# --------------------------------------------------------------------- #
# Permission class                                                      #
# --------------------------------------------------------------------- #


def _make_request(*, payload=None, authenticated=True):
    """Synthetic request object with the shape DRF passes to permissions."""
    return SimpleNamespace(
        user=SimpleNamespace(
            email="caller@example.com",
            is_authenticated=authenticated,
        ),
        auth=SimpleNamespace(payload=payload) if payload is not None else None,
        path="/test/",
    )


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_permission_anonymous_returns_false_not_raise():
    """Anonymous callers see the regular 401 path, not a step-up modal."""
    perm = RequiresStepUp()
    assert perm.has_permission(_make_request(authenticated=False), view=None) is False


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_permission_missing_claim_raises_step_up_required():
    perm = RequiresStepUp()
    request = _make_request(payload={})
    with pytest.raises(StepUpRequired) as exc:
        perm.has_permission(request, view=None)
    # ``ttl_seconds`` MUST be in details — the frontend reads it to
    # render the "valid for N min" hint without a hard-coded literal.
    assert exc.value.details == {"ttl_seconds": 300}


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_permission_expired_claim_raises_step_up_required():
    perm = RequiresStepUp()
    # 10 minutes ago, TTL is 5 minutes → expired.
    payload = {"step_up_verified_at": int(time.time()) - 600}
    with pytest.raises(StepUpRequired):
        perm.has_permission(_make_request(payload=payload), view=None)


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_permission_fresh_claim_passes():
    perm = RequiresStepUp()
    payload = {"step_up_verified_at": int(time.time()) - 30}
    assert perm.has_permission(_make_request(payload=payload), view=None) is True


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_permission_boundary_exact_ttl_still_passes():
    """At exactly ``ttl`` seconds old the claim is still valid; one second
    past, it isn't. Keeps the < vs <= boundary pinned to the code."""
    perm = RequiresStepUp()
    now = int(time.time())
    with patch("apps.accounts.permissions.time.time", return_value=now):
        payload_ok = {"step_up_verified_at": now - 300}
        assert perm.has_permission(_make_request(payload=payload_ok), view=None)

        payload_bad = {"step_up_verified_at": now - 301}
        with pytest.raises(StepUpRequired):
            perm.has_permission(_make_request(payload=payload_bad), view=None)


# --------------------------------------------------------------------- #
# /api/auth/step-up/ endpoint                                           #
# --------------------------------------------------------------------- #


@pytest.fixture
def step_up_url():
    from django.urls import reverse

    return reverse("step_up")


def test_step_up_requires_authentication(anon_client, tenant, step_up_url):
    """Anonymous callers can't even reach the password check.

    Pulls in the ``tenant`` fixture so the request resolves to the
    pytest tenant schema — accounts URLs live in TENANT_URLS, so
    without an active tenant the URL itself isn't routed (the
    fallback PUBLIC_URLS lookup returns 404, masking the real
    "no auth" case we're trying to assert).
    """
    response = anon_client.post(step_up_url, {"password": "anything"}, format="json")
    assert response.status_code == 401


def test_step_up_wrong_password_returns_400(api_client, user, step_up_url):
    response = api_client.post(
        step_up_url, {"password": "definitely-not-the-password"}, format="json"
    )
    assert response.status_code == 400
    assert response.data["code"] == "auth.invalid_credentials"


def test_step_up_missing_password_returns_400(api_client, user, step_up_url):
    # Serializer-level rejection (password required) — distinct from the
    # wrong-password auth failure above. Authenticated, so we reach is_valid.
    response = api_client.post(step_up_url, {}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert "password" in response.data["details"]


def test_step_up_wrong_password_feeds_axes_signal(api_client, user, step_up_url):
    """Step-up verifies the password via ``check_password`` directly, NOT
    ``authenticate()``, so django-axes never sees the failure on its own.
    The view must fire ``user_login_failed`` itself — otherwise a holder of
    a valid low-privilege token can grind the password behind their session
    and never trip the (username, ip) lockout. The signal carries the
    caller's email as ``username`` so axes keys it like a login failure."""
    from django.contrib.auth.signals import user_login_failed

    captured: list[dict] = []

    def _receiver(sender, credentials=None, request=None, **kwargs):
        captured.append(credentials or {})

    user_login_failed.connect(_receiver)
    try:
        response = api_client.post(
            step_up_url, {"password": "definitely-not-the-password"}, format="json"
        )
    finally:
        user_login_failed.disconnect(_receiver)

    assert response.status_code == 400
    assert any(c.get("username") == user.email for c in captured), (
        "step-up failure did not emit user_login_failed — django-axes "
        "lockout is bypassed"
    )


def test_step_up_correct_password_does_not_feed_axes_signal(
    api_client, user, step_up_url
):
    """The mirror of the above: a SUCCESSFUL step-up must not record a
    failed-login signal (that would lock out legitimate users)."""
    from django.contrib.auth.signals import user_login_failed

    user.set_password("step-up-test-pw-Zx9!")
    user.save(update_fields=["password"])

    captured: list[dict] = []

    def _receiver(sender, credentials=None, request=None, **kwargs):
        captured.append(credentials or {})

    user_login_failed.connect(_receiver)
    try:
        response = api_client.post(
            step_up_url, {"password": "step-up-test-pw-Zx9!"}, format="json"
        )
    finally:
        user_login_failed.disconnect(_receiver)

    assert response.status_code == 200
    assert not any(c.get("username") == user.email for c in captured)


def test_step_up_uses_dedicated_throttle_scope():
    """Step-up no longer shares the generous ``login`` bucket (20/min) — it
    has its own strict per-user scope so a wrong-password grind is rate-
    capped independently of the login flow."""
    from django.conf import settings

    from apps.accounts.views.auth_views import step_up_view

    assert step_up_view.cls.throttle_scope == "step_up"
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].get("step_up")


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_step_up_correct_password_returns_rotated_token(api_client, user, step_up_url):
    """Happy path — password matches, response carries an access token
    whose payload includes a fresh ``step_up_verified_at``."""
    # Set a known password we can re-confirm.
    user.set_password("step-up-test-pw-Zx9!")
    user.save(update_fields=["password"])

    response = api_client.post(
        step_up_url, {"password": "step-up-test-pw-Zx9!"}, format="json"
    )
    assert response.status_code == 200
    assert response.data["ttl_seconds"] == 300

    decoded = AccessToken(response.data["access"])
    assert "step_up_verified_at" in decoded.payload
    age = int(time.time()) - int(decoded.payload["step_up_verified_at"])
    # Allow up to 5 seconds for slow CI; the claim is set right at the
    # tail of the request so the lag is normally < 1s.
    assert 0 <= age <= 5


# --------------------------------------------------------------------- #
# End-to-end: gated endpoint                                            #
# --------------------------------------------------------------------- #


def _set_step_up_on_credentials(api_client, user, password):
    """Hit /api/auth/step-up/, then swap the rotated token onto the client.

    We pass the AccessToken instance to ``force_authenticate(token=...)``
    rather than just setting the Authorization header, because the
    fixture-provided client is already in force_authenticate mode
    (which bypasses real JWT decoding and leaves ``request.auth=None``).
    Passing the token here lands it on ``request.auth.payload`` exactly
    the way real JWT auth would — that's the path the permission class
    reads from.
    """
    from django.urls import reverse

    response = api_client.post(
        reverse("step_up"), {"password": password}, format="json"
    )
    assert response.status_code == 200, response.content
    new_access = response.data["access"]
    api_client.force_authenticate(user=user, token=AccessToken(new_access))
    return new_access


def test_gdpr_approve_deletion_returns_step_up_required_without_claim(
    api_client, user, tenant
):
    """Hitting the gated endpoint without a step-up token returns the
    canonical 403 with the machine-readable code, NOT just a generic
    forbidden — that's what the frontend interceptor branches on."""
    from django.urls import reverse

    # Make caller an admin so role permission passes; the gate we're
    # testing is identity-freshness, not role.
    if "admin" not in (user.roles or []):
        user.roles = ["admin"]
        user.save(update_fields=["roles"])

    # Any non-existent request_id is fine — we expect to be blocked
    # BEFORE the lookup. We only need to confirm the response shape.
    url = reverse("gdpr-admin-approve-deletion", kwargs={"request_id": "x"})
    response = api_client.post(url)

    assert response.status_code == 403
    assert response.data["code"] == "auth.step_up_required"
    assert response.data["details"]["ttl_seconds"] == 300


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_gdpr_approve_deletion_passes_step_up_with_fresh_token(
    api_client, user, tenant
):
    """With a fresh step-up token, the same call gets past the gate and
    proceeds to its normal lookup (which will fail with 404 — that's
    fine, it proves step-up isn't the blocker anymore)."""
    from django.urls import reverse

    if "admin" not in (user.roles or []):
        user.roles = ["admin"]
        user.save(update_fields=["roles"])
    user.set_password("step-up-test-pw-Zx9!")
    user.save(update_fields=["password"])

    _set_step_up_on_credentials(api_client, user, "step-up-test-pw-Zx9!")

    url = reverse("gdpr-admin-approve-deletion", kwargs={"request_id": "x"})
    response = api_client.post(url)

    # The step-up gate is past. Assert that UNCONDITIONALLY: a broken
    # gate surfaces as a 403 with code ``auth.step_up_required``, so that
    # exact combination must never occur. The old ``if status == 403``
    # guard was too weak — an unexpected 200 (gate silently bypassed) or
    # a 403 with a missing/None code would skip the assertion entirely.
    assert not (
        response.status_code == 403
        and response.data.get("code") == "auth.step_up_required"
    ), "fresh step-up token was rejected — the gate did not accept us"
    # Pin the expected post-gate outcome: the synthetic request_id has no
    # matching DeletionRequest, so the view body raises NotFoundError (404).
    # That 404 is positive proof the request reached the lookup past the gate.
    assert response.status_code == 404


# --------------------------------------------------------------------- #
# End-to-end: tenant admin role-grant gate (SEC-2)                      #
# --------------------------------------------------------------------- #


def _make_admin(user):
    if "admin" not in (user.roles or []):
        user.roles = ["admin"]
        user.save(update_fields=["roles"])


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_admin_user_role_grant_requires_step_up_without_claim(api_client, user, tenant):
    """Granting a role via ``PATCH /admin/users/<pk>/`` is privilege
    escalation — it must be step-up gated. Without a fresh claim the call
    returns the canonical 403 ``auth.step_up_required``, so a stolen session
    token alone can't escalate. SEC-2."""
    from django.urls import reverse

    _make_admin(user)
    target = JasminUserFactory(roles=["member"])

    url = reverse("admin-users-detail", kwargs={"pk": target.id})
    response = api_client.patch(url, {"roles": ["admin"]}, format="json")

    assert response.status_code == 403
    assert response.data["code"] == "auth.step_up_required"
    # The role must NOT have been granted — the gate blocks before the write.
    target.refresh_from_db()
    assert "admin" not in (target.roles or [])


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_admin_user_non_role_edit_does_not_require_step_up(api_client, user, tenant):
    """A PATCH that does NOT touch ``roles`` (name, language, …) must pass the
    gate unprompted — the modal fires only on actual role grants, so routine
    edits aren't friction-walled. SEC-2 (conditional gate)."""
    from django.urls import reverse

    _make_admin(user)
    target = JasminUserFactory(roles=["member"], first_name="Old")

    url = reverse("admin-users-detail", kwargs={"pk": target.id})
    response = api_client.patch(url, {"first_name": "Renamed"}, format="json")

    # Whatever the outcome, it must NOT be the step-up block — no role change
    # was requested, so the gate doesn't apply.
    assert not (
        response.status_code == 403
        and response.data.get("code") == "auth.step_up_required"
    )


@override_settings(STEP_UP_TTL_SECONDS=300)
def test_admin_user_role_grant_passes_with_fresh_step_up(api_client, user, tenant):
    """With a fresh step-up token the role grant gets PAST the gate (a broken
    gate would surface as 403 ``auth.step_up_required``, which must never
    happen here). SEC-2."""
    from django.urls import reverse

    _make_admin(user)
    user.set_password("step-up-test-pw-Zx9!")
    user.save(update_fields=["password"])
    target = JasminUserFactory(roles=["member"])

    _set_step_up_on_credentials(api_client, user, "step-up-test-pw-Zx9!")

    url = reverse("admin-users-detail", kwargs={"pk": target.id})
    response = api_client.patch(url, {"roles": ["office"]}, format="json")

    assert not (
        response.status_code == 403
        and response.data.get("code") == "auth.step_up_required"
    ), "fresh step-up token was rejected — the role-grant gate did not accept us"


# --------------------------------------------------------------------- #
# Shared helpers / fixtures                                             #
# --------------------------------------------------------------------- #


@pytest.fixture
def anon_client():
    """Empty APIClient — no credentials set."""
    from rest_framework.test import APIClient

    return APIClient()
