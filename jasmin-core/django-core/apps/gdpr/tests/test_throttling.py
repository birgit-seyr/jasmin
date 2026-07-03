"""Tests for DRF ``ScopedRateThrottle`` scopes on the GDPR endpoints.

``apps/gdpr/views.py`` declares throttle scopes on three endpoints:

  - ``gdpr_request_deletion``  (5/hour)   — anti-mailbomb on the
                                            lodge endpoint
  - ``gdpr_confirm_deletion``  (10/minute) — anti-token-guess
  - ``gdpr_sar_export``        (2/hour)   — anti-DoS on the
                                            expensive SAR DB pass

The rates live in ``settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']``.
Without a test, someone could drop a ``throttle_scope`` attribute on
a view and not notice — the API would still respond 200 forever and
the security backstop would silently disappear.

We test the lodge endpoint (5/hour) because:
  - It's the cheapest cap (5 attempts, no waiting).
  - It's the highest-impact: a leaked JWT lets an attacker request
    deletion + spam the linked inbox with confirmation mails.

Cache hygiene: DRF tracks rates in Django's cache backend. Each test
clears the cache to avoid interference between test methods (and
between test runs on a long-lived cache like Redis).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory


@pytest.fixture
def clean_throttle_cache():
    """Wipe the throttle cache before AND after each test that uses
    it. DRF's ``SimpleRateThrottle`` keys are namespaced
    ``throttle_<scope>_<ident>``; clearing the whole cache is the
    simplest way to start from a known baseline without coupling to
    DRF internals."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestRequestDeletionThrottle:
    """``5/hour`` per authenticated user on
    ``POST /api/gdpr/request-deletion/``. The scope keys on user pk
    when authenticated (``ScopedRateThrottle`` default), so different
    users have independent budgets."""

    URL = reverse("gdpr-request-deletion")

    def test_429_after_quota_exhausted(self, tenant, clean_throttle_cache):
        """5 lodges go through. The 6th hits the per-user cap.

        Each lodge supersedes the previous one (the service flips
        the older row to ``CANCELLED``), but the throttle counts
        REQUESTS, not active rows — so the cap still fires.
        """
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        client = APIClient()
        client.force_authenticate(user=user)

        # 5 lodges allowed.
        for i in range(5):
            resp = client.post(self.URL)
            assert resp.status_code == 202, (
                f"attempt {i + 1}/5 should have succeeded, got {resp.status_code}: "
                f"{resp.content!r}"
            )

        # 6th gets throttled.
        resp = client.post(self.URL)
        assert resp.status_code == 429
        # DRF surfaces a ``Retry-After`` header so the client can back off.
        assert "Retry-After" in resp.headers

    def test_separate_users_have_independent_budgets(
        self, tenant, clean_throttle_cache
    ):
        """Per-user keying — Alice exhausting her 5-lodge cap must
        NOT lock Bob out. Without this property, one malicious user
        could DoS deletion-lodging for the whole tenant by exhausting
        a shared bucket."""
        alice = JasminUserFactory(roles=["member"], email="alice@example.com")
        bob = JasminUserFactory(roles=["member"], email="bob@example.com")

        client = APIClient()
        client.force_authenticate(user=alice)
        for _ in range(5):
            client.post(self.URL)
        # Alice is now at the cap.
        assert client.post(self.URL).status_code == 429

        # Bob is fresh; his first lodge is allowed.
        client.force_authenticate(user=bob)
        assert client.post(self.URL).status_code == 202
