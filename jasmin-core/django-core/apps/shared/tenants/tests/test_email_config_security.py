"""Connection-security mapping + validation for ``TenantEmailConfig``.

The office UI presents a single "connection security" selector, but the model
keeps two mutually-exclusive booleans (``smtp_use_tls`` = STARTTLS,
``smtp_use_ssl`` = implicit SSL) so the long-standing ``smtp_use_tls`` field is
never removed (backward compatibility). These tests pin the boolean→Django
backend mapping and the "not both" guard.
"""

from __future__ import annotations

import pytest

from apps.shared.tenants.models import TenantEmailConfig
from apps.shared.tenants.serializers import TenantEmailConfigSerializer


@pytest.mark.django_db
class TestEmailConfigSecurity:
    def _cfg(self, tenant, **over) -> TenantEmailConfig:
        defaults = dict(
            tenant=tenant,
            smtp_host="smtp.example.org",
            smtp_port=587,
            from_email="noreply@example.org",
            from_name="Test Tenant",
            is_active=True,
        )
        defaults.update(over)
        return TenantEmailConfig.objects.create(**defaults)

    def test_backend_settings_starttls(self, tenant):
        s = self._cfg(
            tenant, smtp_use_tls=True, smtp_use_ssl=False
        ).get_backend_settings()
        assert s["EMAIL_USE_TLS"] is True
        assert s["EMAIL_USE_SSL"] is False

    def test_backend_settings_ssl(self, tenant):
        s = self._cfg(
            tenant, smtp_use_tls=False, smtp_use_ssl=True
        ).get_backend_settings()
        assert s["EMAIL_USE_TLS"] is False
        assert s["EMAIL_USE_SSL"] is True

    def test_backend_settings_none(self, tenant):
        s = self._cfg(
            tenant, smtp_use_tls=False, smtp_use_ssl=False
        ).get_backend_settings()
        assert s["EMAIL_USE_TLS"] is False
        assert s["EMAIL_USE_SSL"] is False

    def test_serializer_rejects_both_tls_and_ssl(self, tenant):
        # Django's SMTP backend raises if both are set — the serializer catches
        # it first with a field error.
        cfg = self._cfg(tenant, smtp_use_tls=True, smtp_use_ssl=False)
        ser = TenantEmailConfigSerializer(
            instance=cfg,
            data={"smtp_use_tls": True, "smtp_use_ssl": True},
            partial=True,
        )
        assert not ser.is_valid()
        assert "smtp_use_ssl" in ser.errors

    def test_serializer_accepts_ssl_only(self, tenant):
        # Switching to SSL sends BOTH booleans (tls off, ssl on) — mirrors the
        # frontend selector, which never leaves both set.
        cfg = self._cfg(tenant, smtp_use_tls=True, smtp_use_ssl=False)
        ser = TenantEmailConfigSerializer(
            instance=cfg,
            data={"smtp_use_tls": False, "smtp_use_ssl": True},
            partial=True,
        )
        assert ser.is_valid(), ser.errors

    def test_serializer_partial_ssl_conflicts_with_stored_tls(self, tenant):
        # A PATCH that sets only ssl=True while the stored config still has
        # tls=True is rejected — the guard resolves the missing field from the
        # instance, so a half-update can't slip both-True past validation.
        cfg = self._cfg(tenant, smtp_use_tls=True, smtp_use_ssl=False)
        ser = TenantEmailConfigSerializer(
            instance=cfg, data={"smtp_use_ssl": True}, partial=True
        )
        assert not ser.is_valid()
        assert "smtp_use_ssl" in ser.errors
