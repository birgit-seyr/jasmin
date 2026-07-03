"""Tests for the ``TenantEmailConfigViewSet.test_email`` action —
the P0-4 wiring documented in ``docs/code/email-overview.md``.

Contract:

  * The action MUST route through ``EmailService.send_email`` with
    ``slug="tenants.smtp_test"`` and ``purpose="test:smtp"`` so the
    send lands in EmailLog like every other send. The previous
    direct-``EmailMessage`` path was the only send in the codebase
    that bypassed EmailLog.
  * Recipient allowlist (audit A6): ``to_email`` must be the
    requesting user's own email or the (admin-controlled) tenant
    contact email — a compromised office account must not be able to
    use the tenant's SMTP as a spam relay. The office-writable
    ``from_email`` / ``reply_to_email`` are deliberately NOT allowed:
    they can be rewritten via ``save_config`` by the same role, which
    would reduce the lock to a two-request bypass.
  * The action is rate-limited via the shared ``email_test_send``
    throttle scope (same budget as the template editor's test send).
  * On success: ``TenantEmailConfig.is_verified`` flips to True.
  * On send_email returning False: 400 + ``is_verified`` stays False.
  * On SMTP exception bubbling out: 400 + ``is_verified`` stays False.
  * Errors are JasminErrors — canonical ``{code, message}`` body.

We patch ``EmailService.send_email`` with ``autospec=True`` so the
mock keeps the same ``self`` binding as the real method — same
class-vs-instance protection as the P0-1 regression test.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework import status

from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import TenantEmailConfig

# DRF auto-derives ``url_name`` from the method name (``test_email``)
# unless ``url_name=`` is set explicitly on the @action decorator.
# So the reverse-name is ``<basename>-<method-name-with-hyphens>``
# even though ``url_path="test"`` makes the URL itself /test/.
URL = reverse("tenant_email_config-test-email")


def _make_config(tenant) -> TenantEmailConfig:
    return TenantEmailConfig.objects.create(
        tenant=tenant,
        smtp_host="localhost",
        smtp_port=25,
        smtp_use_tls=False,
        from_email="noreply@example.org",
        from_name="Test Tenant",
        is_active=True,
    )


@pytest.mark.django_db
class TestTenantSmtpTestSend:
    def test_missing_to_email_returns_400(self, api_client, tenant):
        _make_config(tenant)
        resp = api_client.post(URL, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_config.test_recipient_missing"
        assert "to_email" in resp.data["message"].lower()

    def test_no_config_returns_400(self, api_client, tenant):
        # No TenantEmailConfig created for this tenant.
        resp = api_client.post(URL, {"to_email": "ops@example.org"}, format="json")
        # The action's ``self.get_object()`` raises 404 when no
        # config exists for the current tenant.
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
        )

    def test_arbitrary_recipient_is_rejected(self, api_client, tenant):
        """A6 lock: addresses outside the configuration's own set never
        reach the send path — no spam relay via a phished office user."""
        config = _make_config(tenant)

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            resp = api_client.post(
                URL, {"to_email": "victim@example.com"}, format="json"
            )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_config.test_recipient_not_allowed"
        assert not send_email.called
        config.refresh_from_db()
        assert config.is_verified is False

    def test_own_user_email_is_allowed(self, api_client, user, tenant):
        """The requesting office user can always test to their own
        address (case-insensitive)."""
        _make_config(tenant)

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            resp = api_client.post(URL, {"to_email": user.email.upper()}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert send_email.call_args.kwargs["to_emails"] == [user.email.upper()]

    def test_office_writable_sender_addresses_are_rejected(
        self, api_client, user, tenant
    ):
        """The configured sender / reply-to are NOT valid recipients:
        both are writable by the same office role via ``save_config``,
        so allowing them would reduce the A6 lock to a two-request
        bypass (PATCH reply_to_email, then POST test)."""
        config = _make_config(tenant)
        config.reply_to_email = "victim@example.com"
        config.save(update_fields=["reply_to_email"])

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            for recipient in ("noreply@example.org", "victim@example.com"):
                resp = api_client.post(URL, {"to_email": recipient}, format="json")
                assert resp.status_code == status.HTTP_400_BAD_REQUEST
                assert resp.data["code"] == "email_config.test_recipient_not_allowed"

        assert not send_email.called

    def test_throttle_is_attached_to_the_action(self):
        """A throttle on the action keeps the (allowlisted) test send
        from being driven in a loop. Scope shared with the template
        editor's test send."""
        from apps.shared.tenants.viewsets import (
            EmailConfigTestSendThrottle,
            TenantEmailConfigViewSet,
        )

        throttles = TenantEmailConfigViewSet.test_email.kwargs["throttle_classes"]
        assert EmailConfigTestSendThrottle in throttles
        assert EmailConfigTestSendThrottle.scope == "email_test_send"

    def test_happy_path_routes_through_email_service(self, api_client, user, tenant):
        config = _make_config(tenant)
        assert config.is_verified is False

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            # The requesting user's own address is in the allowlist.
            resp = api_client.post(URL, {"to_email": user.email}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert send_email.called
        # autospec keeps ``self`` as the first positional arg —
        # asserts the helper hit the method via an instance, not the
        # class. Same protection pattern as the P0-1 regression.
        bound_self = send_email.call_args.args[0]
        assert isinstance(bound_self, EmailService)
        kwargs = send_email.call_args.kwargs
        assert kwargs["slug"] == "tenants.smtp_test"
        assert kwargs["to_emails"] == [user.email]
        assert kwargs["purpose"] == "test:smtp"
        assert kwargs["related_object_type"] == "tenant_email_config"

        config.refresh_from_db()
        assert config.is_verified is True

    def test_send_email_returns_false_marks_400_and_no_verify(
        self, api_client, user, tenant
    ):
        config = _make_config(tenant)

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=False
        ):
            resp = api_client.post(URL, {"to_email": user.email}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_config.test_send_failed"
        config.refresh_from_db()
        assert config.is_verified is False

    def test_smtp_exception_marks_400_and_no_verify(self, api_client, user, tenant):
        import smtplib

        config = _make_config(tenant)

        with mock.patch.object(
            EmailService,
            "send_email",
            autospec=True,
            side_effect=smtplib.SMTPException("simulated SMTP outage"),
        ):
            resp = api_client.post(URL, {"to_email": user.email}, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "failed" in resp.data["message"].lower()
        config.refresh_from_db()
        assert config.is_verified is False
