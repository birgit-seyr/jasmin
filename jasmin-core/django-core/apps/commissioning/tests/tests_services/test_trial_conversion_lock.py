"""BIZ-2: ``convert_trial_member_on_first_coop_share`` must re-check
``is_trial`` under a row lock so two concurrent first-CoopShare inserts
can't both convert (which would burn a second member_number from the
sequence and fire a duplicate welcome email).

The fix re-fetches the member with ``select_for_update()`` inside the
existing ``transaction.atomic()`` block and bails out (returns ``False``)
when the reloaded row is no longer a trial.

These are focused unit tests — no real threads. They assert the
re-check PATH: a normal first conversion flips ``is_trial`` and returns
``True``; a second call against the now-non-trial row (the state a
losing concurrent transaction would reload under the lock) returns
``False`` and changes nothing.
"""

from __future__ import annotations

import pytest

from apps.commissioning.services.trial_conversion import (
    convert_trial_member_on_first_coop_share,
)
from apps.commissioning.tests.factories import MemberFactory


@pytest.mark.django_db
class TestTrialConversionRowLockRecheck:
    def test_first_conversion_flips_is_trial(self, tenant):
        """(a) A normal first conversion succeeds and flips the flag."""
        member = MemberFactory(member_number=None, is_trial=True)

        assert convert_trial_member_on_first_coop_share(member) is True

        member.refresh_from_db()
        assert member.is_trial is False
        assert member.trial_converted_at is not None
        assert member.member_number is not None

    def test_recheck_returns_false_on_already_converted_row(self, tenant):
        """(b) After conversion, calling again on the (now non-trial)
        row hits the under-lock re-check and is a no-op returning False.

        Simulates the losing side of a concurrent race: the second
        transaction blocks on ``select_for_update``, then reloads
        ``is_trial=False`` once the winner commits — and must not
        re-stamp / re-number / re-send.
        """
        member = MemberFactory(member_number=None, is_trial=True)
        assert convert_trial_member_on_first_coop_share(member) is True

        member.refresh_from_db()
        first_stamp = member.trial_converted_at
        first_number = member.member_number

        # The caller's in-memory ``member`` is the original instance.
        # Force its ``is_trial`` back to True so the cheap pre-lock guard
        # passes — this is exactly the stale snapshot a racing second
        # transaction would hold. The under-lock re-fetch must still
        # reload the committed ``is_trial=False`` and bail out.
        member.is_trial = True

        assert convert_trial_member_on_first_coop_share(member) is False

        member.refresh_from_db()
        assert member.is_trial is False
        assert member.trial_converted_at == first_stamp
        assert member.member_number == first_number
