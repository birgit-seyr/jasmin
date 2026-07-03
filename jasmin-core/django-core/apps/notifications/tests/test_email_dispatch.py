"""End-to-end test for `EmailService.send_email`.

Captures via Django's `mail.outbox` (locmem backend) and asserts:
    - Outbox grows by exactly one message.
    - Subject and body are rendered from the registered slug template.
    - Plaintext + HTML alternative are both attached.
    - From / To / Reply-To match the tenant config.
    - An `EmailLog` row is created with status=sent.

We patch `EmailService._get_connection` to use the locmem backend so the
test does not depend on a real ESP. Everything else (registry lookup,
template rendering, EmailLog creation) is exercised for real.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core import mail
from django.core.mail import get_connection

from apps.notifications.models import EmailLog
from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import TenantEmailConfig


@pytest.fixture
def email_config(tenant):
    """Minimal SMTP TenantEmailConfig wired to the locmem backend."""
    cfg = TenantEmailConfig.objects.create(
        tenant=tenant,
        smtp_host="localhost",
        smtp_port=25,
        smtp_username="",
        smtp_password="",
        smtp_use_tls=False,
        from_email="noreply@example.org",
        from_name="Test Tenant",
        reply_to_email="hello@example.org",
        is_active=True,
        is_verified=True,
    )
    return cfg


@pytest.fixture(autouse=True)
def _use_locmem_backend():
    """Force EmailService to use the in-memory backend for the test.

    Also clears the per-tenant config cache so each test starts fresh.
    """
    from django.core.cache import cache

    cache.clear()
    locmem = get_connection(backend="django.core.mail.backends.locmem.EmailBackend")
    with patch.object(EmailService, "_get_connection", return_value=locmem):
        yield
    cache.clear()


@pytest.mark.django_db
class TestEmailDispatch:
    def test_send_email_via_slug_lands_in_outbox(self, tenant, email_config):
        mail.outbox.clear()
        ok = EmailService(schema_name=tenant.schema_name).send_email(
            slug="accounts.password_reset",
            to_emails=["maria@example.org"],
            context={
                "tenant_name": "Test Tenant",
                "user": {"first_name": "Maria"},
                "reset_url": "https://app.example.org/reset/abc",
                "expires_minutes": "60",
            },
            language="en",
        )
        assert ok is True
        assert len(mail.outbox) == 1

        msg = mail.outbox[0]
        assert msg.to == ["maria@example.org"]
        # From address combines from_name + from_email.
        assert "noreply@example.org" in msg.from_email
        assert "Test Tenant" in msg.from_email
        assert msg.reply_to == ["hello@example.org"]

        # Subject is rendered from the registry default through the safe
        # renderer — it should contain the tenant_name we passed.
        assert "Test Tenant" in msg.subject

        # An HTML alternative must be attached alongside the text body.
        alt_types = [mt for _body, mt in msg.alternatives]
        assert "text/html" in alt_types

        # The reset URL must appear somewhere in the rendered body.
        full_body = msg.body + " ".join(b for b, _ in msg.alternatives)
        assert "https://app.example.org/reset/abc" in full_body

    def test_send_email_creates_email_log_with_sent_status(self, tenant, email_config):
        mail.outbox.clear()
        before = EmailLog.objects.count()

        EmailService(schema_name=tenant.schema_name).send_email(
            slug="accounts.password_reset",
            to_emails=["maria@example.org", "tom@example.org"],
            context={
                "tenant_name": "Test Tenant",
                "user": {"first_name": "Maria"},
                "reset_url": "https://app.example.org/reset/abc",
                "expires_minutes": "60",
            },
            language="en",
        )

        # One EmailLog row per recipient.
        new_logs = EmailLog.objects.order_by("-id")[: EmailLog.objects.count() - before]
        assert new_logs.count() == 2
        for row in new_logs:
            assert row.status == "sent"
            assert row.sent_at is not None
            assert row.recipient in {"maria@example.org", "tom@example.org"}

    def test_unsupported_explicit_language_is_normalized(self, tenant, email_config):
        """An explicit ``language`` (e.g. an unvalidated user_language CharField)
        is normalized before template resolution — ``'deu'`` resolves as
        ``'de'`` instead of bypassing normalization and mis-resolving."""
        mail.outbox.clear()
        import apps.shared.tenants.email_service as es

        original = es._resolve_template
        seen: dict[str, str] = {}

        def spy(slug, context, language, **kwargs):
            seen["language"] = language
            return original(slug, context, language, **kwargs)

        with patch.object(es, "_resolve_template", spy):
            ok = EmailService(schema_name=tenant.schema_name).send_email(
                slug="accounts.password_reset",
                to_emails=["maria@example.org"],
                context={
                    "tenant_name": "Test Tenant",
                    "user": {"first_name": "Maria"},
                    "reset_url": "https://app.example.org/reset/abc",
                    "expires_minutes": "60",
                },
                language="deu",  # unsupported alias for German
            )

        assert ok is True
        assert (
            seen["language"] == "de"
        ), f"explicit 'deu' should normalize to 'de', got {seen['language']!r}"

    def test_no_config_returns_false(self, tenant):
        # No TenantEmailConfig at all → service should bail out, not crash.
        ok = EmailService(schema_name=tenant.schema_name).send_email(
            slug="accounts.password_reset",
            to_emails=["maria@example.org"],
            context={
                "tenant_name": "Test Tenant",
                "user": {"first_name": "Maria"},
                "reset_url": "https://app.example.org/reset/abc",
                "expires_minutes": "60",
            },
        )
        assert ok is False

    def test_send_email_stamps_rfc5322_message_id(self, tenant, email_config):
        """P1-4: every outgoing message must carry a stable Message-ID
        that's mirrored on every EmailLog row, so a future bounce
        webhook can resolve `provider_message_id` back to the rows.
        """
        mail.outbox.clear()
        before_ids = set(EmailLog.objects.values_list("id", flat=True))

        EmailService(schema_name=tenant.schema_name).send_email(
            slug="accounts.password_reset",
            to_emails=["alice@example.org", "bob@example.org"],
            context={
                "tenant_name": "Test Tenant",
                "user": {"first_name": "Alice"},
                "reset_url": "https://app.example.org/reset/xyz",
                "expires_minutes": "60",
            },
            language="en",
        )

        # Header stamped on the outgoing EmailMultiAlternatives.
        assert len(mail.outbox) == 1
        message_id = mail.outbox[0].extra_headers["Message-ID"]
        assert message_id.startswith("<") and message_id.endswith(">")
        # Domain half pulls from from_email.
        assert "@example.org>" in message_id

        # Every freshly-created EmailLog row carries the same ID.
        new_logs = EmailLog.objects.exclude(id__in=before_ids)
        assert new_logs.count() == 2
        message_ids = set(new_logs.values_list("provider_message_id", flat=True))
        assert message_ids == {message_id}

    def test_message_id_is_unique_per_send(self, tenant, email_config):
        """Two separate sends must NOT collide on Message-ID."""
        mail.outbox.clear()
        service = EmailService(schema_name=tenant.schema_name)
        for _ in range(2):
            service.send_email(
                slug="accounts.password_reset",
                to_emails=["maria@example.org"],
                context={
                    "tenant_name": "Test Tenant",
                    "user": {"first_name": "Maria"},
                    "reset_url": "https://app.example.org/reset/abc",
                    "expires_minutes": "60",
                },
                language="en",
            )

        first_id = mail.outbox[0].extra_headers["Message-ID"]
        second_id = mail.outbox[1].extra_headers["Message-ID"]
        assert first_id != second_id
