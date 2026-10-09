"""``normalize_ibans``: rewrites stored billing-profile IBANs into their
canonical form (no whitespace, upper-case) and reports the ones that are not
valid IBANs instead of touching them.
"""

from __future__ import annotations

from io import StringIO

import pytest
from auditlog.models import LogEntry
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.commissioning.tests.factories import MemberFactory
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile

UNNORMALISED = "de89 3704 0044 0532 0130 00"
NORMALISED = "DE89370400440532013000"
# Wrong check digits: no normalising makes this a valid IBAN.
INVALID = "de00 3704 0044 0532 0130 00"


def _profile(iban: str, member_number: int) -> BillingProfile:
    profile = BillingProfile.objects.create(
        member=MemberFactory(member_number=member_number),
        payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
        iban="CH9300762011623852957",
        account_holder="Ada Lovelace",
        sepa_mandate_signed_at="2020-01-01",
    )
    # Written past the model's validation, the way rows stored before the
    # import normalised its IBANs can look.
    BillingProfile.objects.filter(pk=profile.pk).update(iban=iban)
    profile.refresh_from_db()
    return profile


def _audit_entries(profile: BillingProfile) -> int:
    return LogEntry.objects.get_for_object(profile).count()


def _run(**options) -> str:
    out = StringIO()
    call_command("normalize_ibans", stdout=out, **options)
    return out.getvalue()


@pytest.mark.django_db
class TestNormalizeIbans:
    def test_fixes_an_unnormalised_iban(self, tenant):
        profile = _profile(UNNORMALISED, 6001)

        output = _run(tenant=tenant.schema_name)

        profile.refresh_from_db()
        assert profile.iban == NORMALISED
        assert f"Tenant {tenant.schema_name}" in output
        assert "1 normalised" in output

    def test_change_is_audit_logged(self, tenant):
        profile = _profile(UNNORMALISED, 6002)
        before = _audit_entries(profile)

        _run(tenant=tenant.schema_name)

        assert _audit_entries(profile) == before + 1

    def test_skips_and_reports_an_invalid_iban(self, tenant):
        profile = _profile(INVALID, 6003)

        output = _run(tenant=tenant.schema_name)

        profile.refresh_from_db()
        assert profile.iban == INVALID
        assert "1 invalid" in output
        assert "6003" in output
        # The report names the member, never the account itself.
        assert INVALID not in output
        assert "DE00370400440532013000" not in output

    def test_dry_run_changes_nothing(self, tenant):
        profile = _profile(UNNORMALISED, 6004)

        output = _run(tenant=tenant.schema_name, dry_run=True)

        profile.refresh_from_db()
        assert profile.iban == UNNORMALISED
        assert "1 to normalise" in output

    def test_second_run_changes_nothing(self, tenant):
        profile = _profile(UNNORMALISED, 6005)
        _run(tenant=tenant.schema_name)
        writes_after_first_run = _audit_entries(profile)

        output = _run(tenant=tenant.schema_name)

        profile.refresh_from_db()
        assert profile.iban == NORMALISED
        assert _audit_entries(profile) == writes_after_first_run
        assert "0 normalised" in output

    def test_leaves_a_normalised_iban_alone(self, tenant):
        profile = _profile(NORMALISED, 6006)
        writes_before = _audit_entries(profile)

        _run(tenant=tenant.schema_name)

        assert _audit_entries(profile) == writes_before

    def test_every_active_tenant_by_default(self, tenant):
        profile = _profile(UNNORMALISED, 6007)

        output = _run()

        profile.refresh_from_db()
        assert profile.iban == NORMALISED
        assert f"Tenant {tenant.schema_name}" in output

    def test_unknown_tenant_is_refused(self, tenant):
        with pytest.raises(CommandError):
            _run(tenant="no_such_schema")
