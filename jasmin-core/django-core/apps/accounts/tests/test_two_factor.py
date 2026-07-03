"""Tests for the two-factor auth (TOTP) feature.

Two layers:

  * **Service tests** — drive ``two_factor_service`` directly with a real
    TOTPDevice. The 6-digit code is generated locally from the device's
    own secret using ``django_otp.oath.totp`` so the tests don't depend
    on the system clock matching anything in particular.
  * **HTTP tests** — POST against the live URL routes to confirm wiring
    (login branches, /verify/, /status/, /enroll-start/, /enroll-confirm/,
    /disable/, /recovery-codes/regenerate/).

Why both: the service tests are stable across URL changes; the HTTP
tests catch the wiring breakage that pure-service tests miss (URL
typos, middleware, decorators, serializer drift).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.conf import settings
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.errors import (
    TwoFactorAlreadyEnrolled,
    TwoFactorChallengeInvalid,
    TwoFactorInvalidCode,
    TwoFactorNotEnrolled,
)
from apps.accounts.services import two_factor_service
from apps.commissioning.tests.factories import JasminUserFactory

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _current_totp(device: TOTPDevice) -> str:
    """Generate the current valid TOTP code for the device."""
    return format(totp(device.bin_key, step=device.step, digits=device.digits), "06d")


def _enrol(user) -> TOTPDevice:
    """Run start + confirm; return the active TOTPDevice.

    Test-only: resets the device's ``last_t`` after confirm so the next
    operation in this test (typically ``verify_code``) can re-use the
    current 30-second window's token. ``confirm_enrollment`` internally
    calls ``device.verify_token(...)``, which django-otp persists as
    ``last_t = t`` so the same token can't be replayed. In production
    that's exactly what we want; in tests we treat each call as a
    distinct user action and don't want to span clock ticks.
    """
    two_factor_service.start_enrollment(user=user, issuer="Test")
    device = TOTPDevice.objects.get(user=user, confirmed=False)
    code = _current_totp(device)
    two_factor_service.confirm_enrollment(user=user, code=code)
    confirmed = TOTPDevice.objects.get(user=user, confirmed=True)
    confirmed.last_t = -1
    confirmed.save(update_fields=["last_t"])
    return confirmed


def _set_password(user, raw):
    user.set_password(raw)
    user.save(update_fields=["password"])


# --------------------------------------------------------------------------- #
# Service: status                                                              #
# --------------------------------------------------------------------------- #


class TestStatus:
    def test_status_when_not_enrolled(self, tenant):
        user = JasminUserFactory()
        state = two_factor_service.status_for_user(user)
        assert state.enrolled is False
        assert state.recovery_codes_remaining == 0

    def test_status_when_enrolled(self, tenant):
        user = JasminUserFactory()
        _enrol(user)
        state = two_factor_service.status_for_user(user)
        assert state.enrolled is True
        assert state.recovery_codes_remaining == 10


# --------------------------------------------------------------------------- #
# Service: enrolment                                                           #
# --------------------------------------------------------------------------- #


class TestEnrolment:
    def test_start_creates_pending_device_and_returns_uri(self, tenant):
        user = JasminUserFactory(email="enrol@example.com")
        start = two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        assert start.secret
        assert start.provisioning_uri.startswith("otpauth://totp/")
        assert "secret=" in start.provisioning_uri
        assert "issuer=Jasmin" in start.provisioning_uri
        assert TOTPDevice.objects.filter(user=user, confirmed=False).count() == 1

    def test_start_rotates_secret_if_pending_exists(self, tenant):
        user = JasminUserFactory()
        first = two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        second = two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        # Same row, different secret — half-finished QR codes can't survive.
        assert TOTPDevice.objects.filter(user=user, confirmed=False).count() == 1
        assert first.secret != second.secret

    def test_start_refuses_when_already_enrolled(self, tenant):
        user = JasminUserFactory()
        _enrol(user)
        with pytest.raises(TwoFactorAlreadyEnrolled):
            two_factor_service.start_enrollment(user=user, issuer="Jasmin")

    def test_confirm_with_right_code_activates_device_and_mints_codes(self, tenant):
        user = JasminUserFactory()
        two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        result = two_factor_service.confirm_enrollment(
            user=user, code=_current_totp(device)
        )
        assert len(result.recovery_codes) == 10
        device.refresh_from_db()
        assert device.confirmed is True
        assert StaticDevice.objects.filter(user=user, confirmed=True).exists()

    def test_confirm_with_wrong_code_rejected(self, tenant):
        user = JasminUserFactory()
        two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        with pytest.raises(TwoFactorInvalidCode):
            two_factor_service.confirm_enrollment(user=user, code="000000")

    def test_confirm_without_enrolment_raises_not_enrolled(self, tenant):
        user = JasminUserFactory()
        with pytest.raises(TwoFactorNotEnrolled):
            two_factor_service.confirm_enrollment(user=user, code="123456")


# --------------------------------------------------------------------------- #
# Service: verify                                                              #
# --------------------------------------------------------------------------- #


class TestVerify:
    def test_totp_code_accepted(self, tenant):
        user = JasminUserFactory()
        device = _enrol(user)
        assert two_factor_service.verify_code(user=user, code=_current_totp(device))

    def test_recovery_code_accepted_and_consumed(self, tenant):
        user = JasminUserFactory()
        two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        result = two_factor_service.confirm_enrollment(
            user=user, code=_current_totp(device)
        )
        recovery = result.recovery_codes[0]
        assert two_factor_service.verify_code(user=user, code=recovery)
        # Same recovery code cannot be reused.
        with pytest.raises(TwoFactorInvalidCode):
            two_factor_service.verify_code(user=user, code=recovery)

    def test_wrong_code_rejected(self, tenant):
        user = JasminUserFactory()
        _enrol(user)
        with pytest.raises(TwoFactorInvalidCode):
            two_factor_service.verify_code(user=user, code="000000")

    def test_verify_without_device_raises_not_enrolled(self, tenant):
        user = JasminUserFactory()
        with pytest.raises(TwoFactorNotEnrolled):
            two_factor_service.verify_code(user=user, code="123456")


# --------------------------------------------------------------------------- #
# Service: disable + regenerate                                                #
# --------------------------------------------------------------------------- #


class TestDisable:
    def test_disable_removes_devices_with_valid_code(self, tenant):
        user = JasminUserFactory()
        device = _enrol(user)
        two_factor_service.disable(user=user, code=_current_totp(device))
        assert not TOTPDevice.objects.filter(user=user).exists()
        assert not StaticDevice.objects.filter(user=user).exists()

    def test_disable_rejects_wrong_code(self, tenant):
        user = JasminUserFactory()
        _enrol(user)
        with pytest.raises(TwoFactorInvalidCode):
            two_factor_service.disable(user=user, code="000000")


class TestRegenerateRecoveryCodes:
    def test_regenerate_returns_fresh_batch_with_valid_totp(self, tenant):
        user = JasminUserFactory()
        two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        first = two_factor_service.confirm_enrollment(
            user=user, code=_current_totp(device)
        )
        device.refresh_from_db()
        # ``confirm_enrollment`` burned this window's token (django-otp
        # persists ``last_t``); reset it so ``regenerate`` can verify in
        # the same window. Same rationale as ``_enrol``.
        device.last_t = -1
        device.save(update_fields=["last_t"])
        second = two_factor_service.regenerate_recovery_codes(
            user=user, code=_current_totp(device)
        )
        assert len(second) == 10
        assert set(first.recovery_codes).isdisjoint(set(second))

    def test_regenerate_rejects_recovery_code(self, tenant):
        """Recovery codes intentionally can't regenerate — that path
        would let a thief lock out the real owner."""
        user = JasminUserFactory()
        two_factor_service.start_enrollment(user=user, issuer="Jasmin")
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        result = two_factor_service.confirm_enrollment(
            user=user, code=_current_totp(device)
        )
        recovery = result.recovery_codes[0]
        with pytest.raises(TwoFactorInvalidCode):
            two_factor_service.regenerate_recovery_codes(user=user, code=recovery)


# --------------------------------------------------------------------------- #
# Service: challenge tokens                                                    #
# --------------------------------------------------------------------------- #


class TestChallengeToken:
    def test_issue_and_consume_happy_path(self, tenant):
        user = JasminUserFactory()
        token = two_factor_service.issue_challenge_token(
            user=user, tenant_schema=tenant.schema_name
        )
        resolved = two_factor_service.consume_challenge_token(
            challenge=token, tenant_schema=tenant.schema_name
        )
        assert resolved.pk == user.pk

    def test_wrong_tenant_rejected(self, tenant):
        user = JasminUserFactory()
        token = two_factor_service.issue_challenge_token(
            user=user, tenant_schema=tenant.schema_name
        )
        with pytest.raises(TwoFactorChallengeInvalid):
            two_factor_service.consume_challenge_token(
                challenge=token, tenant_schema="some_other_tenant"
            )

    def test_garbage_token_rejected(self, tenant):
        with pytest.raises(TwoFactorChallengeInvalid):
            two_factor_service.consume_challenge_token(
                challenge="not-a-jwt", tenant_schema=tenant.schema_name
            )


# --------------------------------------------------------------------------- #
# Service: role-required enrolment gate                                        #
# --------------------------------------------------------------------------- #


class TestRoleRequiresEnrolment:
    def test_empty_config_means_opt_in_for_everyone(self, tenant):
        user = JasminUserFactory(roles=["admin"])
        with patch.object(settings, "TWO_FACTOR_REQUIRED_ROLES", []):
            assert two_factor_service.role_requires_enrolment(user) is False

    def test_user_role_in_required_list_triggers_gate(self, tenant):
        user = JasminUserFactory(roles=["admin"])
        with patch.object(settings, "TWO_FACTOR_REQUIRED_ROLES", ["admin"]):
            assert two_factor_service.role_requires_enrolment(user) is True

    def test_user_role_not_in_required_list_passes(self, tenant):
        user = JasminUserFactory(roles=["member"])
        with patch.object(settings, "TWO_FACTOR_REQUIRED_ROLES", ["admin"]):
            assert two_factor_service.role_requires_enrolment(user) is False


# --------------------------------------------------------------------------- #
# HTTP integration                                                             #
# --------------------------------------------------------------------------- #


class TestLoginBranchesOn2FA:
    """The ``/login/`` view returns ONE of two shapes depending on
    whether the user has an active TOTP device."""

    def test_user_without_2fa_gets_full_login_payload(self, tenant):
        u = JasminUserFactory(email="no2fa@example.com")
        _set_password(u, "Z3rgRushIsScary!42")
        resp = APIClient().post(
            "/api/auth/login/",
            data={"email": "no2fa@example.com", "password": "Z3rgRushIsScary!42"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["access"]
        assert "requires_2fa" not in resp.data

    def test_user_with_2fa_gets_challenge_response(self, tenant):
        u = JasminUserFactory(email="has2fa@example.com")
        _set_password(u, "Z3rgRushIsScary!42")
        _enrol(u)
        resp = APIClient().post(
            "/api/auth/login/",
            data={"email": "has2fa@example.com", "password": "Z3rgRushIsScary!42"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {
            "requires_2fa": True,
            "challenge_token": resp.data["challenge_token"],
        }
        assert resp.data["challenge_token"]
        # No JWT issued yet.
        assert "access" not in resp.data


class TestVerifyEndpoint:
    def test_verify_with_valid_code_returns_full_payload(self, tenant):
        u = JasminUserFactory(email="verify@example.com")
        _set_password(u, "Z3rgRushIsScary!42")
        device = _enrol(u)
        login = APIClient().post(
            "/api/auth/login/",
            data={"email": "verify@example.com", "password": "Z3rgRushIsScary!42"},
            format="json",
        )
        challenge = login.data["challenge_token"]
        resp = APIClient().post(
            "/api/auth/two-factor/verify/",
            data={"challenge_token": challenge, "code": _current_totp(device)},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["access"]
        assert resp.data["user"]["email"] == "verify@example.com"

    def test_verify_with_bad_code_returns_400(self, tenant):
        u = JasminUserFactory(email="badcode@example.com")
        _set_password(u, "Z3rgRushIsScary!42")
        _enrol(u)
        login = APIClient().post(
            "/api/auth/login/",
            data={"email": "badcode@example.com", "password": "Z3rgRushIsScary!42"},
            format="json",
        )
        resp = APIClient().post(
            "/api/auth/two-factor/verify/",
            data={
                "challenge_token": login.data["challenge_token"],
                "code": "000000",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_verify_with_missing_challenge_returns_400(self, tenant):
        resp = APIClient().post(
            "/api/auth/two-factor/verify/",
            data={"code": "123456"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# --------------------------------------------------------------------------- #
# COR-23: role-mandated enrolment is not a login deadlock                      #
# --------------------------------------------------------------------------- #


class TestEnrolmentDeadlockFix:
    """A role-mandated-2FA user with no device used to be permanently locked
    out: login issued no session, but enroll-start/confirm needed one. Login
    now hands back a short-lived enrolment token those endpoints accept."""

    def test_enrolment_token_round_trip(self, tenant):
        user = JasminUserFactory(roles=["admin"], email="gated-rt@example.com")
        token = two_factor_service.issue_enrolment_token(
            user=user, tenant_schema=tenant.schema_name
        )
        resolved = two_factor_service.consume_enrolment_token(
            enrolment=token, tenant_schema=tenant.schema_name
        )
        assert resolved.id == user.id

    def test_enrolment_token_rejects_wrong_tenant(self, tenant):
        user = JasminUserFactory(roles=["admin"], email="gated-wt@example.com")
        token = two_factor_service.issue_enrolment_token(
            user=user, tenant_schema=tenant.schema_name
        )
        with pytest.raises(TwoFactorChallengeInvalid):
            two_factor_service.consume_enrolment_token(
                enrolment=token, tenant_schema="some_other_schema"
            )

    def test_gated_login_returns_token_and_enrolment_succeeds(self, tenant):
        with patch.object(settings, "TWO_FACTOR_REQUIRED_ROLES", ["admin"]):
            u = JasminUserFactory(roles=["admin"], email="gated@example.com")
            _set_password(u, "Z3rgRushIsScary!42")
            client = APIClient()

            login = client.post(
                "/api/auth/login/",
                data={"email": "gated@example.com", "password": "Z3rgRushIsScary!42"},
                format="json",
            )
            # Gated: NO JWT — but an enrolment token to break the deadlock.
            assert login.status_code == status.HTTP_403_FORBIDDEN
            assert login.data["code"] == "auth.two_factor.enrolment_required"
            assert "access" not in login.data
            token = login.data["details"]["enrolment_token"]
            assert token

            # enroll-start with ONLY the token (no session).
            start = APIClient().post(
                "/api/auth/two-factor/enroll-start/",
                data={"enrolment_token": token},
                format="json",
            )
            assert start.status_code == status.HTTP_200_OK
            assert start.data["provisioning_uri"]

            # enroll-confirm with the token + the new device's current code.
            device = TOTPDevice.objects.get(user=u, confirmed=False)
            confirm = APIClient().post(
                "/api/auth/two-factor/enroll-confirm/",
                data={"enrolment_token": token, "code": _current_totp(device)},
                format="json",
            )
            assert confirm.status_code == status.HTTP_200_OK
            assert confirm.data["recovery_codes"]
            assert TOTPDevice.objects.filter(user=u, confirmed=True).exists()

    def test_enroll_start_without_token_or_session_is_rejected(self, tenant):
        resp = APIClient().post(
            "/api/auth/two-factor/enroll-start/", data={}, format="json"
        )
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_voluntary_enrolment_with_session_still_works(self, tenant):
        """AllowAny didn't break the logged-in path: a user enrolling
        voluntarily from their profile (session, NO enrolment_token) still
        reaches enroll-start via _resolve_enrolling_user's session branch."""
        u = JasminUserFactory(email="voluntary@example.com")
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.post("/api/auth/two-factor/enroll-start/", data={}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["provisioning_uri"]


class TestTwoFactorCodeEndpointValidation:
    """Serializer-level 400s on the wired 2FA endpoints (blank/missing code) —
    distinct from the service-layer wrong-code 400. Assert the canonical body,
    not the (German-translated) DRF message."""

    def test_verify_blank_code_returns_400(self, tenant):
        resp = APIClient().post(
            "/api/auth/two-factor/verify/",
            data={"challenge_token": "anything", "code": ""},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "code" in resp.data["details"]

    def test_disable_blank_code_returns_400(self, tenant):
        u = JasminUserFactory()
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.post(
            "/api/auth/two-factor/disable/", data={"code": ""}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "code" in resp.data["details"]

    def test_regenerate_missing_code_returns_400(self, tenant):
        u = JasminUserFactory()
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.post(
            "/api/auth/two-factor/recovery-codes/regenerate/",
            data={},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "code" in resp.data["details"]

    def test_enroll_confirm_blank_code_returns_400(self, tenant):
        # Authenticate so ``_resolve_enrolling_user`` returns the session user
        # and is_valid is reached (an anon request without a token 401s first).
        u = JasminUserFactory()
        client = APIClient()
        client.force_authenticate(user=u)
        resp = client.post(
            "/api/auth/two-factor/enroll-confirm/", data={"code": ""}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "validation_error"
        assert "code" in resp.data["details"]
