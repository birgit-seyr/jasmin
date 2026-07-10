"""Tests for `apps.payments.services.BillingRunService` (create_run + export).

Covers:
    - Charge eligibility filtering (status, due_date, payment_method, mandate)
    - Successful create + export flow
    - pain.008 XML format pinning lives in test_billing_run_pain008.py
    - Error paths (no eligible charges, missing creditor info, double export)
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine

from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SubscriptionFactory,
)
from apps.payments.constants import (
    BillingRunStatus,
    ChargeStatus,
    PaymentMethodOptions,
)
from apps.payments.errors import (
    BillingRunInvalidCollectionDate,
    BillingRunInvalidPeriod,
    BillingRunMixedCurrency,
    BillingRunNotDraft,
    NoEligibleCharges,
    NoValidSepaMandates,
    SepaExportInvalid,
)
from apps.payments.models import BillingProfile, ChargeSchedule
from apps.payments.services import BillingRunService


@pytest.fixture(autouse=True)
def _frozen_today():
    """Freeze "today" to 2026-02-01 for the whole module.

    The suite pins fixed 2026 dates (e.g. ``collection_date=2026-03-05``) that are
    now in the past relative to the real wall clock. The ``collection_date >=
    today`` guards in ``create_run`` / ``export`` (RUN-2 / RUN-4) therefore need a
    deterministic "today" earlier than every collection_date used here.
    """
    with time_machine.travel("2026-02-01", tick=False):
        yield


def _make_planned_charge(
    member,
    subscription,
    *,
    due_date=datetime.date(2026, 2, 1),
    amount=Decimal("25.00"),
):
    return ChargeSchedule.objects.create(
        member=member,
        subscription=subscription,
        period_start=due_date,
        period_end=due_date + datetime.timedelta(days=27),
        due_date=due_date,
        expected_amount=amount,
        currency="EUR",
        description="Subscription Feb 2026",
        status=ChargeStatus.PLANNED,
    )


# ---------------------------------------------------------------------------
# create_run
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateRun:
    def test_bundles_eligible_charges(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        c1 = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 1)
        )
        c2 = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 15)
        )

        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )

        assert run.status == BillingRunStatus.DRAFT
        assert run.charge_count == 2
        assert run.total_amount == Decimal("50.00")
        assert run.msg_id.startswith("BR-")
        c1.refresh_from_db()
        c2.refresh_from_db()
        assert c1.billing_run_id == run.pk
        assert c1.end_to_end_id != ""
        assert len(c1.end_to_end_id) <= 35

    def test_rate_limit_refuses_run_over_cap(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        """The SEPA charge-generation quota gates create_run — a compromised
        office account can't mint an unbounded number of direct-debit batches."""
        from apps.shared.tenants.errors import ActionRateLimitExceeded
        from apps.shared.tenants.models import RateLimitedAction

        # Platform-owned override (connection.tenant is this fixture object, so
        # the in-memory value is what the guard reads). Tighten to 1 run/week.
        tenant.action_rate_limit_overrides = {
            str(RateLimitedAction.SEPA_CHARGE_GENERATION): {
                "weekly": 1,
                "per_minute": 100,
            }
        }

        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 1))
        BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )

        # A second run (with a fresh eligible charge) is refused by the cap.
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 15))
        with pytest.raises(ActionRateLimitExceeded) as exc:
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
            )
        assert exc.value.details["action"] == str(
            RateLimitedAction.SEPA_CHARGE_GENERATION
        )

    def test_does_not_reload_each_charge(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        """Bundling must not fire a per-charge immutability-reload SELECT. The
        only SELECT against the charge table should be the single eligible
        select_for_update — regardless of how many charges bundle."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for day in (1, 8, 15):
            _make_planned_charge(
                member, subscription, due_date=datetime.date(2026, 2, day)
            )

        with CaptureQueriesContext(connection) as ctx:
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
            )

        charge_selects = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith("SELECT")
            and "chargeschedule" in q["sql"].lower()
        ]
        # Only the single eligible select_for_update. The bundling uses
        # bulk_update (not a per-charge save()), so there is no per-charge
        # immutability reload and no per-charge auditlog old-row fetch — the
        # old per-row save() path added several SELECTs per bundled charge.
        assert len(charge_selects) == 1, charge_selects

    def test_skips_charges_outside_period(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        in_range = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )
        out_of_range = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 4, 5)
        )

        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )

        in_range.refresh_from_db()
        out_of_range.refresh_from_db()
        assert in_range.billing_run_id == run.pk
        assert out_of_range.billing_run_id is None

    def test_skips_non_planned_charges(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        already_issued = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )
        already_issued.status = ChargeStatus.ISSUED
        already_issued.save(allow_immutable_change=True)

        with pytest.raises(
            NoEligibleCharges, match="No PLANNED charges with a positive amount"
        ):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
            )

    def test_skips_members_without_active_sepa_profile(
        self, tenant, tenant_settings, subscription, member
    ):
        # No billing_profile fixture here → member has no profile at all.
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        # No active SEPA profile → the eligibility join excludes the charge.
        with pytest.raises(NoEligibleCharges):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
            )

    def test_period_end_before_start_raises(self, tenant, tenant_settings):
        with pytest.raises(BillingRunInvalidPeriod, match="period_end"):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 28),
                period_end=datetime.date(2026, 2, 1),
                collection_date=datetime.date(2026, 3, 5),
            )


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExport:
    def _setup_run(self, member, subscription):
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        return BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )

    def test_export_flips_run_and_charges(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        run = self._setup_run(member, subscription)
        BillingRunService.export(run)

        run.refresh_from_db()
        assert run.status == BillingRunStatus.EXPORTED
        assert run.sepa_xml_export.name != ""
        # The artifact is now ``.xml`` (pain.008.001.02) instead of ``.csv``.
        assert run.sepa_xml_export.name.endswith(".xml")

        for c in run.charges.all():
            assert c.status == ChargeStatus.ISSUED

        billing_profile.refresh_from_db()
        # First-use-at gets stamped on first export.
        assert billing_profile.sepa_mandate_first_use_at is not None

    def test_double_export_raises(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        run = self._setup_run(member, subscription)
        BillingRunService.export(run)
        with pytest.raises(BillingRunNotDraft, match="cannot re-export"):
            BillingRunService.export(run)

    def test_export_rejects_non_eur_charge(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        """pain.008 is EUR-only: a charge stamped with a non-EUR currency must
        fail loudly (SepaExportInvalid) rather than be silently direct-debited
        as the same numeric amount in EUR."""
        run = self._setup_run(member, subscription)
        run.charges.update(currency="USD")
        with pytest.raises(SepaExportInvalid, match="not EUR"):
            BillingRunService.export(run)
        # The run stays DRAFT — the failed export rolled back, no file produced.
        run.refresh_from_db()
        assert run.status == BillingRunStatus.DRAFT


# ---------------------------------------------------------------------------
# BANK_TRANSFER runs: never produce a SEPA Direct Debit file, and only
# bundle bank-transfer charges (no cross-contamination with SEPA charges).
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBankTransferRun:
    @staticmethod
    def _bank_transfer_profile(member):
        return BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
            is_active=True,
        )

    def test_export_produces_no_sepa_file(
        self, tenant, tenant_settings, subscription, member
    ):
        self._bank_transfer_profile(member)
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))

        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
            payment_method=PaymentMethodOptions.BANK_TRANSFER,
        )
        assert run.charge_count == 1

        BillingRunService.export(run)
        run.refresh_from_db()

        assert run.status == BillingRunStatus.EXPORTED
        # No SEPA Direct Debit file for a bank-transfer run.
        assert not run.sepa_xml_export
        for charge in run.charges.all():
            assert charge.status == ChargeStatus.ISSUED

    def test_run_excludes_sepa_member_charge(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # ``billing_profile`` is a SEPA profile for ``member``; their charge
        # must NOT be swept into a BANK_TRANSFER run. With only that charge
        # present, the run has nothing eligible.
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))

        with pytest.raises(NoEligibleCharges):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
                payment_method=PaymentMethodOptions.BANK_TRANSFER,
            )


# ---------------------------------------------------------------------------
# Billing-audit fixes: collection-date guards (RUN-2 / RUN-4), export
# re-validation of mandates (RUN-1 / TXN-2), run-total recompute (TXN-3).
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateRunCollectionDate:
    def test_rejects_past_collection_date(self, tenant, tenant_settings):
        # RUN-4: today is frozen at 2026-02-01; a collection_date before today is
        # rejected by the service itself (not only the create view), so a
        # non-view caller can't mint a DRAFT doomed to fail at the bank.
        with pytest.raises(BillingRunInvalidCollectionDate, match="in the past"):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 1, 1),
                period_end=datetime.date(2026, 1, 31),
                collection_date=datetime.date(2026, 1, 15),
            )


@pytest.mark.django_db
class TestExportGuards:
    def _setup_run(self, member, subscription):
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        return BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )

    def test_export_rejects_deactivated_mandate(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # RUN-1 / TXN-2: the mandate is revoked (is_active=False) AFTER the DRAFT
        # run was built. Export must refuse rather than debit a revoked mandate.
        run = self._setup_run(member, subscription)
        billing_profile.is_active = False
        billing_profile.save()
        with pytest.raises(SepaExportInvalid, match="no longer SEPA-ready"):
            BillingRunService.export(run)
        run.refresh_from_db()
        assert run.status == BillingRunStatus.DRAFT  # rolled back, not exported

    def test_export_rejects_switch_to_bank_transfer(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # RUN-1 / TXN-2: member switched away from SEPA after create_run.
        run = self._setup_run(member, subscription)
        billing_profile.payment_method = PaymentMethodOptions.BANK_TRANSFER
        billing_profile.save()
        with pytest.raises(SepaExportInvalid, match="no longer SEPA-ready"):
            BillingRunService.export(run)

    def test_export_rejects_past_collection_date(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # RUN-2: collection_date (2026-03-05) was valid at create (today
        # 2026-02-01) but the operator exports after it has passed.
        run = self._setup_run(member, subscription)
        with time_machine.travel("2026-04-01", tick=False):
            with pytest.raises(BillingRunInvalidCollectionDate, match="in the past"):
                BillingRunService.export(run)
        run.refresh_from_db()
        assert run.status == BillingRunStatus.DRAFT

    def test_export_recomputes_totals_after_unbundle(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # TXN-3: a bundled charge is unbundled before export; the run's snapshot
        # total/count must be re-derived from the charges actually issued.
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 15))
        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )
        assert run.charge_count == 2
        assert run.total_amount == Decimal("50.00")

        unbundled = run.charges.first()
        unbundled.billing_run = None
        unbundled.save()

        BillingRunService.export(run)
        run.refresh_from_db()
        assert run.charge_count == 1
        assert run.total_amount == Decimal("25.00")


@pytest.mark.django_db
class TestLowSeverityAuditFixes:
    """MON-3 (single-currency runs) + RUN-5 (no future mandate-signed date)."""

    def test_create_run_rejects_mixed_currency(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # MON-3: two eligible charges in different currencies → a meaningless
        # cross-currency total, rejected before the run is created.
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        usd = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 15)
        )
        usd.currency = "USD"
        usd.save()
        with pytest.raises(BillingRunMixedCurrency, match="multiple currencies"):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
            )

    def test_export_rejects_future_mandate_signed_date(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # RUN-5: mandate signed in the future (today frozen at 2026-02-01).
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))
        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )
        billing_profile.sepa_mandate_signed_at = datetime.date(2026, 6, 1)
        billing_profile.save()
        with pytest.raises(SepaExportInvalid, match="in the future"):
            BillingRunService.export(run)
        run.refresh_from_db()
        assert run.status == BillingRunStatus.DRAFT


# ---------------------------------------------------------------------------
# SEPA-readiness drop in create_run (TEST-3)
# ---------------------------------------------------------------------------


def _not_ready_sepa_profile(member):
    """An ACTIVE SEPA Direct Debit profile that is NOT ``is_sepa_ready`` — it
    passes the eligibility SQL join (is_active + SEPA payment_method) but fails
    the in-Python ``is_sepa_ready`` filter.

    A valid active SEPA profile can't be *created* unsigned (``clean()`` requires
    the signature), so we create a valid one and blank the signature out of band
    via ``.update()`` (bypassing clean). That models exactly the defense-in-depth
    case the ``is_sepa_ready`` filter guards: a mandate cleared / revoked after
    the profile went active, which the SQL join alone would not catch."""
    profile = BillingProfile.objects.create(
        member=member,
        payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
        iban="DE89370400440532013000",
        account_holder=f"{member.first_name} {member.last_name}",
        sepa_mandate_signed_at=datetime.date(2026, 1, 1),
        is_active=True,
    )
    BillingProfile.objects.filter(pk=profile.pk).update(sepa_mandate_signed_at=None)
    profile.refresh_from_db()
    assert profile.is_sepa_ready is False
    return profile


@pytest.mark.django_db
class TestCreateRunSepaReadiness:
    """The ``is_sepa_ready`` list-comprehension drop (a mandate half-entered:
    active SEPA profile, no signature) is otherwise untested — the existing
    coverage is a member with NO profile (the SQL join), not one whose active
    profile lacks a signed mandate."""

    def test_all_not_ready_raises_no_valid_sepa_mandates(
        self, tenant, tenant_settings, subscription, member
    ):
        _not_ready_sepa_profile(member)
        _make_planned_charge(member, subscription, due_date=datetime.date(2026, 2, 5))

        # The active-profile SQL join includes the charge, then is_sepa_ready
        # drops it → nothing bundleable → NoValidSepaMandates (NOT
        # NoEligibleCharges, which is the no-profile-at-all case).
        with pytest.raises(NoValidSepaMandates):
            BillingRunService.create_run(
                period_start=datetime.date(2026, 2, 1),
                period_end=datetime.date(2026, 2, 28),
                collection_date=datetime.date(2026, 3, 5),
            )

    def test_mixed_bundles_ready_and_leaves_not_ready_planned(
        self, tenant, tenant_settings, billing_profile, subscription, member
    ):
        # Ready member (fixtures give a fully-valid SEPA profile) + a charge.
        ready_charge = _make_planned_charge(
            member, subscription, due_date=datetime.date(2026, 2, 5)
        )

        # Second member with an active-but-unsigned SEPA profile + a charge.
        other_member = MemberFactory(user=JasminUserFactory(roles=["member"]))
        _not_ready_sepa_profile(other_member)
        # default_delivery_station_day=None so this second subscription doesn't
        # build another day_number=2 SharesDeliveryDay (global overlap scope).
        other_subscription = SubscriptionFactory(
            member=other_member,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
            quantity=1,
            price_per_delivery=Decimal("10.00"),
            payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
            default_delivery_station_day=None,
        )
        not_ready_charge = _make_planned_charge(
            other_member, other_subscription, due_date=datetime.date(2026, 2, 5)
        )

        run = BillingRunService.create_run(
            period_start=datetime.date(2026, 2, 1),
            period_end=datetime.date(2026, 2, 28),
            collection_date=datetime.date(2026, 3, 5),
        )

        ready_charge.refresh_from_db()
        not_ready_charge.refresh_from_db()
        # Exactly the ready charge is bundled; the not-ready one stays PLANNED
        # and unattached (no operator surface — the intended silent skip).
        assert ready_charge.billing_run_id == run.pk
        assert not_ready_charge.billing_run_id is None
        assert not_ready_charge.status == ChargeStatus.PLANNED
