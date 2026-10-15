"""The sign-in lockout: django-axes counts failed sign-ins per (email, client
IP), and with ``LOGIN_LOCKOUT_ENABLED`` (``AXES_LOCK_OUT_AT_FAILURE``) on, the
login, its 2FA step and step-up refuse a pair that has 5 of them.

pytest runs with DEBUG on, which switches axes off, so every case switches it
back on with ``override_settings`` — and the lockout with it, except where the
switch itself is under test.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import time_machine
import yaml
from axes.models import AccessAttempt
from axes.signals import user_locked_out
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import connection
from django.db.models import Sum
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_tenants.utils import schema_context
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts import tasks as axes_tasks
from apps.accounts.services import login_lockout, two_factor_service
from apps.commissioning.tests.factories import JasminUserFactory
from apps.shared.super_admin.models import SuperAdmin
from apps.shared.super_admin.views.auth_views import super_admin_login_view

pytestmark = pytest.mark.django_db

# This file lives at apps/accounts/tests/<file>, so the repository is five up.
REPO_ROOT = Path(__file__).resolve().parents[5]

EMAIL = "victim@example.com"
PASSWORD = "Z3rgRushIsScary!42"
WRONG = "Wrong-Horse-Battery!9"
NEW_PASSWORD = "Gl4cier-Mint-Harbor-97!q"
# APIClient sends REMOTE_ADDR 127.0.0.1 unless told otherwise.
OWN_IP = "127.0.0.1"
OTHER_IP = "198.51.100.23"

LOGIN = "/api/auth/login/"
STEP_UP = "/api/auth/step-up/"
VERIFY = "/api/auth/two-factor/verify/"
RESET_CONFIRM = "/api/auth/password-reset/confirm/"


@pytest.fixture
def lockout_on():
    with override_settings(AXES_ENABLED=True, AXES_LOCK_OUT_AT_FAILURE=True):
        yield


@pytest.fixture
def lockouts():
    """Every ``user_locked_out`` axes sends: what the operator alert hangs on."""
    seen: list[tuple[str | None, str | None]] = []

    def receiver(sender, request, username=None, ip_address=None, **kwargs):
        seen.append((username, ip_address))

    user_locked_out.connect(receiver, dispatch_uid="test-login-lockout", weak=False)
    yield seen
    user_locked_out.disconnect(dispatch_uid="test-login-lockout")


def _user(email: str = EMAIL):
    user = JasminUserFactory(email=email)
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    return user


def _session(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _login(client: APIClient, password: str, email: str = EMAIL):
    return client.post(LOGIN, {"email": email, "password": password}, format="json")


def _step_up(client: APIClient, password: str, totp_code: str | None = None):
    body = {"password": password}
    if totp_code is not None:
        body["totp_code"] = totp_code
    return client.post(STEP_UP, body, format="json")


def _verify(client: APIClient, challenge: str, code: str):
    return client.post(
        VERIFY, {"challenge_token": challenge, "code": code}, format="json"
    )


def _reset_password(client: APIClient, user):
    # The token hashes ``last_login``, which a sign-in in the test has moved.
    user.refresh_from_db()
    return client.post(
        RESET_CONFIRM,
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": PasswordResetTokenGenerator().make_token(user),
            "password": NEW_PASSWORD,
        },
        format="json",
    )


def _failures(email: str = EMAIL, ip: str | None = None) -> int:
    attempts = AccessAttempt.objects.filter(username=email)
    if ip is not None:
        attempts = attempts.filter(ip_address=ip)
    total = attempts.aggregate(total=Sum("failures_since_start"))["total"]
    return total or 0


def _run_burst_alert() -> MagicMock:
    """Run the burst alert once; return the ``mail_admins`` it would call."""
    axes_tasks._last_alerted.clear()
    try:
        with patch.object(axes_tasks, "mail_admins") as mail_admins:
            axes_tasks.alert_on_axes_bursts.call_local()
    finally:
        axes_tasks._last_alerted.clear()
    return mail_admins


def _current_code(device: TOTPDevice) -> str:
    return format(totp(device.bin_key, step=device.step, digits=device.digits), "06d")


def _wrong_code(device: TOTPDevice) -> str:
    """Every digit of the current code shifted: not this window's code."""
    return "".join(str((int(digit) + 5) % 10) for digit in _current_code(device))


def _enrol(user) -> TOTPDevice:
    two_factor_service.start_enrollment(user=user, issuer="Test")
    pending = TOTPDevice.objects.get(user=user, confirmed=False)
    two_factor_service.confirm_enrollment(user=user, code=_current_code(pending))
    device = TOTPDevice.objects.get(user=user, confirmed=True)
    # The confirmation spent this window's code; the tests sign in with it.
    device.last_t = -1
    device.save(update_fields=["last_t"])
    return device


class TestAxesUsername:
    @pytest.mark.parametrize(
        ("credentials", "expected"),
        [
            ({"username": " Foo@Example.COM "}, "foo@example.com"),
            ({"email": "Foo@Example.com", "password": "secret"}, "foo@example.com"),
            ({"username": "ſisı@Example.com"}, "sisi@example.com"),
            ({"username": "foo@STRAẞE.de"}, "foo@straße.de"),
            ({"username": "foo@straße.de"}, "foo@straße.de"),
            (None, None),
            ({}, None),
            ({"username": ""}, None),
            ({"username": "   "}, None),
            ({"username": ["foo@example.com"]}, None),
        ],
    )
    def test_the_key_is_the_address_in_one_case(self, credentials, expected):
        """Both names axes hands the address under — ``email`` from its
        backend's pre-check, ``username`` from ``user_login_failed`` — give
        one key, and so do the spellings the database's ``UPPER()`` folds
        together: ``ſ`` and ``s``, ``ı`` and ``i``, ``ẞ`` and ``ß``."""
        assert login_lockout.axes_username(None, credentials) == expected

    def test_the_key_fits_the_username_column(self):
        assert login_lockout.axes_username(None, {"username": "a" * 300}) == "a" * 255

    def test_every_letter_the_lookup_folds_into_ascii_keys_as_that_letter(self, tenant):
        """The account lookup is ``email__iexact``: ``UPPER()`` of both sides.
        Whatever letter this database upper-cases to an ASCII letter (``ı``
        and ``ſ`` at least) signs in as that letter, so it has to key as that
        letter too, or a spelling with it would get a lock of its own."""
        with connection.cursor() as cursor:
            # Every letter with a case mapping onto ASCII is in the Basic
            # Multilingual Plane; 55296-57343 are the surrogates.
            cursor.execute(
                "SELECT chr(code), upper(chr(code)) "
                "FROM generate_series(128, 65535) AS code "
                "WHERE code NOT BETWEEN 55296 AND 57343 "
                "AND ascii(upper(chr(code))) BETWEEN 65 AND 90"
            )
            folded_into_ascii = cursor.fetchall()

        assert {letter for letter, _ in folded_into_ascii} >= {"ı", "ſ"}
        for letter, ascii_letter in folded_into_ascii:
            address = f"{letter}@example.com"
            key = login_lockout.axes_username(None, {"username": address})
            assert key == f"{ascii_letter.lower()}@example.com"


@pytest.mark.usefixtures("lockout_on")
class TestLogin:
    def test_five_wrong_passwords_lock_out_the_right_one(self, tenant, lockouts):
        _user()
        client = APIClient()

        for _ in range(5):
            response = _login(client, WRONG)
            assert response.status_code == 400
            assert response.data["code"] == "auth.invalid_credentials"
        refused = _login(client, PASSWORD)

        assert refused.status_code == 429
        assert refused.data["code"] == "auth.account_locked"
        assert "access" not in refused.data
        # The refusal came before the password check, so it wasn't counted.
        assert _failures() == 5
        # One lock, one signal: the operator alert fires for the 5th failure.
        assert lockouts == [(EMAIL, OWN_IP)]

    def test_the_lock_holds_one_address_from_one_ip(self, tenant):
        _user()
        _user("other@example.com")
        client = APIClient()
        for _ in range(5):
            _login(client, WRONG)

        assert _login(client, PASSWORD).status_code == 429
        assert _login(APIClient(REMOTE_ADDR=OTHER_IP), PASSWORD).status_code == 200
        assert _login(client, PASSWORD, email="other@example.com").status_code == 200

    def test_case_variants_of_the_address_fill_one_bucket(self, tenant):
        user = _user("Casey.Case@Example.com")
        client = APIClient()
        for typed in ("casey.case@example.com", "CASEY.CASE@EXAMPLE.COM"):
            _login(client, WRONG, email=typed)
        # Step-up reports its failures under the address as stored.
        step_up = _session(user)
        for _ in range(3):
            assert _step_up(step_up, WRONG).status_code == 400

        assert _failures("casey.case@example.com") == 5
        refused = _login(client, PASSWORD, email="Casey.Case@Example.com")
        assert refused.status_code == 429
        assert refused.data["code"] == "auth.account_locked"

    def test_unicode_spellings_of_the_address_share_its_lock(self, tenant):
        """The database's ``UPPER()``, which the ``email__iexact`` lookup runs,
        maps ``ſ`` to ``S`` and ``ı`` to ``I``: ``ſisı@example.com`` signs in
        as sisi@example.com. Each such spelling counts toward that address's
        lock, and none of them gets past it."""
        user = _user("sisi@example.com")
        client = APIClient()
        signed_in = _login(client, PASSWORD, email="ſisı@example.com")
        assert signed_in.status_code == 200
        assert signed_in.data["user"]["email"] == "sisi@example.com"

        for typed in (
            "ſisi@example.com",
            "sisı@example.com",
            "ſiſı@example.com",
            "SISI@EXAMPLE.COM",
        ):
            assert _login(client, WRONG, email=typed).status_code == 400
        assert _step_up(_session(user), WRONG).status_code == 400

        assert _failures("sisi@example.com") == 5
        for typed in ("ſisı@example.com", "sisi@example.com"):
            refused = _login(client, PASSWORD, email=typed)
            assert refused.status_code == 429
            assert refused.data["code"] == "auth.account_locked"

    def test_an_address_longer_than_the_key_column_still_counts(self, tenant):
        """An address may run to 320 characters, ``AccessAttempt.username``
        holds 255: the key is cut to fit, and the failure is counted like any
        other instead of failing the request."""
        typed = (
            "a" * 64 + "@" + ".".join(["b" * 63, "c" * 63, "d" * 63, "e" * 40]) + ".com"
        )

        response = _login(APIClient(), WRONG, email=typed)

        assert response.status_code == 400
        assert response.data["code"] == "auth.invalid_credentials"
        assert _failures(typed[:255]) == 1

    def test_the_lock_ends_an_hour_after_the_failure_that_set_it(self, tenant):
        _user()
        start = datetime.datetime(2026, 9, 7, 12, 0, tzinfo=datetime.UTC)
        with time_machine.travel(start, tick=False) as traveller:
            client = APIClient()
            for _ in range(5):
                _login(client, WRONG)

            traveller.move_to(start + datetime.timedelta(minutes=50))
            assert _login(client, PASSWORD).status_code == 429

            # Had the refused attempt at 50 minutes counted, the lock would
            # now run until 110 minutes.
            traveller.move_to(start + datetime.timedelta(minutes=61))
            assert _login(client, PASSWORD).status_code == 200

    def test_axes_own_refusal_is_not_counted_either(self, tenant):
        """axes' backend refuses a locked pair before any password check by
        itself too — for a request that slipped past the views' check. That
        refusal mustn't count as one more failure either."""
        _user()
        client = APIClient()
        for _ in range(5):
            _login(client, WRONG)
        request = Request(APIRequestFactory().post(LOGIN))

        assert authenticate(request, username=EMAIL, password=PASSWORD) is None
        assert _failures() == 5

    def test_a_successful_sign_in_clears_the_failures_of_its_own_ip(self, tenant):
        _user()
        client, elsewhere = APIClient(), APIClient(REMOTE_ADDR=OTHER_IP)
        for _ in range(5):
            _login(elsewhere, WRONG)
        for _ in range(4):
            _login(client, WRONG)

        assert _login(client, PASSWORD).status_code == 200
        assert _failures(ip=OWN_IP) == 0
        # Someone else's guessing elsewhere stays counted, and locked out.
        assert _failures(ip=OTHER_IP) == 5
        assert _login(elsewhere, PASSWORD).status_code == 429

        # Carried over, the earlier four would lock at the next failure.
        for _ in range(4):
            _login(client, WRONG)
        assert _login(client, PASSWORD).status_code == 200


@pytest.mark.usefixtures("lockout_on")
class TestTwoFactorStep:
    def test_wrong_codes_lock_and_a_locked_challenge_is_refused(self, tenant):
        user = _user()
        device = _enrol(user)
        client = APIClient()
        challenge = _login(client, PASSWORD).data["challenge_token"]

        for _ in range(5):
            response = _verify(client, challenge, _wrong_code(device))
            assert response.data["code"] == "auth.two_factor.invalid_code"
        # The same challenge, still valid, now with the right code.
        refused = _verify(client, challenge, _current_code(device))

        assert refused.status_code == 429
        assert refused.data["code"] == "auth.account_locked"
        assert "access" not in refused.data
        assert _failures() == 5
        assert _login(client, PASSWORD).status_code == 429

    def test_a_right_password_waiting_for_its_code_clears_nothing(self, tenant):
        user = _user()
        _enrol(user)
        client = APIClient()
        for _ in range(4):
            _login(client, WRONG)

        assert _login(client, PASSWORD).data["requires_2fa"] is True
        assert _failures() == 4
        _login(client, WRONG)
        assert _login(client, PASSWORD).status_code == 429

    def test_a_verified_code_clears_the_failures(self, tenant):
        user = _user()
        device = _enrol(user)
        client = APIClient()
        for _ in range(4):
            _login(client, WRONG)
        challenge = _login(client, PASSWORD).data["challenge_token"]

        assert _verify(client, challenge, _current_code(device)).status_code == 200
        assert _failures() == 0


@pytest.mark.usefixtures("lockout_on")
class TestStepUp:
    def test_wrong_passwords_lock_and_a_locked_step_up_is_refused(self, tenant):
        user = _user()
        client = _session(user)
        for _ in range(5):
            assert _step_up(client, WRONG).status_code == 400

        refused = _step_up(client, PASSWORD)

        assert refused.status_code == 429
        assert refused.data["code"] == "auth.account_locked"
        assert _failures() == 5
        assert _login(APIClient(), PASSWORD).status_code == 429

    @override_settings(STEP_UP_REQUIRES_TOTP=True)
    def test_wrong_authenticator_codes_count_too(self, tenant):
        user = _user()
        device = _enrol(user)
        client = _session(user)

        for _ in range(5):
            response = _step_up(client, PASSWORD, _wrong_code(device))
            assert response.data["code"] == "auth.two_factor.invalid_code"

        assert _failures() == 5
        assert _login(APIClient(), PASSWORD).status_code == 429

    def test_a_successful_step_up_clears_the_failures(self, tenant):
        client = _session(_user())
        for _ in range(4):
            _step_up(client, WRONG)

        assert _step_up(client, PASSWORD).status_code == 200
        assert _failures() == 0


@pytest.mark.usefixtures("lockout_on")
class TestPasswordReset:
    def test_a_completed_reset_lifts_the_lock_from_every_ip(self, tenant):
        user = _user()
        here, there = APIClient(), APIClient(REMOTE_ADDR=OTHER_IP)
        for _ in range(5):
            _login(here, WRONG)
            _login(there, WRONG)
        assert _login(here, PASSWORD).status_code == 429
        assert _login(there, PASSWORD).status_code == 429

        reset = _reset_password(here, user)

        assert reset.status_code == 200, reset.data
        assert _login(here, NEW_PASSWORD).status_code == 200
        assert _login(there, NEW_PASSWORD).status_code == 200


class TestSwitchedOff:
    def test_the_lockout_ships_switched_off(self):
        if "LOGIN_LOCKOUT_ENABLED" in os.environ:
            pytest.skip("LOGIN_LOCKOUT_ENABLED is set in this environment")
        assert settings.AXES_LOCK_OUT_AT_FAILURE is False

    def test_compose_hands_the_switch_to_the_backend_containers(self):
        compose = REPO_ROOT / "docker-compose.yml"
        if not compose.is_file():
            pytest.skip("docker-compose.yml is not in this checkout")
        services = yaml.safe_load(compose.read_text())["services"]

        for name in ("backend", "huey"):
            environment = services[name]["environment"]
            assert environment["LOGIN_LOCKOUT_ENABLED"] == (
                "${LOGIN_LOCKOUT_ENABLED:-False}"
            )

    @override_settings(AXES_ENABLED=True, AXES_LOCK_OUT_AT_FAILURE=False)
    def test_failures_are_recorded_by_address_but_nothing_locks(self, tenant, lockouts):
        user = _user()
        client = APIClient()
        for _ in range(7):
            assert _login(client, WRONG).status_code == 400

        assert list(
            AccessAttempt.objects.values_list(
                "username", "ip_address", "failures_since_start"
            )
        ) == [(EMAIL, OWN_IP, 7)]
        assert _login(client, PASSWORD).status_code == 200

        step_up = _session(user)
        for _ in range(6):
            assert _step_up(step_up, WRONG).status_code == 400
        assert _step_up(step_up, PASSWORD).status_code == 200
        # Nothing locked, so axes never asked for the operator alert.
        assert lockouts == []

    @override_settings(AXES_ENABLED=True, AXES_LOCK_OUT_AT_FAILURE=False)
    def test_nothing_clears_the_failures_for_the_burst_alert(self, tenant):
        """Off, there is no lock to lift, and the burst alert is what reports
        guessing: a sign-in, a step-up and a password reset leave the
        failures, so a run of wrong passwords that ended in the right one
        still reaches the alert."""
        user = _user()
        client = APIClient()
        for _ in range(6):
            _login(client, WRONG)

        assert _login(client, PASSWORD).status_code == 200
        assert _step_up(_session(user), PASSWORD).status_code == 200
        assert _reset_password(client, user).status_code == 200

        assert _failures(ip=OWN_IP) == 6
        mail_admins = _run_burst_alert()
        mail_admins.assert_called_once()
        assert OWN_IP in mail_admins.call_args.args[1]

    @override_settings(AXES_ENABLED=False, AXES_LOCK_OUT_AT_FAILURE=True)
    def test_with_axes_off_nothing_is_recorded_or_locked(self, tenant):
        _user()
        client = APIClient()
        for _ in range(6):
            _login(client, WRONG)

        assert _login(client, PASSWORD).status_code == 200
        assert not AccessAttempt.objects.exists()


@pytest.mark.usefixtures("lockout_on")
class TestPublicSchema:
    def test_the_lockout_leaves_the_public_schema_alone(self, tenant):
        """axes has no tables on the public schema; a lookup there would fail
        with a ProgrammingError."""
        request = Request(APIRequestFactory().post("/api/super-admin/auth/login/"))
        with schema_context("public"):
            login_lockout.refuse_if_locked(request, "root@example.com")
            login_lockout.clear_failures(request, "root@example.com")
            login_lockout.clear_all_failures("root@example.com")

    def test_the_super_admin_login_is_untouched(self, tenant):
        email = "lockout-root@example.com"
        factory = APIRequestFactory()
        with schema_context("public"):
            admin, _ = SuperAdmin.objects.get_or_create(
                email=email, defaults={"first_name": "Root", "last_name": "Admin"}
            )
            admin.is_active = True
            admin.set_password(PASSWORD)
            admin.save()

            wrong = super_admin_login_view(
                factory.post(LOGIN, {"email": email, "password": WRONG}, format="json")
            )
            right = super_admin_login_view(
                factory.post(
                    LOGIN, {"email": email, "password": PASSWORD}, format="json"
                )
            )

        assert wrong.status_code == 400
        assert wrong.data["code"] == "super_admin.invalid_credentials"
        assert right.status_code == 200
        assert not AccessAttempt.objects.exists()
