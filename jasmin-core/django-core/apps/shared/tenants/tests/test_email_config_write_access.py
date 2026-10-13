"""Who may change the tenant's email config, and what a change leaves behind.

Whoever controls the SMTP server reads every message sent through it — the
password-reset links of admin accounts among them — and receives the stored
SMTP password when Django logs in. So only an admin may save the config or send
a test through it, with or without step-up; office still reads it, since office
pages disable invitations while the tenant has no SMTP host of its own. A change
to the connection drops the verified mark until the next test send succeeds,
and every change leaves an ``email_config.updated`` line in the security log
naming the actor and the changed fields, never their values.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import TenantEmailConfig

LIST_URL = reverse("tenant_email_config-list")
SAVE_URL = reverse("tenant_email_config-save-config")
TEST_URL = reverse("tenant_email_config-test-email")

STORED = {
    "smtp_host": "smtp.example.org",
    "smtp_port": 587,
    "smtp_username": "mailer",
    "smtp_use_tls": True,
    "smtp_use_ssl": False,
    "from_email": "office@example.org",
    "from_name": "Hof",
    "reply_to_email": "",
    "accounting_email": "",
    "max_emails_per_hour": 1000,
    "is_active": True,
}


def _form(**changes) -> dict:
    """The settings page's autosave body: the whole form, sent on every edit,
    with the write-only password left out unless one was typed."""
    return {**STORED, **changes}


def _step_up_client(user, tenant_host) -> APIClient:
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=user, token=make_step_up_token(user))
    return client


def _logged_line(security_log: mock.Mock) -> str:
    message, *args = security_log.warning.call_args.args
    return message % tuple(args)


@pytest.fixture()
def admin(tenant):
    return JasminUserFactory(roles=["admin"])


@pytest.fixture()
def admin_client(admin, tenant_host):
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=admin)
    return client


@pytest.fixture()
def admin_step_up_client(admin, tenant_host):
    return _step_up_client(admin, tenant_host)


@pytest.fixture()
def office_step_up_client(user, tenant_host):
    return _step_up_client(user, tenant_host)


@pytest.fixture()
def config(tenant):
    """A verified config: a test send has gone through it."""
    config, _ = TenantEmailConfig.objects.update_or_create(
        tenant=tenant,
        defaults={**STORED, "smtp_password": "stored-secret", "is_verified": True},
    )
    return config


@pytest.mark.django_db
class TestOfficeReadsButDoesNotWrite:
    def test_office_reads_the_config(self, api_client, config):
        resp = api_client.get(LIST_URL)

        assert resp.status_code == 200, resp.data
        assert resp.data["smtp_host"] == STORED["smtp_host"]
        assert "smtp_password" not in resp.data

    @pytest.mark.parametrize("method", ["patch", "put"])
    def test_office_with_step_up_cannot_repoint_the_host(
        self, office_step_up_client, config, method
    ):
        send = getattr(office_step_up_client, method)

        resp = send(SAVE_URL, _form(smtp_host="smtp.attacker.example"), format="json")

        assert resp.status_code == 403
        assert resp.data["code"] == "permission_denied"
        config.refresh_from_db()
        assert config.smtp_host == STORED["smtp_host"]
        assert config.is_verified is True

    def test_office_cannot_change_a_display_field_either(self, api_client, config):
        resp = api_client.patch(SAVE_URL, {"from_name": "Hof am See"}, format="json")

        assert resp.status_code == 403
        assert resp.data["code"] == "permission_denied"
        config.refresh_from_db()
        assert config.from_name == STORED["from_name"]

    def test_office_cannot_send_a_test(self, office_step_up_client, user, config):
        config.is_verified = False
        config.save(update_fields=["is_verified"])

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            resp = office_step_up_client.post(
                TEST_URL, {"to_email": user.email}, format="json"
            )

        assert resp.status_code == 403
        assert resp.data["code"] == "permission_denied"
        assert not send_email.called
        config.refresh_from_db()
        assert config.is_verified is False


@pytest.mark.django_db
class TestVerificationReset:
    @pytest.mark.parametrize(
        "change",
        [
            {"smtp_host": "smtp.other.example"},
            {"smtp_port": 2525},
            {"smtp_username": "someone-else"},
            {"smtp_use_tls": False},
            {"smtp_port": 465, "smtp_use_tls": False, "smtp_use_ssl": True},
            {"smtp_password": "new-secret"},
        ],
    )
    def test_a_connection_change_drops_the_verified_mark(
        self, admin_step_up_client, config, change
    ):
        resp = admin_step_up_client.patch(SAVE_URL, _form(**change), format="json")

        assert resp.status_code == 200, resp.data
        assert resp.data["is_verified"] is False
        config.refresh_from_db()
        assert config.is_verified is False

    @pytest.mark.parametrize(
        "change",
        [
            {},
            {"smtp_password": ""},
            {"from_name": "Hof am See"},
            {"is_active": False},
        ],
    )
    def test_an_unchanged_connection_keeps_the_verified_mark(
        self, admin_step_up_client, config, change
    ):
        resp = admin_step_up_client.patch(SAVE_URL, _form(**change), format="json")

        assert resp.status_code == 200, resp.data
        config.refresh_from_db()
        assert config.is_verified is True


@pytest.mark.django_db
class TestEmailConfigUpdateTrail:
    def test_a_change_logs_the_actor_and_the_field_names(
        self, admin_step_up_client, admin, tenant, config
    ):
        with mock.patch("apps.shared.tenants.viewsets._security_log") as security_log:
            resp = admin_step_up_client.patch(
                SAVE_URL,
                _form(smtp_host="smtp.other.example", smtp_password="new-secret"),
                format="json",
            )

        assert resp.status_code == 200, resp.data
        security_log.warning.assert_called_once()
        line = _logged_line(security_log)
        assert line.startswith("email_config.updated ")
        assert f"actor={admin.id}" in line
        assert f"tenant={tenant.schema_name}" in line
        assert line.endswith(" fields=smtp_host,smtp_password")
        assert "smtp.other.example" not in line
        assert "new-secret" not in line

    def test_an_unchanged_echo_logs_nothing(self, admin_step_up_client, config):
        with mock.patch("apps.shared.tenants.viewsets._security_log") as security_log:
            resp = admin_step_up_client.patch(SAVE_URL, _form(), format="json")

        assert resp.status_code == 200, resp.data
        security_log.warning.assert_not_called()

    def test_a_save_refused_for_lack_of_step_up_logs_nothing(
        self, admin_client, config
    ):
        with mock.patch("apps.shared.tenants.viewsets._security_log") as security_log:
            resp = admin_client.patch(
                SAVE_URL, _form(smtp_host="smtp.other.example"), format="json"
            )

        assert resp.status_code == 403
        assert resp.data["code"] == "auth.step_up_required"
        security_log.warning.assert_not_called()
