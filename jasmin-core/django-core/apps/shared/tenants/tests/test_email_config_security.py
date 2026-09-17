"""Connection-security mapping + validation for ``TenantEmailConfig``.

The office UI presents a single "connection security" selector, but the model
keeps two mutually-exclusive booleans (``smtp_use_tls`` = STARTTLS,
``smtp_use_ssl`` = implicit SSL) so the long-standing ``smtp_use_tls`` field is
never removed (backward compatibility). These tests pin the boolean→Django
backend mapping and the "not both" guard.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.shared.tenants.errors import (
    SmtpHostNotAllowed,
    SmtpPortInvalid,
    SmtpTlsSslConflict,
)
from apps.shared.tenants.models import TenantEmailConfig
from apps.shared.tenants.serializers import TenantEmailConfigSerializer


@pytest.mark.django_db
class TestEmailConfigSecurity:
    def _create_email_config(self, tenant, **overrides) -> TenantEmailConfig:
        defaults = dict(
            tenant=tenant,
            smtp_host="smtp.example.org",
            smtp_port=587,
            from_email="noreply@example.org",
            from_name="Test Tenant",
            is_active=True,
        )
        defaults.update(overrides)
        return TenantEmailConfig.objects.create(**defaults)

    def test_backend_settings_starttls(self, tenant):
        backend_settings = self._create_email_config(
            tenant, smtp_use_tls=True, smtp_use_ssl=False
        ).get_backend_settings()
        assert backend_settings["EMAIL_USE_TLS"] is True
        assert backend_settings["EMAIL_USE_SSL"] is False

    def test_backend_settings_ssl(self, tenant):
        backend_settings = self._create_email_config(
            tenant, smtp_use_tls=False, smtp_use_ssl=True
        ).get_backend_settings()
        assert backend_settings["EMAIL_USE_TLS"] is False
        assert backend_settings["EMAIL_USE_SSL"] is True

    def test_backend_settings_none(self, tenant):
        backend_settings = self._create_email_config(
            tenant, smtp_use_tls=False, smtp_use_ssl=False
        ).get_backend_settings()
        assert backend_settings["EMAIL_USE_TLS"] is False
        assert backend_settings["EMAIL_USE_SSL"] is False

    def test_serializer_rejects_both_tls_and_ssl(self, tenant):
        # Django's SMTP backend raises if both are set — the serializer catches
        # it first, with a stable code the client can translate.
        config = self._create_email_config(
            tenant, smtp_use_tls=True, smtp_use_ssl=False
        )
        ser = TenantEmailConfigSerializer(
            instance=config,
            data={"smtp_use_tls": True, "smtp_use_ssl": True},
            partial=True,
        )

        with pytest.raises(SmtpTlsSslConflict) as exc_info:
            ser.is_valid(raise_exception=True)

        assert exc_info.value.code == "email_config.tls_ssl_conflict"
        assert exc_info.value.field == "smtp_use_ssl"

    def test_serializer_accepts_ssl_only(self, tenant):
        # Switching to SSL sends BOTH booleans (tls off, ssl on) — mirrors the
        # frontend selector, which never leaves both set.
        config = self._create_email_config(
            tenant, smtp_use_tls=True, smtp_use_ssl=False
        )
        ser = TenantEmailConfigSerializer(
            instance=config,
            data={"smtp_use_tls": False, "smtp_use_ssl": True},
            partial=True,
        )
        assert ser.is_valid(), ser.errors

    def test_serializer_partial_ssl_conflicts_with_stored_tls(self, tenant):
        # A PATCH that sets only ssl=True while the stored config still has
        # tls=True is rejected — the guard resolves the missing field from the
        # instance, so a half-update can't slip both-True past validation.
        config = self._create_email_config(
            tenant, smtp_use_tls=True, smtp_use_ssl=False
        )
        ser = TenantEmailConfigSerializer(
            instance=config, data={"smtp_use_ssl": True}, partial=True
        )

        with pytest.raises(SmtpTlsSslConflict):
            ser.is_valid(raise_exception=True)


@pytest.mark.django_db
class TestSmtpFieldErrorCodes:
    """Host and port refusals carry a stable code, not a DRF field map — the
    office UI can only translate a message it can identify."""

    def _serializer(self, tenant, data) -> TenantEmailConfigSerializer:
        config = TenantEmailConfig.objects.create(
            tenant=tenant,
            smtp_host="smtp.example.org",
            smtp_port=587,
            from_email="noreply@example.org",
            from_name="Test Tenant",
            is_active=True,
        )
        return TenantEmailConfigSerializer(instance=config, data=data, partial=True)

    @pytest.mark.parametrize("port", [0, 70000, -1])
    def test_a_port_outside_the_tcp_range_carries_its_code(self, tenant, port):
        ser = self._serializer(tenant, {"smtp_port": port})

        with pytest.raises(SmtpPortInvalid) as exc_info:
            ser.is_valid(raise_exception=True)

        assert exc_info.value.code == "email_config.smtp_port_invalid"
        assert exc_info.value.field == "smtp_port"

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_an_internal_host_carries_its_code(self, tenant):
        ser = self._serializer(tenant, {"smtp_host": "smtp.internal.test"})

        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 1, 6, "", ("10.1.2.3", 0))],
        ):
            with pytest.raises(SmtpHostNotAllowed) as exc_info:
                ser.is_valid(raise_exception=True)

        assert exc_info.value.code == "email_config.smtp_host_not_allowed"
        assert exc_info.value.field == "smtp_host"

    @override_settings(SMTP_ALLOW_PRIVATE_HOSTS=False)
    def test_a_public_host_is_accepted(self, tenant):
        ser = self._serializer(tenant, {"smtp_host": "smtp.example.test"})

        with patch(
            "apps.shared.smtp_host_validator.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 1, 6, "", ("93.184.216.34", 0))],
        ):
            assert ser.is_valid(), ser.errors
