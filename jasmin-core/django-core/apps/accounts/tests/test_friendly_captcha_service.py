"""Friendly Captcha verification service — unit tests.

Covers the four observable behaviours documented in the service module
docstring: dormant (flag off), missing solution, FC ack, FC reject,
and network failure (fail-closed contract).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from django.test import override_settings

from apps.accounts.errors import CaptchaVerificationFailed
from apps.accounts.services import verify_captcha

# --------------------------------------------------------------------- #
# Flag off (default)                                                    #
# --------------------------------------------------------------------- #


@override_settings(FRIENDLY_CAPTCHA_ENABLED=False)
def test_disabled_is_noop_even_with_no_solution():
    """When the feature flag is off, the service must NEVER raise —
    we ship dormant and current callers don't send a solution yet."""
    verify_captcha(None, scope="login")
    verify_captcha("", scope="login")
    verify_captcha("anything", scope="login")


# --------------------------------------------------------------------- #
# Flag on, common paths                                                 #
# --------------------------------------------------------------------- #


_FC_SETTINGS = {
    "FRIENDLY_CAPTCHA_ENABLED": True,
    "FRIENDLY_CAPTCHA_SITEKEY": "FCMSITEKEYTEST",
    "FRIENDLY_CAPTCHA_SECRET": "FCMSECRETTEST",
    "FRIENDLY_CAPTCHA_VERIFY_URL": "https://fc.test/api/v1/siteverify",
    "FRIENDLY_CAPTCHA_TIMEOUT_SECONDS": 2.0,
}


@override_settings(**_FC_SETTINGS)
def test_missing_solution_raises():
    """A flag-on endpoint that receives no solution must reject."""
    with pytest.raises(CaptchaVerificationFailed):
        verify_captcha(None, scope="login")
    with pytest.raises(CaptchaVerificationFailed):
        verify_captcha("", scope="login")


@override_settings(**_FC_SETTINGS)
def test_valid_solution_passes_silently():
    """FC says ``success: true`` -> verify_captcha returns None."""
    with patch(
        "apps.accounts.services.friendly_captcha_service.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True}
        verify_captcha("a-valid-solution", scope="login")

    # Sanity: the call shape matches FC's documented payload.
    args, kwargs = mock_post.call_args
    assert args[0] == _FC_SETTINGS["FRIENDLY_CAPTCHA_VERIFY_URL"]
    assert kwargs["json"] == {
        "solution": "a-valid-solution",
        "secret": _FC_SETTINGS["FRIENDLY_CAPTCHA_SECRET"],
        "sitekey": _FC_SETTINGS["FRIENDLY_CAPTCHA_SITEKEY"],
    }
    assert kwargs["timeout"] == _FC_SETTINGS["FRIENDLY_CAPTCHA_TIMEOUT_SECONDS"]


@override_settings(**_FC_SETTINGS)
def test_invalid_solution_raises():
    """FC says ``success: false`` -> CaptchaVerificationFailed."""
    with patch(
        "apps.accounts.services.friendly_captcha_service.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": False,
            "errors": ["solution_invalid"],
        }
        with pytest.raises(CaptchaVerificationFailed):
            verify_captcha("a-bad-solution", scope="login")


# --------------------------------------------------------------------- #
# Fail-closed contract                                                  #
# --------------------------------------------------------------------- #


@override_settings(**_FC_SETTINGS)
def test_network_error_fails_closed():
    """If FC is unreachable the service raises, never silently passes.

    This is the contract guarantee the module docstring promises;
    keeping it as an explicit test prevents a well-meaning future
    change to "fail open on FC outage" from sliding in unnoticed.
    """
    with patch(
        "apps.accounts.services.friendly_captcha_service.requests.post",
        side_effect=requests.Timeout("FC timed out"),
    ):
        with pytest.raises(CaptchaVerificationFailed):
            verify_captcha("anything", scope="login")


@override_settings(**_FC_SETTINGS)
def test_non_200_response_fails_closed():
    """FC returning a 5xx is treated as unreachable."""
    with patch(
        "apps.accounts.services.friendly_captcha_service.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 503
        with pytest.raises(CaptchaVerificationFailed):
            verify_captcha("anything", scope="login")


# --------------------------------------------------------------------- #
# Operator misconfiguration                                             #
# --------------------------------------------------------------------- #


@override_settings(
    FRIENDLY_CAPTCHA_ENABLED=True,
    FRIENDLY_CAPTCHA_SITEKEY="",
    FRIENDLY_CAPTCHA_SECRET="",
    FRIENDLY_CAPTCHA_VERIFY_URL=_FC_SETTINGS["FRIENDLY_CAPTCHA_VERIFY_URL"],
    FRIENDLY_CAPTCHA_TIMEOUT_SECONDS=2.0,
)
def test_flag_on_but_creds_missing_fails_closed():
    """Operator turned the flag on without populating creds — fail
    closed so we don't silently accept every request. The error path
    here is distinct from a runtime FC failure (logger.error vs
    logger.warning), but observable behaviour is the same."""
    with pytest.raises(CaptchaVerificationFailed):
        verify_captcha("anything", scope="login")
