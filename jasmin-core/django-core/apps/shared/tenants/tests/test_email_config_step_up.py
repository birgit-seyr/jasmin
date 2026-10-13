"""Step-up gate on the tenant's email config.

Only an admin may save the config. Whoever controls the SMTP server reads every
message sent through it — the invitation and password-reset links for admin
accounts among them — so a save that changes where mail goes out, or where
replies and invoices land, also needs a fresh step-up claim. The sender's
display name and an unchanged echo don't.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.conftest import make_step_up_token
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.tenants.models import TenantEmailConfig

URL = reverse("tenant_email_config-save-config")


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
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=admin, token=make_step_up_token(admin))
    return client


@pytest.fixture
def config(tenant):
    config, _ = TenantEmailConfig.objects.update_or_create(
        tenant=tenant,
        defaults={
            "smtp_host": "smtp.example.org",
            "smtp_port": 587,
            "from_email": "office@example.org",
            "from_name": "Hof",
            "is_active": True,
        },
    )
    return config


@pytest.mark.django_db
class TestEmailConfigStepUp:
    @pytest.mark.parametrize(
        "change",
        [
            {"smtp_host": "smtp.attacker.example"},
            {"smtp_password": "new-secret"},
            {"accounting_email": "elsewhere@example.org"},
            {"reply_to_email": "elsewhere@example.org"},
        ],
    )
    def test_a_routing_change_without_step_up_is_refused(
        self, admin_client, config, change
    ):
        resp = admin_client.patch(URL, change, format="json")

        assert resp.status_code == 403
        assert resp.data["code"] == "auth.step_up_required"
        config.refresh_from_db()
        assert config.smtp_host == "smtp.example.org"
        assert not config.accounting_email

    def test_a_routing_change_with_step_up_is_saved(self, admin_step_up_client, config):
        resp = admin_step_up_client.patch(
            URL, {"smtp_host": "smtp.other.example"}, format="json"
        )

        assert resp.status_code == 200, resp.data
        config.refresh_from_db()
        assert config.smtp_host == "smtp.other.example"

    def test_the_display_name_and_an_unchanged_echo_need_no_step_up(
        self, admin_client, config
    ):
        resp = admin_client.patch(
            URL,
            {
                "from_name": "Hof am See",
                "smtp_host": "smtp.example.org",
                "smtp_port": 587,
                "smtp_password": "",
            },
            format="json",
        )

        assert resp.status_code == 200, resp.data
        config.refresh_from_db()
        assert config.from_name == "Hof am See"
