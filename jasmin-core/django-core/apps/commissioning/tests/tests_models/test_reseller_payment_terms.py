"""Tests for the per-reseller payment-term resolution helpers.

The model exposes two helpers:
  * ``Reseller.get_payment_terms_days()`` → int
  * ``Reseller.get_early_payment_discount()`` → ``(percent, days)``

Resolution order (per CLAUDE.md "tenant default falls back from per-row"):
  1. Per-reseller value (NULL = not set)
  2. Tenant default from current ``TenantSettings``
  3. Hard-coded safety value (14 days, no Skonto)
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.tests.factories import ResellerFactory
from apps.shared.tenants.models import TenantSettings


@pytest.fixture()
def settings_row(tenant):
    """A current TenantSettings row for the test tenant.

    The shared ``tenant`` fixture doesn't auto-create one, so tests that
    exercise the per-reseller → tenant-default fallback need this.
    """
    return TenantSettings.objects.create(tenant=tenant, valid_from=timezone.now())


@pytest.mark.django_db
class TestGetPaymentTermsDays:
    def test_returns_reseller_override_when_set(self, tenant, settings_row):
        reseller = ResellerFactory(payment_terms_in_days=21)
        # Tenant default (14) is ignored when the reseller has its own.
        assert reseller.get_payment_terms_days() == 21

    def test_falls_back_to_tenant_default_when_reseller_value_is_null(
        self, tenant, settings_row
    ):
        settings_row.payment_terms_reseller_in_days = 30
        settings_row.save(update_fields=["payment_terms_reseller_in_days"])

        reseller = ResellerFactory(payment_terms_in_days=None)
        assert reseller.get_payment_terms_days() == 30

    def test_falls_back_to_14_when_no_tenant_settings(self, tenant):
        # No ``settings_row`` fixture — the helper hits its hard-coded
        # safety value because ``get_current_settings`` returns None.
        reseller = ResellerFactory(payment_terms_in_days=None)
        assert reseller.get_payment_terms_days() == 14


@pytest.mark.django_db
class TestGetEarlyPaymentDiscount:
    def test_returns_reseller_override_when_set(self, tenant, settings_row):
        reseller = ResellerFactory(
            early_payment_discount_percent=Decimal("2.00"),
            early_payment_discount_days=7,
        )
        pct, days = reseller.get_early_payment_discount()
        assert pct == Decimal("2.00")
        assert days == 7

    def test_falls_back_to_tenant_default_when_both_reseller_fields_null(
        self, tenant, settings_row
    ):
        settings_row.early_payment_discount_percent = Decimal("1.50")
        settings_row.early_payment_discount_days = 10
        settings_row.save(
            update_fields=[
                "early_payment_discount_percent",
                "early_payment_discount_days",
            ]
        )

        reseller = ResellerFactory(
            early_payment_discount_percent=None,
            early_payment_discount_days=None,
        )
        pct, days = reseller.get_early_payment_discount()
        assert pct == Decimal("1.50")
        assert days == 10

    def test_explicit_reseller_zero_percent_overrides_tenant_default(
        self, tenant, settings_row
    ):
        """A reseller with an explicitly-cleared Skonto must NOT inherit
        the tenant's offer — otherwise the office can never opt a single
        reseller out of a tenant-wide discount."""
        settings_row.early_payment_discount_percent = Decimal("3.00")
        settings_row.early_payment_discount_days = 5
        settings_row.save(
            update_fields=[
                "early_payment_discount_percent",
                "early_payment_discount_days",
            ]
        )

        reseller = ResellerFactory(
            early_payment_discount_percent=Decimal("0.00"),
            early_payment_discount_days=0,
        )
        pct, days = reseller.get_early_payment_discount()
        # Reseller's explicit 0 wins over tenant's 3%.
        assert pct == Decimal("0.00")
        assert days == 0

    def test_returns_none_pair_when_neither_reseller_nor_tenant_have_skonto(
        self, tenant, settings_row
    ):
        # Default TenantSettings has NULL Skonto fields.
        reseller = ResellerFactory(
            early_payment_discount_percent=None,
            early_payment_discount_days=None,
        )
        pct, days = reseller.get_early_payment_discount()
        assert pct is None
        assert days is None
