"""Tenant mail never falls back to the platform ``EMAIL_*`` account.

Design decision: a tenant that has not configured its own SMTP must NOT
fall back to the platform ``EMAIL_*`` account — that transport is reserved
for operator / ops alerts (``mail_admins``). Tenant mail goes out through
the tenant's own SMTP or not at all. ``EmailService.send_email`` returns
False and never opens a connection.

Three guards enforce this and are pinned here:
  * ``send_email`` early-returns False (before rendering) when the active
    config has no SMTP host.
  * ``_get_connection`` is the authoritative backstop — it raises rather
    than let Django's ``get_connection(host=None, …)`` fall back to
    ``settings.EMAIL_HOST``.
  * ``_get_connection`` hands Django an empty username or password where
    the config stores none, never ``None``, which Django would replace with
    ``settings.EMAIL_HOST_USER`` / ``EMAIL_HOST_PASSWORD`` and log in to the
    tenant's host with. The one exception is the platform's own SMTP server
    (``EMAIL_HOST`` / ``EMAIL_PORT``): a config that names it logs in there
    with the platform's username or password where it stores none.
"""

from __future__ import annotations

from unittest import mock

import pytest

from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import TenantEmailConfig


def _config(tenant, **overrides) -> TenantEmailConfig:
    defaults = dict(
        tenant=tenant,
        from_email="noreply@example.org",
        from_name="Test Tenant",
        is_active=True,
    )
    defaults.update(overrides)
    return TenantEmailConfig.objects.create(**defaults)


@pytest.mark.django_db
class TestSendingDisabledWithoutSmtp:
    def test_has_smtp_configured_property(self, tenant):
        cfg = _config(tenant)  # no smtp_host
        assert cfg.has_smtp_configured is False
        cfg.smtp_host = "smtp.example.org"
        assert cfg.has_smtp_configured is True
        cfg.smtp_host = "   "  # whitespace-only counts as unset
        assert cfg.has_smtp_configured is False

    def test_send_email_disabled_without_smtp_host(self, tenant):
        """Active config, but no SMTP host → send is a no-op returning
        False, and the transport is never even opened (no fallback)."""
        _config(tenant)  # active, but smtp_host unset
        service = EmailService(tenant.schema_name)

        with mock.patch.object(
            EmailService, "_get_connection", autospec=True
        ) as get_conn:
            sent = service.send_email(
                to_emails=["someone@example.org"],
                context={},
                slug="tenants.smtp_test",
            )

        assert sent is False
        assert get_conn.call_count == 0

    def test_get_connection_refuses_without_host(self, tenant):
        """The authoritative backstop: even called directly, it refuses to
        build a connection (which would fall back to the platform host)."""
        _config(tenant)  # no smtp_host
        service = EmailService(tenant.schema_name)

        with pytest.raises(ValueError, match="No SMTP host configured"):
            service._get_connection()

    def test_send_email_proceeds_when_smtp_host_set(self, tenant):
        """Positive control: a configured host does NOT get blocked — the
        send reaches the assemble/send step. Rendering + transport are
        stubbed so the test stays template- and network-independent."""
        _config(tenant, smtp_host="smtp.example.org", smtp_port=587)
        service = EmailService(tenant.schema_name)

        with (
            mock.patch.object(
                EmailService,
                "_render_body",
                autospec=True,
                return_value=("Subject", "<p>hi</p>", "hi", "tpl"),
            ),
            mock.patch.object(
                EmailService, "_build_and_send", autospec=True, return_value=True
            ) as build_and_send,
        ):
            sent = service.send_email(
                to_emails=["someone@example.org"],
                context={},
                slug="tenants.smtp_test",
            )

        assert sent is True
        assert build_and_send.call_count == 1


PLATFORM_HOST = "smtp.mailkit.example"
PLATFORM_PORT = 587
PLATFORM_USER = "ops@platform.example"
PLATFORM_PASSWORD = "platform-secret"


@pytest.fixture()
def platform_account(settings):
    """The platform's own SMTP server and the account it logs in with."""
    settings.EMAIL_HOST = PLATFORM_HOST
    settings.EMAIL_PORT = PLATFORM_PORT
    settings.EMAIL_HOST_USER = PLATFORM_USER
    settings.EMAIL_HOST_PASSWORD = PLATFORM_PASSWORD
    # Keeps the send-time host check off the network.
    settings.SMTP_ALLOW_PRIVATE_HOSTS = True


def _connection(tenant):
    """The SMTP backend the tenant's mail goes out through, unopened."""
    return EmailService(tenant.schema_name)._get_connection()


def _logins(connection) -> list:
    """Open ``connection`` against a stand-in SMTP server and return the
    logins Django made on it."""
    with mock.patch("smtplib.SMTP") as smtp_server:
        connection.open()
    return smtp_server.return_value.login.call_args_list


@pytest.mark.django_db
@pytest.mark.usefixtures("platform_account")
class TestNoPlatformCredentials:
    """The tenant chooses the host, so the platform account logs in to no
    host but the platform's own SMTP server — not even to fill a username or
    password the config lacks."""

    @pytest.mark.parametrize(
        ("username", "password"),
        [(None, None), ("tenant-user", None), (None, "tenant-secret")],
    )
    def test_a_missing_credential_sends_without_a_login(
        self, tenant, username, password
    ):
        _config(
            tenant,
            smtp_host="smtp.example.org",
            smtp_username=username,
            smtp_password=password,
        )

        connection = _connection(tenant)

        # Empty, never ``None``, which the backend would replace with the
        # platform's username or password.
        assert connection.username == (username or "")
        assert connection.password == (password or "")
        assert _logins(connection) == []

    @pytest.mark.parametrize(
        "host",
        [
            f"{PLATFORM_HOST}.attacker.example",
            f"mail.{PLATFORM_HOST}",
            f"{PLATFORM_HOST}:{PLATFORM_PORT}",
            # A Kelvin sign for the "k": it lower-cases to an ASCII "k".
            "smtp.mailKit.example",
        ],
    )
    def test_a_host_resembling_the_platforms_gets_no_login(self, tenant, host):
        _config(tenant, smtp_host=host, smtp_port=PLATFORM_PORT)

        connection = _connection(tenant)

        assert (connection.username, connection.password) == ("", "")

    def test_the_platform_host_on_another_port_gets_no_login(self, tenant):
        _config(tenant, smtp_host=PLATFORM_HOST, smtp_port=2525)

        connection = _connection(tenant)

        assert (connection.username, connection.password) == ("", "")
        assert _logins(connection) == []

    def test_stored_credentials_log_in_unchanged(self, tenant):
        _config(
            tenant,
            smtp_host="smtp.example.org",
            smtp_username="tenant-user",
            smtp_password="tenant-secret",
        )

        assert _logins(_connection(tenant)) == [
            mock.call("tenant-user", "tenant-secret")
        ]


@pytest.mark.django_db
@pytest.mark.usefixtures("platform_account")
class TestPlatformSmtpServer:
    """A config may name the platform's own SMTP server, which already holds
    the platform's account: a username or password the config does not store
    is the platform's there."""

    @pytest.mark.parametrize(
        "host",
        [
            PLATFORM_HOST,
            "SMTP.MailKit.Example",
            f"  {PLATFORM_HOST}  ",
            f"{PLATFORM_HOST}.",
        ],
    )
    def test_a_config_without_credentials_logs_in_with_the_platform_account(
        self, tenant, host
    ):
        _config(tenant, smtp_host=host, smtp_port=PLATFORM_PORT)

        connection = _connection(tenant)

        assert (connection.username, connection.password) == (
            PLATFORM_USER,
            PLATFORM_PASSWORD,
        )
        assert _logins(connection) == [mock.call(PLATFORM_USER, PLATFORM_PASSWORD)]

    def test_a_config_without_a_port_connects_to_the_platform_port(self, tenant):
        _config(tenant, smtp_host=PLATFORM_HOST, smtp_port=None)

        connection = _connection(tenant)

        assert connection.port == PLATFORM_PORT
        assert (connection.username, connection.password) == (
            PLATFORM_USER,
            PLATFORM_PASSWORD,
        )

    @pytest.mark.parametrize(
        ("username", "password", "login"),
        [
            ("tenant-user", None, ("tenant-user", PLATFORM_PASSWORD)),
            (None, "tenant-secret", (PLATFORM_USER, "tenant-secret")),
            ("tenant-user", "tenant-secret", ("tenant-user", "tenant-secret")),
        ],
    )
    def test_a_stored_credential_is_kept(self, tenant, username, password, login):
        _config(
            tenant,
            smtp_host=PLATFORM_HOST,
            smtp_username=username,
            smtp_password=password,
        )

        assert _logins(_connection(tenant)) == [mock.call(*login)]

    def test_an_empty_credential_is_not_filled_in(self, tenant):
        """Only a credential the config does not store (``None``) is the
        platform's, the one Django's backend would fill in. An empty one is
        stored, so the config sends without a login here too."""
        _config(tenant, smtp_host=PLATFORM_HOST, smtp_username="", smtp_password="")

        connection = _connection(tenant)

        assert (connection.username, connection.password) == ("", "")
        assert _logins(connection) == []
