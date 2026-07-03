"""Regression tests: the credential / 2FA / step-up throttles actually fire.

Brute-force defense for login, 2FA-verify, and step-up is wired via the
fragile module-level pattern ``view_fn.cls.throttle_scope = "login"`` (three
separate assignments). The accounts conftest documents that BEFORE the
2026-06 fix this wiring shipped as a silent no-op — brute-force protection
was effectively disabled with green CI.

A 6-digit TOTP is brute-forceable, so a dropped ``.cls.throttle_scope`` line
must fail CI, not slip through. These tests POST each endpoint past its rate
limit and assert the over-limit request returns 429.

Login + 2FA-verify share the ``"login"`` scope (20/minute); step-up has its
own stricter ``"step_up"`` scope (10/minute) so a wrong-password grind behind
a valid session is capped independently of the login flow. The accounts
conftest's autouse ``_clear_throttle_cache`` resets the bucket before each
test, so each method starts from a fresh budget. login + 2FA-verify are
anonymous and key on client IP; step-up is authenticated and keys on the user
pk — hence separate methods keep the buckets from conflating.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory

# Scope rates (config/settings.py DEFAULT_THROTTLE_RATES).
RATE = 20  # "login" scope (login + 2FA-verify)
STEP_UP_RATE = 10  # "step_up" scope (tighter than login)

pytestmark = pytest.mark.django_db


def _assert_throttled_after_quota(client, url, payload, rate=RATE):
    """Send ``rate`` allowed requests (each must NOT be 429), then assert the
    next one is throttled. The throttle fires in APIView.initial() BEFORE the
    view body validates, so wrong/empty creds still count toward the cap."""
    for i in range(rate):
        resp = client.post(url, payload, format="json")
        assert resp.status_code != 429, (
            f"request {i + 1}/{rate} was throttled too early "
            f"(status {resp.status_code}) — is the rate lower than {rate}?"
        )
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 429, (
        f"request {rate + 1} should be throttled (429) but got "
        f"{resp.status_code} — the throttle_scope wiring may be a no-op."
    )
    assert "Retry-After" in resp.headers


class TestLoginThrottle:
    def test_429_after_login_quota_exhausted(self, tenant):
        _assert_throttled_after_quota(
            APIClient(),
            reverse("login"),
            {"email": "nobody@example.com", "password": "wrong"},
        )


class TestTwoFactorVerifyThrottle:
    def test_429_after_verify_quota_exhausted(self, tenant):
        _assert_throttled_after_quota(
            APIClient(),
            reverse("two_factor_verify"),
            {"challenge_token": "bogus", "code": "000000"},
        )


class TestStepUpThrottle:
    def test_429_after_step_up_quota_exhausted(self, tenant):
        # Step-up is IsAuthenticated → the throttle keys on the user pk, so it
        # needs an authenticated client (not the anonymous/IP path above).
        user = JasminUserFactory(roles=["office"], email="stepup@example.com")
        user.set_password("step-up-test-pw-Zx9!")
        user.save(update_fields=["password"])
        client = APIClient()
        client.force_authenticate(user=user)
        _assert_throttled_after_quota(
            client, reverse("step_up"), {"password": "wrong"}, rate=STEP_UP_RATE
        )


class TestThrottleClientIpResolution:
    """The IP-keyed throttles above only hold if the throttle ident is the
    REAL client IP. The gateway APPENDS the client IP to any caller-supplied
    X-Forwarded-For, so with ``REST_FRAMEWORK['NUM_PROXIES'] = 1`` DRF keys on
    the last (gateway-appended) entry. Without that setting it keys on the
    WHOLE XFF string — letting an attacker prepend a per-request forged entry
    to get a fresh bucket every request, fully bypassing the scoped limits.
    This pins the setting: drop it and ``get_ident`` reverts to the full-XFF
    behaviour and the two forged-prefix requests stop sharing a bucket."""

    def test_forged_xff_prefix_does_not_change_throttle_ident(self):
        from rest_framework.test import APIRequestFactory
        from rest_framework.throttling import BaseThrottle

        factory = APIRequestFactory()
        throttle = BaseThrottle()
        real_ip = "203.0.113.7"

        # Same trailing (gateway-appended) real IP; different attacker-
        # prepended forged entries.
        r1 = factory.get(
            "/",
            HTTP_X_FORWARDED_FOR=f"9.9.9.9, {real_ip}",
            REMOTE_ADDR="172.16.0.1",
        )
        r2 = factory.get(
            "/",
            HTTP_X_FORWARDED_FOR=f"8.8.8.8, {real_ip}",
            REMOTE_ADDR="172.16.0.1",
        )

        assert throttle.get_ident(r1) == real_ip
        assert throttle.get_ident(r2) == real_ip
        # Both forged-prefix requests collapse to ONE bucket — no bypass.
        assert throttle.get_ident(r1) == throttle.get_ident(r2)
