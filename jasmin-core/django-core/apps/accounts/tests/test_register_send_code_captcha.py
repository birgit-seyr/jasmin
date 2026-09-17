"""``register/send_code`` verifies the captcha token its serializer produced.

The endpoint validates the whole body with ``RegisterSendCodeRequestSerializer``
before the captcha check, so the token handed to ``verify_captcha`` carries the
``CharField`` trim and string coercion — the same input the sibling captcha
endpoints (login, password reset, register) check.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.shared.tenants.models import TenantSettings

SEND_CODE_URL = "/api/auth/register/send_code/"

pytestmark = pytest.mark.django_db


@pytest.fixture()
def _self_registration_on(tenant):
    TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        allows_self_registration=True,
    )


def _send_code(payload):
    """POST the payload with the captcha service and the mailer stubbed out.

    Returns the response plus the ``verify_captcha`` mock so the caller can
    assert on the token the view passed it.
    """
    with (
        patch("apps.accounts.views.auth_views.verify_captcha") as verify,
        patch("apps.accounts.views.auth_views.schedule_deferred_email"),
    ):
        response = APIClient().post(SEND_CODE_URL, data=payload, format="json")
    return response, verify


def test_captcha_token_is_trimmed_before_verification(_self_registration_on):
    response, verify = _send_code(
        {"email": "fresh@example.com", "frc_captcha_solution": "  solved-token  "}
    )

    assert response.status_code == status.HTTP_200_OK
    assert verify.call_args.args[0] == "solved-token"
    assert verify.call_args.kwargs["scope"] == "register"


def test_a_numeric_captcha_token_reaches_the_service_as_a_string(
    _self_registration_on,
):
    response, verify = _send_code(
        {"email": "numeric@example.com", "frc_captcha_solution": 12345}
    )

    assert response.status_code == status.HTTP_200_OK
    assert verify.call_args.args[0] == "12345"


def test_an_absent_captcha_token_is_verified_as_none(_self_registration_on):
    # The field is optional, so the service still decides (it refuses only when
    # the captcha flag is on).
    response, verify = _send_code({"email": "plain@example.com"})

    assert response.status_code == status.HTTP_200_OK
    assert verify.call_args.args[0] is None
