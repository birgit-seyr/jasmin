"""Tests for the ``anonymise_long_cancelled_members`` Huey periodic task.

Closes the GenG §31 / HGB §257 / AO §147 10-year clock that the
audit checklist and ``docs/retention-policy.md`` advertise. Without
this task, the retention claim was theoretical: an auditor running

    Member.objects.filter(
        cancelled_effective_at__lt=ten_years_ago,
    ).count()

would have found PII the policy claimed had been erased.

We exercise ``_run_for_current_schema`` directly (not the
``@db_periodic_task`` wrapper) because the wrapper iterates tenants
via ``schema_context`` and the ``tenant`` fixture already puts us in
the test schema. The behavior under test — candidate selection,
retention-block handling, idempotency — lives in the inner function.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.commissioning.models import Member
from apps.commissioning.services.member_cancellation import (
    cancel_member_with_coop_shares,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)
from apps.gdpr.models import DeletionLog
from apps.gdpr.tasks import (
    EX_MEMBER_RETENTION_YEARS,
    _retention_cutoff,
    _run_for_current_schema,
)

# Exactly the cutoff point — a member whose ``cancelled_effective_at``
# is this date is on the boundary and SHOULD be picked up
# (``__lte=cutoff``).
_TODAY = datetime.date(2026, 6, 3)
_CUTOFF = _TODAY - relativedelta(years=EX_MEMBER_RETENTION_YEARS)
# A long-cancelled ex-member must have entered well before their exit date.
# MemberFactory defaults ``entry_date`` to today; these members are cancelled
# ~10 years ago, so an explicit early entry keeps the dates ordered.
_EARLY_ENTRY = datetime.date(2010, 1, 1)


def _cancel_member_at(member: Member, when: datetime.date) -> None:
    """Stamp the cancellation timestamps directly so the test can fix
    the date without depending on year-end notice-period math."""
    cancel_member_with_coop_shares(
        member,
        cancelled_at=timezone.make_aware(
            datetime.datetime.combine(when, datetime.time.min)
        ),
        cancelled_effective_at=when,
    )


@pytest.mark.django_db
class TestRetentionCutoff:
    def test_cutoff_is_today_minus_ten_years(self):
        today = datetime.date(2026, 6, 3)
        assert _retention_cutoff(today) == datetime.date(2016, 6, 3)


@pytest.mark.django_db
class TestSweepCandidateSelection:
    def test_past_cutoff_with_no_blocks_is_anonymised(self, tenant):
        user = JasminUserFactory(email="ex.member@example.com", is_active=True)
        member = MemberFactory(
            user=user,
            member_number=42,
            email=user.email,
            entry_date=_EARLY_ENTRY,
        )
        _cancel_member_at(member, _CUTOFF - relativedelta(days=1))

        anonymised, blocked = _run_for_current_schema(_CUTOFF)

        assert (anonymised, blocked) == (1, 0)
        user.refresh_from_db()
        assert user.is_active is False
        assert user.account_status == "inactive"
        # DeletionLog stamped with the original email — the audit trail
        # that backup-replay walks.
        assert DeletionLog.objects.filter(user_email="ex.member@example.com").exists()

    def test_inside_retention_window_is_skipped(self, tenant):
        user = JasminUserFactory(email="recent.member@example.com", is_active=True)
        member = MemberFactory(user=user, email=user.email, entry_date=_EARLY_ENTRY)
        # One day BEFORE the cutoff means still within the 10y window.
        _cancel_member_at(member, _CUTOFF + relativedelta(days=1))

        anonymised, blocked = _run_for_current_schema(_CUTOFF)

        assert (anonymised, blocked) == (0, 0)
        user.refresh_from_db()
        assert user.is_active is True

    def test_exactly_at_cutoff_is_anonymised(self, tenant):
        user = JasminUserFactory(email="boundary.member@example.com", is_active=True)
        member = MemberFactory(user=user, email=user.email, entry_date=_EARLY_ENTRY)
        _cancel_member_at(member, _CUTOFF)

        anonymised, blocked = _run_for_current_schema(_CUTOFF)

        assert anonymised == 1

    def test_uncancelled_member_is_skipped(self, tenant):
        """``cancelled_effective_at IS NULL`` rows must never be picked
        up — the office hasn't recorded a legal exit date."""
        user = JasminUserFactory(email="active.member@example.com", is_active=True)
        MemberFactory(user=user, email=user.email)

        anonymised, blocked = _run_for_current_schema(_CUTOFF)

        assert (anonymised, blocked) == (0, 0)

    def test_manually_deactivated_member_is_still_anonymised(self, tenant):
        """GDPR-1: the sweep must NOT key on ``user.is_active``. Ordinary
        office deactivation (``account_status="inactive"``) also clears it, so
        keying on it would skip a cancelled-past-window ex-member who was merely
        deactivated — retaining their PII forever. The tombstone-based filter
        (exclude ``@deleted.invalid``) must still pick them up."""
        user = JasminUserFactory(
            email="deactivated.exmember@example.com", is_active=True
        )
        member = MemberFactory(user=user, email=user.email, entry_date=_EARLY_ENTRY)
        _cancel_member_at(member, _CUTOFF - relativedelta(days=1))
        # Office deactivates the login — NOT anonymisation. is_active False, but
        # the email is still the real address (no @deleted.invalid tombstone).
        user.account_status = "inactive"
        user.is_active = False
        user.save(update_fields=["account_status", "is_active"])

        anonymised, blocked = _run_for_current_schema(_CUTOFF)

        assert (anonymised, blocked) == (1, 0)
        user.refresh_from_db()
        assert user.email.endswith("@deleted.invalid")  # now tombstoned
        assert DeletionLog.objects.filter(
            user_email="deactivated.exmember@example.com"
        ).exists()


@pytest.mark.django_db
class TestRetentionBlockObservability:
    """Retention blocks must NOT cause the sweep to error out — they
    must be logged via ``gdpr.ex_member_blocked`` and counted, so the
    office can see which ex-members are stuck on which obligations."""

    def test_open_coop_share_blocks_and_counts(self, tenant):
        user = JasminUserFactory(email="blocked.member@example.com", is_active=True)
        member = MemberFactory(user=user, email=user.email, entry_date=_EARLY_ENTRY)
        # CoopShare must exist BEFORE cancellation so cancel-with-shares
        # cascades to it — except we explicitly want a STILL-OPEN share
        # to trigger the retention block.
        CoopShareFactory(member=member, amount_of_coop_shares=Decimal("1"))
        # Stamp the cancellation directly on Member only — leave the
        # CoopShare uncancelled to simulate "office forgot to close it".
        member.cancelled_at = timezone.now()
        member.cancelled_effective_at = _CUTOFF - relativedelta(days=1)
        member.save(update_fields=["cancelled_at", "cancelled_effective_at"])

        anonymised, blocked = _run_for_current_schema(_CUTOFF)

        assert (anonymised, blocked) == (0, 1)
        # User still active — the block prevented the scrub.
        user.refresh_from_db()
        assert user.is_active is True
        # No DeletionLog row created on a blocked sweep.
        assert not DeletionLog.objects.filter(
            user_email="blocked.member@example.com"
        ).exists()


@pytest.mark.django_db
class TestIdempotency:
    """The sweep must not re-process members it already anonymised, and
    must not create duplicate DeletionLog rows on repeat runs."""

    def test_already_anonymised_member_is_not_re_processed(self, tenant):
        user = JasminUserFactory(email="repeat.member@example.com", is_active=True)
        member = MemberFactory(user=user, email=user.email, entry_date=_EARLY_ENTRY)
        _cancel_member_at(member, _CUTOFF - relativedelta(days=1))

        # First sweep.
        first_anonymised, _ = _run_for_current_schema(_CUTOFF)
        assert first_anonymised == 1
        first_count = DeletionLog.objects.count()

        # Second sweep — must NOT touch the already-inactive user, must
        # NOT create another DeletionLog row.
        second_anonymised, second_blocked = _run_for_current_schema(_CUTOFF)

        assert (second_anonymised, second_blocked) == (0, 0)
        assert DeletionLog.objects.count() == first_count
