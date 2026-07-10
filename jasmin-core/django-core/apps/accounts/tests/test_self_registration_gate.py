"""Server-side gate for public self-registration.

``TenantSettings.allows_self_registration`` defaults False. The
``/api/auth/register/*`` endpoints must refuse with
``403 auth.self_registration_disabled`` unless the tenant opted in — so hiding
the login-page register buttons can't be bypassed by posting straight to the
API. This is the defense-in-depth half of the feature flag.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.shared.tenants.models import TenantSettings

REGISTER_URL = "/api/auth/register/"
SEND_CODE_URL = "/api/auth/register/send_code/"


def _set_self_registration(tenant, *, enabled: bool) -> None:
    TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        allows_self_registration=enabled,
    )


@pytest.mark.django_db
def test_register_refused_by_default(tenant):
    # No settings row => not opted in => blocked. The default posture.
    resp = APIClient().post(REGISTER_URL, data={}, format="json")
    assert resp.status_code == 403
    assert resp.data["code"] == "auth.self_registration_disabled"


@pytest.mark.django_db
def test_register_refused_when_explicitly_disabled(tenant):
    _set_self_registration(tenant, enabled=False)
    resp = APIClient().post(REGISTER_URL, data={}, format="json")
    assert resp.status_code == 403
    assert resp.data["code"] == "auth.self_registration_disabled"


@pytest.mark.django_db
def test_send_code_also_gated(tenant):
    # All three register endpoints share the gate — spot-check a second one.
    _set_self_registration(tenant, enabled=False)
    resp = APIClient().post(SEND_CODE_URL, data={}, format="json")
    assert resp.status_code == 403
    assert resp.data["code"] == "auth.self_registration_disabled"


@pytest.mark.django_db
def test_register_passes_gate_when_enabled(tenant):
    _set_self_registration(tenant, enabled=True)
    resp = APIClient().post(REGISTER_URL, data={}, format="json")
    # Passes the self-registration gate; an empty body then fails VALIDATION
    # (400) rather than the 403 self-registration refusal.
    assert resp.status_code != 403
    assert resp.data.get("code") != "auth.self_registration_disabled"
