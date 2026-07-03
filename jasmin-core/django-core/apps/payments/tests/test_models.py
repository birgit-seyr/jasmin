"""Unit tests for `apps.payments.models`.

Covers:
    - BillingProfile.clean() validation for SEPA mandates
    - BillingProfile.is_sepa_ready property
    - ChargeSchedule immutability rules in `save()`
    - ChargeSchedule.is_open property
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.payments.constants import ChargeStatus, PaymentMethodOptions
from apps.payments.models import BillingProfile, ChargeSchedule


# ---------------------------------------------------------------------------
# BillingProfile
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBillingProfileValidation:
    def test_active_sepa_requires_iban(self, tenant, member):
        with pytest.raises(ValidationError) as exc:
            BillingProfile.objects.create(
                member=member,
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                account_holder="Foo",
                sepa_mandate_reference="MND-1",
                sepa_mandate_signed_at=datetime.date(2026, 1, 1),
                is_active=True,
                # iban omitted
            )
        assert "iban" in exc.value.message_dict

    def test_active_sepa_requires_account_holder(self, tenant, member):
        with pytest.raises(ValidationError) as exc:
            BillingProfile.objects.create(
                member=member,
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                iban="DE89370400440532013000",
                sepa_mandate_reference="MND-1",
                sepa_mandate_signed_at=datetime.date(2026, 1, 1),
                is_active=True,
            )
        assert "account_holder" in exc.value.message_dict

    def test_active_sepa_auto_assigns_reference_but_requires_signed_at(
        self, tenant, member
    ):
        # The Mandatsreferenz is now auto-generated on save, so it's never a
        # missing-field error; the office still must record the signed date.
        with pytest.raises(ValidationError) as exc:
            BillingProfile.objects.create(
                member=member,
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                iban="DE89370400440532013000",
                account_holder="Foo",
                is_active=True,
            )
        assert "sepa_mandate_signed_at" in exc.value.message_dict
        assert "sepa_mandate_reference" not in exc.value.message_dict

    def test_sepa_mandate_reference_auto_generated(self, tenant, member):
        bp = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban="DE89370400440532013000",
            account_holder="Foo",
            sepa_mandate_signed_at=datetime.date(2026, 1, 1),
            is_active=True,
        )
        assert bp.sepa_mandate_reference
        assert bp.sepa_mandate_reference.startswith("MND-")
        assert bp.is_sepa_ready  # ref + iban + signed_at all present now

    def test_inactive_sepa_skips_validation(self, tenant, member):
        # is_active=False bypasses the "SEPA fields required" check.
        bp = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            is_active=False,
        )
        assert bp.pk is not None

    def test_bank_transfer_skips_sepa_validation(self, tenant, member):
        bp = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
            is_active=True,
        )
        assert bp.pk is not None


@pytest.mark.django_db
class TestBillingProfileIsSepaReady:
    def test_full_profile_is_ready(self, tenant, billing_profile):
        assert billing_profile.is_sepa_ready is True

    def test_inactive_is_not_ready(self, tenant, billing_profile):
        billing_profile.is_active = False
        billing_profile.save()
        assert billing_profile.is_sepa_ready is False

    def test_bank_transfer_is_not_ready(self, tenant, member):
        bp = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
            is_active=True,
        )
        assert bp.is_sepa_ready is False


# ---------------------------------------------------------------------------
# ChargeSchedule immutability
# ---------------------------------------------------------------------------
def _make_charge(member, subscription, status=ChargeStatus.PLANNED):
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=datetime.date(2026, 1, 1),
        period_end=datetime.date(2026, 1, 31),
        due_date=datetime.date(2026, 1, 1),
        expected_amount=Decimal("10.00"),
        currency="EUR",
        status=status,
    )


@pytest.mark.django_db
class TestChargeScheduleImmutability:
    def test_planned_amount_is_mutable(self, tenant, member, subscription):
        c = _make_charge(member, subscription)
        c.expected_amount = Decimal("12.34")
        c.save()
        c.refresh_from_db()
        assert c.expected_amount == Decimal("12.34")

    def test_issued_amount_change_raises(self, tenant, member, subscription):
        c = _make_charge(member, subscription, status=ChargeStatus.ISSUED)
        c.expected_amount = Decimal("99.99")
        with pytest.raises(ValidationError):
            c.save()

    def test_issued_status_only_change_is_allowed(self, tenant, member, subscription):
        c = _make_charge(member, subscription, status=ChargeStatus.ISSUED)
        c.status = ChargeStatus.PAID
        # Status-only change is fine — none of the frozen fields changed.
        c.save()
        c.refresh_from_db()
        assert c.status == ChargeStatus.PAID

    def test_allow_immutable_change_bypasses(self, tenant, member, subscription):
        c = _make_charge(member, subscription, status=ChargeStatus.ISSUED)
        c.expected_amount = Decimal("77.77")
        c.save(allow_immutable_change=True)
        c.refresh_from_db()
        assert c.expected_amount == Decimal("77.77")

    def test_create_issues_no_guard_select(self, tenant, member, subscription):
        """A fresh create() must NOT run the immutability-guard SELECT.

        The guard only matters for UPDATEs, but JasminModel assigns the
        CharField PK in Python at construction (default=generate_jasmin_id),
        so ``self.pk`` is truthy even on a brand-new row. Without the
        ``_state.adding`` gate, every create() fired a wasted SELECT for a
        row that doesn't exist yet (doubling the create-path query count in
        bulk paths like regenerate_all). This locks a create to a single
        statement against the table: the INSERT, no guard SELECT.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        table = ChargeSchedule._meta.db_table

        def _table_stmts(ctx, verb: str) -> int:
            needle = f'"{table}"'
            return sum(
                1
                for q in ctx.captured_queries
                if needle in q["sql"].lower()
                and q["sql"].lstrip().lower().startswith(verb)
            )

        with CaptureQueriesContext(connection) as ctx:
            _make_charge(member, subscription)

        assert _table_stmts(ctx, "select") == 0, (
            "create() issued a guard SELECT on the ChargeSchedule table — "
            "the immutability check must be gated on _state.adding so it "
            "runs only for genuine UPDATEs."
        )
        assert _table_stmts(ctx, "insert") == 1
        # The flip side — that a genuine UPDATE still runs the guard — is
        # covered behaviorally by test_issued_amount_change_raises (it can
        # only raise if the guard SELECT found the locked row), so we don't
        # re-assert the update query shape here (it also picks up auditlog's
        # own change-diff SELECT, which is noise for this lock).


@pytest.mark.django_db
class TestChargeScheduleIsOpen:
    @pytest.mark.parametrize(
        "status,expected",
        [
            (ChargeStatus.PLANNED, True),
            (ChargeStatus.ISSUED, True),
            (ChargeStatus.PARTIAL, True),
            (ChargeStatus.PAID, False),
            (ChargeStatus.FAILED, False),
            (ChargeStatus.WAIVED, False),
        ],
    )
    def test_is_open(self, tenant, member, subscription, status, expected):
        c = _make_charge(member, subscription, status=status)
        assert c.is_open is expected
