"""Tests for `ChargeScheduleService.regenerate_all` (bulk path).

Covers the cross-subscription bulk regeneration entry point that the
admin "Recompute every subscription's planned charges" action uses.

Invariants:
    - Returns a dict keyed by str(subscription.pk).
    - Each value is the count of PLANNED rows after regeneration for that
      subscription (matching what regenerate_for_subscription returns).
    - Idempotent: a second call on the same dataset returns the same map
      and produces no net DB change in PLANNED rows.
    - Locked statuses (ISSUED / PAID / FAILED / WAIVED) are preserved.
    - Subscriptions with no valid_from contribute 0 (and don't crash).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SubscriptionFactory,
)
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule
from apps.payments.services import ChargeScheduleService


def _make_subscription(
    *,
    valid_from=datetime.date(2026, 1, 5),
    valid_until=datetime.date(2026, 12, 27),
    admin_confirmed=True,
    on_waiting_list=False,
):
    user = JasminUserFactory(roles=["member"])
    member = MemberFactory(user=user)
    return SubscriptionFactory(
        member=member,
        valid_from=valid_from,
        valid_until=valid_until,
        # ``regenerate_all`` only bills admin-confirmed, non-waiting-list subs
        # (COR-13); default to billable so the bulk-path tests below exercise
        # real charge generation.
        admin_confirmed=admin_confirmed,
        on_waiting_list=on_waiting_list,
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
        # SharesDeliveryDay has overlap_unique_fields=("day_number",); the
        # factory hard-codes day_number=2, so building a second one would
        # collide. We don't need a delivery station day for charge
        # schedule generation.
        default_delivery_station_day=None,
    )


@pytest.mark.django_db
class TestRegenerateAll:
    def test_returns_count_per_subscription(self, tenant, tenant_settings):
        sub_a = _make_subscription()
        sub_b = _make_subscription()

        result = ChargeScheduleService.regenerate_all()

        # Other tests may leave Subscription rows; assert ours are present.
        assert str(sub_a.pk) in result
        assert str(sub_b.pk) in result
        # MONTHLY cycle over a 12-month term ⇒ 12 planned rows each.
        assert result[str(sub_a.pk)] == 12
        assert result[str(sub_b.pk)] == 12

        for sub in (sub_a, sub_b):
            assert (
                ChargeSchedule.objects.filter(
                    subscription=sub, status=ChargeStatus.PLANNED
                ).count()
                == 12
            )

    def test_skips_non_billable_subscriptions(self, tenant, tenant_settings):
        """COR-13: ``regenerate_all`` gives a ledger ONLY to billable subs.
        Unconfirmed and waiting-list subscriptions must get NO PLANNED charges
        (they used to get 12 each, polluting the ledger and the SEPA run)."""
        confirmed = _make_subscription()  # admin_confirmed=True, not waiting
        unconfirmed = _make_subscription(admin_confirmed=False)
        waiting = _make_subscription(on_waiting_list=True)

        result = ChargeScheduleService.regenerate_all()

        assert str(confirmed.pk) in result
        assert str(unconfirmed.pk) not in result
        assert str(waiting.pk) not in result
        assert ChargeSchedule.objects.filter(subscription=unconfirmed).count() == 0
        assert ChargeSchedule.objects.filter(subscription=waiting).count() == 0
        assert (
            ChargeSchedule.objects.filter(
                subscription=confirmed, status=ChargeStatus.PLANNED
            ).count()
            == 12
        )

    def test_idempotent(self, tenant, tenant_settings):
        sub = _make_subscription()

        first = ChargeScheduleService.regenerate_all()
        before = list(
            ChargeSchedule.objects.filter(subscription=sub, status=ChargeStatus.PLANNED)
            .order_by("period_start")
            .values_list("period_start", "expected_amount")
        )

        second = ChargeScheduleService.regenerate_all()
        after = list(
            ChargeSchedule.objects.filter(subscription=sub, status=ChargeStatus.PLANNED)
            .order_by("period_start")
            .values_list("period_start", "expected_amount")
        )

        assert first == second
        assert before == after

    def test_preserves_locked_charges(self, tenant, tenant_settings):
        sub = _make_subscription()
        ChargeScheduleService.regenerate_for_subscription(sub)

        # Lock the first PLANNED row by transitioning it to ISSUED.
        first_planned = (
            ChargeSchedule.objects.filter(subscription=sub, status=ChargeStatus.PLANNED)
            .order_by("period_start")
            .first()
        )
        first_planned.status = ChargeStatus.ISSUED
        first_planned.save(allow_immutable_change=True)
        locked_period_start = first_planned.period_start

        ChargeScheduleService.regenerate_all()

        # Locked row is still ISSUED, unchanged.
        first_planned.refresh_from_db()
        assert first_planned.status == ChargeStatus.ISSUED
        assert first_planned.period_start == locked_period_start
        # And no PLANNED row has been created for that same period.
        assert not ChargeSchedule.objects.filter(
            subscription=sub,
            status=ChargeStatus.PLANNED,
            period_start=locked_period_start,
        ).exists()

    def test_sharedelivery_query_is_batched_across_subscriptions(
        self, tenant, tenant_settings
    ):
        """``regenerate_all`` must pre-fetch every subscription's
        ShareDeliveries in ONE query, not one ``filter(subscription=...)``
        per subscription. Adding subscriptions must not add ShareDelivery
        SELECTs."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def _sharedelivery_selects(ctx) -> int:
            return sum(
                1
                for q in ctx.captured_queries
                if '"commissioning_sharedelivery"' in q["sql"].lower()
                and q["sql"].lstrip().lower().startswith("select")
            )

        _make_subscription()
        with CaptureQueriesContext(connection) as ctx_small:
            ChargeScheduleService.regenerate_all()
        small = _sharedelivery_selects(ctx_small)

        for _ in range(4):
            _make_subscription()
        with CaptureQueriesContext(connection) as ctx_large:
            ChargeScheduleService.regenerate_all()
        large = _sharedelivery_selects(ctx_large)

        assert small <= 1, f"expected <=1 ShareDelivery SELECT, got {small}"
        assert large <= 1, (
            "ShareDelivery query not batched: "
            f"1 sub -> {small} selects, 5 subs -> {large} selects"
        )

    def test_tenant_and_settings_queries_do_not_fan_out(self, tenant, tenant_settings):
        """``regenerate_all`` must resolve the tenant + its billing settings
        ONCE for the whole run, not once per subscription.

        Both are invariant across the run (same schema, same active settings
        row), so adding subscriptions must NOT add Tenant / TenantSettings
        SELECTs. Without the hoist, ``regenerate_for_subscription`` re-queried
        both per subscription — an N+1 over those tables that this locks.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.shared.tenants.models import Tenant, TenantSettings

        tenant_table = Tenant._meta.db_table
        settings_table = TenantSettings._meta.db_table

        def _table_selects(ctx, table: str) -> int:
            needle = f'"{table}"'
            return sum(
                1
                for q in ctx.captured_queries
                if needle in q["sql"].lower()
                and q["sql"].lstrip().lower().startswith("select")
            )

        _make_subscription()
        with CaptureQueriesContext(connection) as ctx_small:
            ChargeScheduleService.regenerate_all()
        small_tenant = _table_selects(ctx_small, tenant_table)
        small_settings = _table_selects(ctx_small, settings_table)

        for _ in range(4):
            _make_subscription()
        with CaptureQueriesContext(connection) as ctx_large:
            ChargeScheduleService.regenerate_all()
        large_tenant = _table_selects(ctx_large, tenant_table)
        large_settings = _table_selects(ctx_large, settings_table)

        # Tenant resolved exactly once, regardless of subscription count.
        assert (
            small_tenant <= 1
        ), f"expected <=1 Tenant SELECT for 1 sub, got {small_tenant}"
        assert large_tenant == small_tenant, (
            "Tenant query fans out across subscriptions: "
            f"1 sub -> {small_tenant} selects, 5 subs -> {large_tenant}"
        )
        # Settings resolved once too — the count must not grow with N.
        assert large_settings <= small_settings, (
            "TenantSettings query fans out across subscriptions: "
            f"1 sub -> {small_settings} selects, 5 subs -> {large_settings}"
        )

    def test_subscription_without_valid_from_returns_zero(
        self, tenant, tenant_settings
    ):
        # The Subscription model has a DB-level NOT NULL on valid_from, so
        # we can't actually persist a row without it. The service code
        # still defends with `if not subscription.valid_from: return 0`,
        # which we exercise via an in-memory instance.
        sub = _make_subscription()
        sub.valid_from = None
        from apps.payments.services import ChargeScheduleService

        n = ChargeScheduleService.regenerate_for_subscription(sub)
        assert n == 0
