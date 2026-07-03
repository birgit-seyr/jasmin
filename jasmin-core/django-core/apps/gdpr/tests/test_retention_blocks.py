"""Tests for the retention pre-flight check.

Verifies that ``GDPRService.anonymize_user`` refuses with
``RetentionPeriodActive`` (HTTP 409) when the subject still has any
of the four retention obligations:

  - active CoopShare (GenG §5)
  - active subscription (ongoing service relationship)
  - open ChargeSchedule (PLANNED / ISSUED / PARTIAL — HGB §257)
  - unpaid finalized invoice (UStG §14b)

…and that a clean staff-only user (no Member, no Reseller, no
obligations) is anonymized without complaint.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.models import Member
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
    SubscriptionFactory,
)
from apps.gdpr.errors import RetentionPeriodActive
from apps.gdpr.services import GDPRService
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule


def _sunday_offset(weeks: int) -> datetime.date:
    """Return a Sunday ``weeks`` weeks from today (positive = future,
    negative = past). ``Subscription.valid_until`` has a model-level
    "must be Sunday" invariant (mirror of the Monday ``valid_from``
    rule per CLAUDE.md), so test dates can't be picked freely."""
    today = datetime.date.today()
    days_to_sunday = (6 - today.weekday()) % 7  # 6 = Sunday in weekday()
    base_sunday = today + datetime.timedelta(days=days_to_sunday)
    return base_sunday + datetime.timedelta(weeks=weeks)


@pytest.mark.django_db
class TestCheckRetentionBlocks:
    def test_clean_staff_user_has_no_blocks(self, tenant):
        """A pure staff/office user (no Member, no Reseller, no
        invoices) has nothing to retain — anonymization may proceed."""
        user = JasminUserFactory(roles=["office"])
        assert GDPRService.check_retention_blocks(user) == []

    def test_active_coop_share_blocks(self, tenant):
        """GenG §5: any OPEN (uncancelled) CoopShare on the subject's
        Member blocks anonymisation. Cancelled shares are excluded —
        their PII-free history can survive the member's deletion."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)
        CoopShareFactory(member=member)  # two shares → count in message

        reasons = GDPRService.check_retention_blocks(user)
        assert len(reasons) == 1
        assert "2 open CoopShare(s)" in reasons[0]
        assert "GenG" in reasons[0]

    def test_cancelled_but_unpaid_coop_share_blocks(self, tenant):
        """GDPR-DEL-1: a CANCELLED share whose equity was never paid back
        (``paid_back_date`` is None) still blocks anonymisation — the co-op
        still owes the ex-member their Geschäftsanteile (GenG §73 / Art.
        17(3)(b)) and must keep their identity + payout details."""
        from django.utils import timezone

        user = JasminUserFactory()
        member = MemberFactory(user=user)
        CoopShareFactory(
            member=member, cancelled_at=timezone.now(), paid_back_date=None
        )

        reasons = GDPRService.check_retention_blocks(user)
        assert any("CoopShare" in reason for reason in reasons)

    def test_cancelled_and_paid_back_coop_share_does_not_block(self, tenant):
        """Once the share is both cancelled AND paid back, the retention
        obligation is discharged and anonymisation may proceed."""
        from django.utils import timezone

        user = JasminUserFactory()
        member = MemberFactory(user=user)
        CoopShareFactory(
            member=member,
            cancelled_at=timezone.now(),
            paid_back_date=datetime.date.today(),
        )

        reasons = GDPRService.check_retention_blocks(user)
        assert reasons == []

    def test_active_subscription_blocks(self, tenant):
        """An ongoing subscription (no end date) = open service contract."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        SubscriptionFactory(member=member, valid_until=None)

        reasons = GDPRService.check_retention_blocks(user)
        assert any("active subscription" in r for r in reasons)

    def test_future_dated_subscription_blocks(self, tenant):
        """A subscription ending in the future still counts as active."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        SubscriptionFactory(
            member=member,
            valid_until=_sunday_offset(4),  # ~4 weeks ahead, a Sunday
        )

        reasons = GDPRService.check_retention_blocks(user)
        assert any("active subscription" in r for r in reasons)

    def test_past_subscription_does_not_block(self, tenant):
        """A subscription whose end date has passed is settled — does
        not block on its own. (CoopShare / invoices may still block;
        this test isolates the subscription branch.)"""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        SubscriptionFactory(
            member=member,
            valid_until=_sunday_offset(-4),  # ~4 weeks ago, a Sunday
        )

        reasons = GDPRService.check_retention_blocks(user)
        # No active-subscription reason should be present.
        assert not any("active subscription" in r for r in reasons)

    @pytest.mark.parametrize(
        "open_status", [ChargeStatus.PLANNED, ChargeStatus.ISSUED, ChargeStatus.PARTIAL]
    )
    def test_open_charge_schedule_blocks(self, tenant, open_status):
        """Each ChargeStatus that counts as owed-but-not-paid must
        block. Parametrised across all three open statuses."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        subscription = SubscriptionFactory(member=member)
        ChargeSchedule.objects.create(
            member=member,
            subscription=subscription,
            period_start=datetime.date(2026, 1, 5),
            period_end=datetime.date(2026, 1, 31),
            due_date=datetime.date(2026, 1, 31),
            expected_amount=Decimal("25.00"),
            status=open_status,
        )

        reasons = GDPRService.check_retention_blocks(user)
        assert any("open charge(s)" in r for r in reasons)

    @pytest.mark.parametrize("settled", [ChargeStatus.PAID, ChargeStatus.WAIVED])
    def test_settled_charge_does_not_block(self, tenant, settled):
        """PAID / WAIVED charges are settled — no block from them."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        subscription = SubscriptionFactory(member=member)
        ChargeSchedule.objects.create(
            member=member,
            subscription=subscription,
            period_start=datetime.date(2026, 1, 5),
            period_end=datetime.date(2026, 1, 31),
            due_date=datetime.date(2026, 1, 31),
            expected_amount=Decimal("25.00"),
            status=settled,
        )

        reasons = GDPRService.check_retention_blocks(user)
        assert not any("open charge(s)" in r for r in reasons)

    def test_unpaid_finalized_invoice_on_linked_reseller_blocks(self, tenant):
        """UStG §14b: open finalized invoice on a Reseller linked to
        the user must block (B2B customer + member overlap case)."""
        from apps.commissioning.tests.factories import (
            InvoiceResellerFactory,
            ResellerFactory,
        )

        user = JasminUserFactory()
        reseller = ResellerFactory(linked_user=user)
        InvoiceResellerFactory(
            reseller=reseller, is_finalized=True, has_been_paid=False
        )

        reasons = GDPRService.check_retention_blocks(user)
        assert any("unpaid finalized invoice(s)" in r for r in reasons)

    def test_paid_invoice_does_not_block(self, tenant):
        """Already-paid invoice: retention is still active for 10 years,
        but that's handled by the Step 8 cleanup cron — not by the
        live pre-flight check, which only refuses on OPEN obligations."""
        from apps.commissioning.tests.factories import (
            InvoiceResellerFactory,
            ResellerFactory,
        )

        user = JasminUserFactory()
        reseller = ResellerFactory(linked_user=user)
        InvoiceResellerFactory(reseller=reseller, is_finalized=True, has_been_paid=True)

        reasons = GDPRService.check_retention_blocks(user)
        assert not any("unpaid" in r for r in reasons)

    def test_multiple_blocks_aggregated(self, tenant):
        """When several obligations exist, all are reported so the
        admin sees the full list, not just the first failure."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)
        SubscriptionFactory(member=member, valid_until=None)

        reasons = GDPRService.check_retention_blocks(user)
        assert len(reasons) >= 2
        assert any("CoopShare" in r for r in reasons)
        assert any("subscription" in r for r in reasons)


@pytest.mark.django_db
class TestAnonymizeUserRefusal:
    def test_anonymize_raises_when_blocks_exist(self, tenant):
        """``anonymize_user`` calls ``check_retention_blocks`` first
        and raises ``RetentionPeriodActive`` (→ HTTP 409) if any
        block is present. The JasminUser row must be UNCHANGED after
        the refusal."""
        user = JasminUserFactory(first_name="Alice", last_name="Bob")
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)

        with pytest.raises(RetentionPeriodActive) as exc_info:
            GDPRService.anonymize_user(user)

        # Error carries the per-reason details for the frontend.
        assert "CoopShare" in str(exc_info.value)
        assert "reasons" in exc_info.value.details
        assert len(exc_info.value.details["reasons"]) >= 1

        # Critically: the user row was NOT mutated by the failed call.
        user.refresh_from_db()
        assert user.first_name == "Alice"
        assert user.last_name == "Bob"

    def test_anonymize_proceeds_for_clean_user(self, tenant):
        """No retention obligations → anonymization runs as before."""
        user = JasminUserFactory(
            first_name="Charlie",
            last_name="Doe",
            email="charlie@example.com",
        )
        GDPRService.anonymize_user(user)

        user.refresh_from_db()
        assert user.first_name == "Gelöscht"
        assert user.last_name == "Gelöscht"
        assert user.email == f"deleted_{user.pk}@deleted.invalid"

    def test_anonymize_proceeds_after_obligations_settled(self, tenant):
        """A previously-blocked user becomes deletable once the
        obligations are cleared (CoopShare deleted, charge paid, etc.).
        This is the path the admin takes when a member has properly
        exited the cooperative."""
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        share = CoopShareFactory(member=member)

        # Pre-condition: blocked.
        assert GDPRService.check_retention_blocks(user)

        # Settle: remove the share (in real life, the cooperative
        # would record an exit + transfer; here we just delete to
        # simulate the post-exit + post-retention state).
        share.delete()
        assert Member.objects.filter(pk=member.pk).exists()  # member stays

        # Now anonymization succeeds.
        GDPRService.anonymize_user(user)
        user.refresh_from_db()
        assert user.first_name == "Gelöscht"


@pytest.mark.django_db
class TestCheckRetentionBlocksBulk:
    """The office GDPR pending-deletions inbox computes blockers for every
    pending request via ``check_retention_blocks_bulk``. It must run a
    CONSTANT number of queries regardless of how many users are checked (one
    grouped COUNT per obligation), not ~5 per user, and must agree with the
    single-user path."""

    @staticmethod
    def _user_with_open_coop_share():
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)  # one open share → a real blocker
        return user

    def test_query_count_constant_in_user_count(self, tenant):
        small = [self._user_with_open_coop_share() for _ in range(2)]
        with CaptureQueriesContext(connection) as ctx_small:
            res_small = GDPRService.check_retention_blocks_bulk(small)

        large = [self._user_with_open_coop_share() for _ in range(5)]
        with CaptureQueriesContext(connection) as ctx_large:
            res_large = GDPRService.check_retention_blocks_bulk(large)

        # Non-vacuity: every user really has a blocker, so the counts ran.
        assert all(res_small[u.id] for u in small)
        assert all(res_large[u.id] for u in large)

        # django-tenants pins the schema with a ``SET search_path`` before
        # each statement; those aren't the work being bounded, so count only
        # the real SELECTs.
        def _selects(ctx):
            return [
                query
                for query in ctx.captured_queries
                if not query["sql"].lstrip().upper().startswith("SET ")
            ]

        small_selects = _selects(ctx_small)
        large_selects = _selects(ctx_large)

        # Constant query count — no per-user N+1 (one grouped COUNT per
        # obligation regardless of user count).
        assert len(small_selects) == len(large_selects)
        # member lookup + one grouped COUNT per obligation (coop / subscription
        # / charge / invoice) = 5 queries, independent of the user count.
        assert len(large_selects) <= 6

    def test_bulk_agrees_with_single_user(self, tenant):
        user = JasminUserFactory()
        member = MemberFactory(user=user)
        CoopShareFactory(member=member)
        SubscriptionFactory(member=member, valid_until=None)

        single = GDPRService.check_retention_blocks(user)
        bulk = GDPRService.check_retention_blocks_bulk([user])[user.id]
        assert bulk == single
        assert len(bulk) >= 2  # coop + subscription
