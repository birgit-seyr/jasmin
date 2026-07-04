"""Unit tests for `apps.payments.services.ChargeScheduleService`.

The generator is the heart of the billing subsystem. We cover:
    - period iteration (cycle math)
    - EXACT_PER_PERIOD vs SMOOTHED strategies
    - joker exclusion driven by TenantSettings
    - idempotency (re-running doesn't duplicate; respects locked rows)
    - empty / missing-price edge cases
    - due_date placement from `billing_due_day_of_month`
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal

import pytest

from apps.commissioning.models import ShareDelivery
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    PaymentCycleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.payments.constants import (
    BillingRunStatus,
    ChargeStatus,
    PaymentMethodOptions,
)
from apps.payments.models import BillingRun, ChargeSchedule
from apps.payments.services import ChargeScheduleService, _iter_cycle_periods
from apps.shared.tenants.models import TenantSettings


# ---------------------------------------------------------------------------
# _iter_cycle_periods (pure helper)
# ---------------------------------------------------------------------------
class TestIterCyclePeriods:
    def test_monthly_one_year(self):
        periods = list(
            _iter_cycle_periods(
                datetime.date(2026, 1, 1), datetime.date(2026, 12, 31), "MONTHLY"
            )
        )
        assert len(periods) == 12
        assert periods[0].start == datetime.date(2026, 1, 1)
        # First period ends one day before the next starts.
        assert periods[1].start == datetime.date(2026, 2, 1)
        assert periods[0].end == datetime.date(2026, 1, 31)
        assert periods[-1].end == datetime.date(2026, 12, 31)

    def test_weekly(self):
        periods = list(
            _iter_cycle_periods(
                datetime.date(2026, 1, 5), datetime.date(2026, 1, 25), "WEEKLY"
            )
        )
        assert len(periods) == 3
        assert periods[0].end == datetime.date(2026, 1, 11)

    def test_quarterly(self):
        periods = list(
            _iter_cycle_periods(
                datetime.date(2026, 1, 1), datetime.date(2026, 12, 31), "QUARTERLY"
            )
        )
        assert len(periods) == 4

    def test_last_period_clamped_to_valid_until(self):
        periods = list(
            _iter_cycle_periods(
                datetime.date(2026, 1, 1), datetime.date(2026, 1, 20), "MONTHLY"
            )
        )
        assert len(periods) == 1
        assert periods[0].end == datetime.date(2026, 1, 20)

    def test_day31_start_recovers_month_end(self):
        # CHG-3: a day-31 anchor must snap BACK to month-end when the month allows
        # (Mar/May 31), not ratchet down to the 28th for the rest of the term as
        # the old incremental-re-add did.
        periods = list(
            _iter_cycle_periods(
                datetime.date(2026, 1, 31), datetime.date(2026, 5, 31), "MONTHLY"
            )
        )
        starts = [p.start for p in periods]
        assert starts == [
            datetime.date(2026, 1, 31),
            datetime.date(2026, 2, 28),  # Feb has no 31
            datetime.date(2026, 3, 31),  # recovered (old code: 03-28)
            datetime.date(2026, 4, 30),  # Apr has no 31
            datetime.date(2026, 5, 31),  # recovered (old code: 05-28)
        ]
        # Contiguous: each period ends the day before the next begins.
        for cur, nxt in zip(periods, periods[1:], strict=False):
            assert cur.end == nxt.start - datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_deliveries_for_subscription(subscription, weeks, *, joker_weeks=()):
    """Create one ShareDelivery per (year, week) tuple for the subscription.

    Reuses the SharesDeliveryDay already created via the subscription fixture
    (overlap_unique_fields=("day_number",) makes a second one with the same
    day_number raise a ValidationError).
    Pass week numbers in `joker_weeks` to mark those rows as `joker_taken`.
    """
    delivery_day = subscription.default_delivery_station_day.delivery_day
    deliveries = []
    for year, week in weeks:
        share = ShareFactory(
            year=year,
            delivery_week=week,
            delivery_day=delivery_day,
            share_type_variation=subscription.share_type_variation,
        )
        sd = ShareDeliveryFactory(
            share=share,
            subscription=subscription,
            delivery_station_day=subscription.default_delivery_station_day,
            joker_taken=(year, week) in joker_weeks,
        )
        deliveries.append(sd)
    return deliveries


# ---------------------------------------------------------------------------
# regenerate_for_subscription — EXACT_PER_PERIOD
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExactStrategy:
    def test_each_delivery_billed_in_its_period(
        self, tenant, tenant_settings, subscription
    ):
        # Subscription valid_from = 2026-01-05 (Mon). Monthly periods are
        # anchored to that date: P0 = 01-05 → 02-04, P1 = 02-05 → 03-04, ...
        # ISO weeks (Wed delivery): w2=Jan 7, w3=Jan 14, w4=Jan 21 (all in P0),
        # w7=Feb 11 (in P1).
        _make_deliveries_for_subscription(
            subscription,
            [(2026, 2), (2026, 3), (2026, 4), (2026, 7)],
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription).order_by(
            "period_start"
        )
        # 12 monthly periods are always created (whole subscription term).
        assert charges.count() == 12

        jan = charges.first()
        feb = charges.all()[1]
        # 3 deliveries × 10.00 × qty 1
        assert jan.expected_amount == Decimal("30.00")
        assert feb.expected_amount == Decimal("10.00")
        # Empty months bill zero, not skipped.
        assert charges.last().expected_amount == Decimal("0.00")

    def test_failed_period_under_exact_is_flagged_not_silently_dropped(
        self, tenant, tenant_settings, subscription
    ):
        """BIZ-4: a FAILED (bank-returned) charge under EXACT is neither
        re-billed nor absorbed into other periods, so the owed amount would
        vanish silently. Until the reconciliation endpoint exists, regenerate
        surfaces it as an operator-actionable error and never creates a
        duplicate row (the (subscription, period_start) unique constraint)."""
        from unittest.mock import patch

        _make_deliveries_for_subscription(subscription, [(2026, 2), (2026, 3)])
        ChargeScheduleService.regenerate_for_subscription(subscription)

        # Simulate the future reconciliation path marking a charge FAILED — no
        # production writer sets FAILED today.
        failed = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        failed.status = ChargeStatus.FAILED
        failed.save(update_fields=["status"])

        with patch("apps.payments.services.logger") as mock_logger:
            ChargeScheduleService.regenerate_for_subscription(subscription)

        assert any(
            "FAILED charge for period" in call.args[0]
            for call in mock_logger.error.call_args_list
        )
        # The FAILED row is preserved; no duplicate PLANNED row for its period.
        assert (
            ChargeSchedule.objects.filter(
                subscription=subscription, period_start=failed.period_start
            ).count()
            == 1
        )

    def test_due_day_drives_due_date(self, tenant, tenant_settings, subscription):
        tenant_settings.billing_due_day_of_month = 15
        tenant_settings.save()

        ChargeScheduleService.regenerate_for_subscription(subscription)

        for c in ChargeSchedule.objects.filter(subscription=subscription):
            assert c.due_date.day == 15

    def test_due_day_capped_at_28(self, tenant, tenant_settings, subscription):
        # Even if a tenant managed to set 31, the helper caps at 28.
        tenant_settings.billing_due_day_of_month = 31
        tenant_settings.save(update_fields=["billing_due_day_of_month"])
        # bypass clean() to confirm services.py defends itself

        ChargeScheduleService.regenerate_for_subscription(subscription)
        charges = list(
            ChargeSchedule.objects.filter(subscription=subscription).order_by(
                "period_start"
            )
        )
        for c in charges:
            # Capped at 28 — never 29/30/31 — and always inside its own period.
            assert c.due_date.day <= 28
            assert c.period_start <= c.due_date <= c.period_end
        # Every full-length monthly period lands exactly on the 28th; only the
        # final short period (…-12-27) clamps its 28th back to the period end.
        assert all(c.due_date.day == 28 for c in charges[:-1])
        assert charges[-1].due_date == datetime.date(2026, 12, 27)


# ---------------------------------------------------------------------------
# regenerate_for_subscription — SMOOTHED
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSmoothedStrategy:
    def test_total_split_evenly(self, tenant, tenant_settings, subscription):
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()

        # 12 deliveries × 10€ = 120€ total → 12 monthly cycles → 10€/cycle
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        assert charges.count() == 12
        amounts = {c.expected_amount for c in charges}
        assert amounts == {Decimal("10.00")}

    def test_uneven_total_sums_exactly_to_term_total(
        self, tenant, tenant_settings, subscription
    ):
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()

        # 5 deliveries × 10€ = 50€ smoothed over 12 monthly cycles. 50/12 is
        # inexact, so the per-cycle amounts are allocated (largest remainder)
        # to sum EXACTLY to 50.00 — no drift over the term. The old uniform
        # 4.17/cycle over-charged 0.04 (12 × 4.17 = 50.04).
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 7)]
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)
        charges = ChargeSchedule.objects.filter(subscription=subscription)
        amounts = [c.expected_amount for c in charges]

        assert len(amounts) == 12
        # The whole point: the multiset sums to the true total, not 50.04.
        assert sum(amounts) == Decimal("50.00")
        # Each cycle is a clean 2dp amount differing by at most one cent:
        # 8 cycles at 4.17 + 4 cycles at 4.16 = 50.00.
        assert set(amounts) <= {Decimal("4.16"), Decimal("4.17")}
        assert amounts.count(Decimal("4.17")) == 8
        assert amounts.count(Decimal("4.16")) == 4

    def test_remaining_split_over_unlocked_after_some_issued(
        self, tenant, tenant_settings, subscription
    ):
        """Once some periods are ISSUED, SMOOTHED must split only the REMAINING
        amount over the still-unlocked periods, so sum(all charges) stays equal
        to the term total. The old code split the FULL recomputed total across
        ALL periods, so the unlocked share plus the kept locked amounts
        over-/under-collected the difference."""
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()

        # 12 deliveries × 10€ = 120€ → 10€/period across 12 monthly periods.
        deliveries = _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )
        ChargeScheduleService.regenerate_for_subscription(subscription)

        # Lock (ISSUE) the first two periods at 10.00 each (20€ collected).
        charges = list(
            ChargeSchedule.objects.filter(subscription=subscription).order_by(
                "period_start"
            )
        )
        for c in charges[:2]:
            c.status = ChargeStatus.ISSUED
            c.save(allow_immutable_change=True)

        # Two deliveries drop out → new term total = 10 × 10 = 100€.
        ChargeScheduleService.regenerate_for_subscription(
            subscription, deliveries=deliveries[:10]
        )

        all_charges = ChargeSchedule.objects.filter(subscription=subscription)
        # The invariant SMOOTHED exists to hold: total billed == term total.
        assert sum(c.expected_amount for c in all_charges) == Decimal("100.00")
        issued = all_charges.filter(status=ChargeStatus.ISSUED)
        assert sum(c.expected_amount for c in issued) == Decimal("20.00")
        # Remaining 80€ smoothed over the 10 still-unlocked periods → 8.00 each.
        planned = all_charges.filter(status=ChargeStatus.PLANNED)
        assert planned.count() == 10
        assert {c.expected_amount for c in planned} == {Decimal("8.00")}

    def test_overcollected_smoothed_never_creates_negative_charges(
        self, tenant, tenant_settings, subscription, caplog
    ):
        """If the locked (ISSUED) periods already collected MORE than the
        recomputed term total — later deliveries dropped after early periods
        were issued — the still-unlocked periods bill 0, never a NEGATIVE
        charge (which a SEPA pain.008 can't carry; the bank rejects the batch).
        The over-collection is a refund owed back out-of-band — and MEM-4
        requires it to surface as an operator-actionable WARNING, not silently."""
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()

        # 12 deliveries × 10€ = 120€ → 10€/period across 12 periods.
        deliveries = _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )
        ChargeScheduleService.regenerate_for_subscription(subscription)

        # Issue the first two periods (20€ locked).
        for c in list(
            ChargeSchedule.objects.filter(subscription=subscription).order_by(
                "period_start"
            )
        )[:2]:
            c.status = ChargeStatus.ISSUED
            c.save(allow_immutable_change=True)

        # Collapse to a single delivery → new term total = 10€ < 20€ locked.
        # The apps.payments logger sets propagate=False, so caplog's root handler
        # never sees it — attach caplog's handler to the logger directly.
        payments_logger = logging.getLogger("apps.payments.services")
        payments_logger.addHandler(caplog.handler)
        try:
            ChargeScheduleService.regenerate_for_subscription(
                subscription, deliveries=deliveries[:1]
            )
        finally:
            payments_logger.removeHandler(caplog.handler)

        all_charges = ChargeSchedule.objects.filter(subscription=subscription)
        # No negative charge anywhere.
        assert all(c.expected_amount >= Decimal("0.00") for c in all_charges)
        # The unlocked periods clamp to 0 rather than refunding via a negative.
        planned = all_charges.filter(status=ChargeStatus.PLANNED)
        assert {c.expected_amount for c in planned} == {Decimal("0.00")}
        # Issued amounts untouched; total never goes below what was collected.
        assert sum(c.expected_amount for c in all_charges) == Decimal("20.00")
        # MEM-4: the over-collection is logged (10€ owed back), not swallowed.
        assert any(
            "over-collection" in r.message for r in caplog.records
        ), "expected a SMOOTHED over-collection WARNING"


# ---------------------------------------------------------------------------
# Solidarity pricing → charge materialization seam
#
# A member-chosen below-reference solidarity price is snapshotted verbatim into
# ``Subscription.price_per_delivery`` by the subscribe path; the generator reads
# it directly (no branch distinguishing a solidarity price from an office-set
# one). These pin that the chosen 8.00/delivery flows through to
# ``expected_amount`` unmodified — a regression dropping/rounding it during
# materialization would otherwise pass CI (every other test prices at 10.00).
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSolidarityPriceMaterialization:
    def test_exact_uses_chosen_solidarity_price(
        self, tenant, tenant_settings, subscription
    ):
        # 8.00/delivery (below the 10.00 reference), 3 deliveries in P0 (Jan).
        subscription.price_per_delivery = Decimal("8.00")
        subscription.save(update_fields=["price_per_delivery"])
        _make_deliveries_for_subscription(
            subscription, [(2026, 2), (2026, 3), (2026, 4)]
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)

        jan = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        # 3 deliveries × 8.00 × qty 1 — the chosen solidarity price, not 10.00.
        assert jan.expected_amount == Decimal("24.00")

    def test_smoothed_term_total_uses_chosen_solidarity_price(
        self, tenant, tenant_settings, subscription
    ):
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()

        # 12 deliveries × 8.00 = 96.00 smoothed over 12 monthly cycles → 8.00 each.
        subscription.price_per_delivery = Decimal("8.00")
        subscription.save(update_fields=["price_per_delivery"])
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        assert charges.count() == 12
        # The SMOOTHED invariant: the term total is the chosen price × deliveries
        # (96.00 at 8.00/delivery), not the 120.00 the reference price would give.
        assert sum(c.expected_amount for c in charges) == Decimal("96.00")
        assert {c.expected_amount for c in charges} == {Decimal("8.00")}


# ---------------------------------------------------------------------------
# Joker handling
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestJokerHandling:
    def test_jokers_excluded_by_default(self, tenant, tenant_settings, subscription):
        # tenant_settings.bills_joker_deliveries defaults to False
        _make_deliveries_for_subscription(
            subscription,
            [(2026, 2), (2026, 3), (2026, 4)],
            joker_weeks={(2026, 3)},  # one is a joker
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)

        jan = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        # Only 2 of 3 January deliveries count → 20€
        assert jan.expected_amount == Decimal("20.00")

    def test_jokers_included_when_setting_enabled(
        self, tenant, tenant_settings, subscription
    ):
        tenant_settings.bills_joker_deliveries = True
        tenant_settings.save()

        _make_deliveries_for_subscription(
            subscription,
            [(2026, 2), (2026, 3), (2026, 4)],
            joker_weeks={(2026, 3)},
        )

        ChargeScheduleService.regenerate_for_subscription(subscription)

        jan = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        assert jan.expected_amount == Decimal("30.00")


# ---------------------------------------------------------------------------
# Idempotency + locked rows
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestIdempotency:
    def test_rerun_produces_same_count(self, tenant, tenant_settings, subscription):
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 6)]
        )

        first = ChargeScheduleService.regenerate_for_subscription(subscription)
        second = ChargeScheduleService.regenerate_for_subscription(subscription)
        assert first == second
        assert ChargeSchedule.objects.filter(subscription=subscription).count() == 12

    def test_issued_rows_are_preserved(self, tenant, tenant_settings, subscription):
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 6)]
        )
        ChargeScheduleService.regenerate_for_subscription(subscription)

        # Lock the January charge by flipping it to ISSUED with a custom amount.
        jan = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        jan.expected_amount = Decimal("99.99")
        jan.status = ChargeStatus.ISSUED
        jan.save(allow_immutable_change=True)

        ChargeScheduleService.regenerate_for_subscription(subscription)

        jan.refresh_from_db()
        # Untouched.
        assert jan.expected_amount == Decimal("99.99")
        assert jan.status == ChargeStatus.ISSUED


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEdgeCases:
    def test_no_valid_from_returns_zero(self, tenant, tenant_settings, subscription):
        # The DB requires valid_from NOT NULL, so simulate the guard branch by
        # blanking the attribute in-memory only (don't .save()).
        subscription.valid_from = None
        n = ChargeScheduleService.regenerate_for_subscription(subscription)
        assert n == 0
        assert ChargeSchedule.objects.filter(subscription=subscription).count() == 0

    def test_waiting_list_subscription_is_not_billed(
        self, tenant, tenant_settings, subscription
    ):
        # BL-10: a waiting-list subscription must get NO billable charges — the
        # single-subscription path (confirm/materialize) must apply the same
        # on_waiting_list=False exclusion the bulk regenerate_all path does, or a
        # not-yet-committed sub silently enters the SEPA run.
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 8)]
        )
        subscription.on_waiting_list = True
        subscription.save()

        n = ChargeScheduleService.regenerate_for_subscription(subscription)

        assert n == 0
        assert not ChargeSchedule.objects.filter(subscription=subscription).exists()

    def test_no_price_produces_zero_amount_charges(
        self, tenant, tenant_settings, subscription
    ):
        subscription.price_per_delivery = None
        subscription.save()
        _make_deliveries_for_subscription(subscription, [(2026, 2)])

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        assert charges.count() == 12
        assert all(c.expected_amount == Decimal("0.00") for c in charges)

    def test_no_deliveries_yields_zero_charges_in_exact(
        self, tenant, tenant_settings, subscription
    ):
        ChargeScheduleService.regenerate_for_subscription(subscription)
        charges = ChargeSchedule.objects.filter(subscription=subscription)
        assert charges.count() == 12
        assert all(c.expected_amount == Decimal("0.00") for c in charges)

    def test_no_tenant_settings_uses_safe_defaults(self, tenant, subscription):
        # Deliberately do NOT request the `tenant_settings` fixture.
        # Service should fall back to EXACT / no jokers / due day 1.
        _make_deliveries_for_subscription(subscription, [(2026, 2)])
        ChargeScheduleService.regenerate_for_subscription(subscription)
        charges = ChargeSchedule.objects.filter(subscription=subscription)
        assert charges.count() == 12
        # Due day 1 (default) precedes every period (periods start on the 5th),
        # so each due date clamps forward to its own period start.
        assert all(c.due_date == c.period_start for c in charges)


# ---------------------------------------------------------------------------
# regenerate_for_subscription — TXN-1: never drop a charge already bundled
# into a BillingRun.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegenerateProtectsBundledCharges:
    def _bundle(self, charge) -> BillingRun:
        """Attach ``charge`` to a fresh DRAFT run, leaving it PLANNED — exactly
        the state ``create_run`` produces before ``export`` flips it to ISSUED."""
        run = BillingRun.objects.create(
            period_start=charge.period_start,
            period_end=charge.period_end,
            collection_date=charge.period_end + datetime.timedelta(days=5),
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            status=BillingRunStatus.DRAFT,
            total_amount=charge.expected_amount,
            charge_count=1,
            msg_id="BR-TEST-TXN1",
        )
        charge.billing_run = run
        charge.save()
        return run

    def test_bundled_planned_charge_survives_regenerate(
        self, tenant, tenant_settings, subscription
    ):
        # TXN-1: a PLANNED charge already bundled into a DRAFT run must not be
        # deleted + recreated by a later regenerate (which would silently drop
        # the bundled charge and let a fresh PLANNED row be swept into a SECOND
        # run → double-charge).
        _make_deliveries_for_subscription(
            subscription, [(2026, 2), (2026, 3), (2026, 4), (2026, 7)]
        )
        ChargeScheduleService.regenerate_for_subscription(subscription)
        bundled = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        run = self._bundle(bundled)
        bundled_pk, bundled_period = bundled.pk, bundled.period_start

        ChargeScheduleService.regenerate_for_subscription(subscription)

        # The bundled charge is untouched (same pk, still attached to the run).
        survived = ChargeSchedule.objects.filter(pk=bundled_pk).first()
        assert survived is not None
        assert survived.billing_run_id == run.pk
        # And NO duplicate PLANNED row was recreated for that period.
        assert (
            ChargeSchedule.objects.filter(
                subscription=subscription, period_start=bundled_period
            ).count()
            == 1
        )

    def test_smoothed_does_not_rebill_bundled_amount(
        self, tenant, tenant_settings, subscription
    ):
        # MON-1 / TXN-1: under SMOOTHED, a bundled PLANNED charge counts as
        # committed — the remaining periods must split the term total MINUS the
        # bundled amount, never re-bill it.
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )  # 12 × 10€ = 120€ over 12 cycles → 10€/cycle
        ChargeScheduleService.regenerate_for_subscription(subscription)
        bundled = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        self._bundle(bundled)

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        # Total across ALL rows still equals the term total (120€): the bundled
        # 10€ + 11 unlocked cycles summing to 110€. Nothing re-billed twice.
        assert sum(c.expected_amount for c in charges) == Decimal("120.00")
        assert charges.count() == 12

    def test_waived_period_is_forgiven_not_respread(
        self, tenant, tenant_settings, subscription
    ):
        # MON-1 review fix: a WAIVED period is a deliberate forgiveness. Under
        # SMOOTHED the remaining periods must keep their normal share and the
        # member's collectable (PLANNED) total must DROP by the waived amount —
        # the waiver must NOT be re-spread across the other periods (which would
        # claw it back, making the member pay the full term anyway).
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )  # 12 × 10€ = 120€ over 12 cycles → 10€/cycle
        ChargeScheduleService.regenerate_for_subscription(subscription)

        # Waive one period (goodwill); its 10€ amount stays on the row.
        waived = (
            ChargeSchedule.objects.filter(subscription=subscription)
            .order_by("period_start")
            .first()
        )
        waived.status = ChargeStatus.WAIVED
        waived.save(allow_immutable_change=True)

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        planned = charges.filter(status=ChargeStatus.PLANNED)
        waived_total = sum(
            c.expected_amount for c in charges.filter(status=ChargeStatus.WAIVED)
        )
        # Collectable total = term MINUS the waived amount (110€), and every
        # remaining cycle keeps its normal 10€ — NOT 120/11 ≈ 10.91 (which the
        # buggy exclusion produced by re-spreading the forgiven 10€).
        assert (
            sum(c.expected_amount for c in planned) == Decimal("120.00") - waived_total
        )
        assert {c.expected_amount for c in planned} == {Decimal("10.00")}
        assert charges.count() == 12  # waived period preserved, not recreated

    def test_straddling_bundled_charge_unbundled_on_truncation(
        self, tenant, tenant_settings, subscription
    ):
        # MEM-1: a cancellation can truncate valid_until INSIDE a period whose
        # full-period charge was already bundled into a DRAFT run (period_start
        # <= valid_until < period_end). Left bundled it stays "locked" at its
        # FULL amount and would SEPA-debit the now-cancelled tail of the period.
        # The fix unbundles it so the regen drops + recreates it clamped.
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 14)]
        )
        ChargeScheduleService.regenerate_for_subscription(subscription)

        # Bundle a future full-month period's charge into a DRAFT run.
        target = list(
            ChargeSchedule.objects.filter(subscription=subscription).order_by(
                "period_start"
            )
        )[5]
        run = self._bundle(target)
        target_pk, full_period_end = target.pk, target.period_end

        # Truncate the term to a Sunday strictly INSIDE the bundled period.
        offset = (6 - target.period_start.weekday()) % 7 or 7
        valid_until = target.period_start + datetime.timedelta(days=offset)
        assert target.period_start <= valid_until < full_period_end  # real straddle
        subscription.valid_until = valid_until
        subscription.save()

        ChargeScheduleService.regenerate_for_subscription(subscription)

        # No charge still bundled into the DRAFT run extends past the cut — the
        # straddling row was unbundled (pre-fix it stayed locked at full period).
        assert not ChargeSchedule.objects.filter(
            billing_run=run, period_end__gt=valid_until
        ).exists()
        # The old full-period bundled row is gone (unbundled → deleted → recreated).
        assert not ChargeSchedule.objects.filter(pk=target_pk, billing_run=run).exists()
        # And nothing PLANNED survives for a period starting after the cut.
        assert not ChargeSchedule.objects.filter(
            subscription=subscription,
            status=ChargeStatus.PLANNED,
            period_start__gt=valid_until,
        ).exists()


@pytest.mark.django_db
class TestStrategyDeliverySetAlignment:
    """CHG-4: EXACT and SMOOTHED must bill the SAME delivery set — a delivery
    dated outside [valid_from, valid_until] is billed by neither."""

    def test_smoothed_excludes_out_of_term_delivery(
        self, tenant, tenant_settings, subscription
    ):
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save()
        # 6 in-term deliveries (weeks 2-7 = Jan-Feb) + 1 in week 20 (May).
        _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 8)] + [(2026, 20)]
        )
        # Truncate the term so the week-20 delivery falls OUTSIDE it.
        subscription.valid_until = datetime.date(2026, 3, 29)  # Sunday
        subscription.save()

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        # 6 in-term × 10€ = 60€. Before the clamp the stray week-20 delivery
        # inflated the SMOOTHED term total to 70€.
        assert sum(c.expected_amount for c in charges) == Decimal("60.00")


# ---------------------------------------------------------------------------
# On-off opt-out exclusion (TEST-1)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOptinExclusion:
    """Billing must drop on-off (``requires_optin``) deliveries the member
    opted out of — the ONLY place this happens is the Python property
    ``ShareDelivery.is_opted_in_for_delivery`` (payments/services.py). No prior
    test created a ``requires_optin`` variation, so the filter was a silent
    pass-through; a regression to overbill would have gone unnoticed."""

    def _optin_subscription(self, tenant_settings, member):
        # A requires_optin variation can only be saved once the tenant opts in.
        tenant_settings.allows_share_type_variation_optin = True
        tenant_settings.save(update_fields=["allows_share_type_variation_optin"])
        share_type = ShareTypeFactory(valid_from=datetime.date(2026, 1, 5))
        variation = ShareTypeVariationFactory(
            share_type=share_type,
            requires_optin=True,
            default_optin_state=False,  # off by default → each row starts opted out
            valid_from=datetime.date(2026, 1, 5),
        )
        return SubscriptionFactory(
            member=member,
            share_type_variation=variation,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
            quantity=1,
            price_per_delivery=Decimal("10.00"),
            payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
        )

    def _opt_in(self, deliveries):
        # Rows are created opted-out (default_optin_state=False, forced in
        # ShareDelivery.save on insert); flip via .update so the insert-time
        # stamp doesn't overwrite it.
        ShareDelivery.objects.filter(pk__in=[d.pk for d in deliveries]).update(
            is_opted_in=True
        )

    def test_exact_bills_only_opted_in_deliveries(
        self, tenant, tenant_settings, member
    ):
        subscription = self._optin_subscription(tenant_settings, member)
        deliveries = _make_deliveries_for_subscription(
            subscription, [(2026, 2), (2026, 3), (2026, 4), (2026, 7)]
        )
        # Opt IN 2 of the 4; the other 2 stay opted out → must not be billed.
        self._opt_in([deliveries[0], deliveries[3]])

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        # 2 opted-in × 10.00 — the 2 opted-out deliveries are dropped.
        assert sum(c.expected_amount for c in charges) == Decimal("20.00")

    def test_exact_all_opted_out_bills_nothing(self, tenant, tenant_settings, member):
        subscription = self._optin_subscription(tenant_settings, member)
        _make_deliveries_for_subscription(
            subscription, [(2026, 2), (2026, 3), (2026, 4)]
        )
        # No opt-ins → every delivery is excluded → all periods bill zero.

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        assert sum(c.expected_amount for c in charges) == Decimal("0.00")

    def test_smoothed_term_total_excludes_opted_out(
        self, tenant, tenant_settings, member
    ):
        tenant_settings.billing_strategy = TenantSettings.BILLING_STRATEGY_SMOOTHED
        tenant_settings.save(update_fields=["billing_strategy"])
        subscription = self._optin_subscription(tenant_settings, member)
        deliveries = _make_deliveries_for_subscription(
            subscription, [(2026, w) for w in range(2, 8)]  # 6 deliveries
        )
        self._opt_in(deliveries[:3])  # 3 opted in, 3 opted out

        ChargeScheduleService.regenerate_for_subscription(subscription)

        charges = ChargeSchedule.objects.filter(subscription=subscription)
        # Smoothed term total = 3 billable × 10.00, spread over the cycles.
        assert sum(c.expected_amount for c in charges) == Decimal("30.00")


@pytest.mark.django_db
class TestIsOptedInForDeliveryProperty:
    """Direct unit test of the property billing relies on, across the 4
    (requires_optin × is_opted_in) combinations. Each delivery gets its own
    weekday so the one-open-per-day_number SharesDeliveryDay guard is happy."""

    def _delivery(self, *, day_number, requires_optin, is_opted_in, tenant_settings):
        if requires_optin:
            tenant_settings.allows_share_type_variation_optin = True
            tenant_settings.save(update_fields=["allows_share_type_variation_optin"])
        variation = ShareTypeVariationFactory(
            requires_optin=requires_optin,
            default_optin_state=is_opted_in,
            valid_from=datetime.date(2026, 1, 5),
        )
        # Share.delivery_day and delivery_station_day.delivery_day must match
        # (ShareDelivery.clean) — share one SharesDeliveryDay across both.
        delivery_day = SharesDeliveryDayFactory(day_number=day_number)
        share = ShareFactory(
            year=2026,
            delivery_week=3,
            delivery_day=delivery_day,
            share_type_variation=variation,
        )
        delivery = ShareDeliveryFactory(
            share=share,
            delivery_station_day=DeliveryStationDayFactory(delivery_day=delivery_day),
        )
        # On insert, requires_optin rows are stamped from default_optin_state;
        # plain rows keep the factory value. Force the exact row value either
        # way so the assertion isolates the property logic.
        ShareDelivery.objects.filter(pk=delivery.pk).update(is_opted_in=is_opted_in)
        delivery.refresh_from_db()
        return delivery

    def test_plain_variation_always_billable(self, tenant, tenant_settings):
        # requires_optin=False → billable no matter what is_opted_in says.
        for index, opted in enumerate((True, False)):
            delivery = self._delivery(
                day_number=index,
                requires_optin=False,
                is_opted_in=opted,
                tenant_settings=tenant_settings,
            )
            assert delivery.is_opted_in_for_delivery is True

    def test_onoff_variation_follows_optin(self, tenant, tenant_settings):
        opted_in = self._delivery(
            day_number=0,
            requires_optin=True,
            is_opted_in=True,
            tenant_settings=tenant_settings,
        )
        assert opted_in.is_opted_in_for_delivery is True

        opted_out = self._delivery(
            day_number=1,
            requires_optin=True,
            is_opted_in=False,
            tenant_settings=tenant_settings,
        )
        assert opted_out.is_opted_in_for_delivery is False

    def test_property_agrees_with_delivery_counts_q(self, tenant, tenant_settings):
        # The rule lives twice: the Python property (billing loop) and the
        # ``delivery_counts_q`` Q-object (demand/prep). They must classify every
        # row identically — modulo joker, which the property is agnostic to.
        plain = self._delivery(
            day_number=0,
            requires_optin=False,
            is_opted_in=False,
            tenant_settings=tenant_settings,
        )
        onoff_in = self._delivery(
            day_number=1,
            requires_optin=True,
            is_opted_in=True,
            tenant_settings=tenant_settings,
        )
        onoff_out = self._delivery(
            day_number=2,
            requires_optin=True,
            is_opted_in=False,
            tenant_settings=tenant_settings,
        )

        rows = ShareDelivery.objects.all()
        counts_q_pks = set(
            rows.filter(ShareDelivery.delivery_counts_q()).values_list("pk", flat=True)
        )
        property_pks = {
            d.pk for d in rows if d.is_opted_in_for_delivery and not d.joker_taken
        }
        assert counts_q_pks == property_pks
        # Expected partition: plain + opted-in count; opted-out does not.
        assert property_pks == {plain.pk, onoff_in.pk}
        assert onoff_out.pk not in property_pks
