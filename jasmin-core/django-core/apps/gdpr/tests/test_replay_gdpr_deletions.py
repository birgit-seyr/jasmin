"""Tests for the ``replay_gdpr_deletions`` management command.

After a backup restore, a user whose data was anonymized between the
backup snapshot and now comes back to life with their PII intact. This
command walks every tenant's ``DeletionLog`` and re-runs the deletion so
the right to erasure (Art. 17) survives a restore.

The regression these tests pin: the command used to hand-scrub only four
``JasminUser`` columns (``is_active``, ``first_name``, ``last_name``,
``email``), silently leaving the Member row, billing/IBAN, login history
and every other PII surface untouched. It now delegates to
``GDPRService.anonymize_user`` — the single source of truth — so a replay
scrubs exactly what a live deletion does.

Two behaviours are locked here:
  1. A restored, still-active subject is FULLY re-anonymized (Member
     tombstone + PII nulled), not just the four user columns.
  2. A subject whose statutory retention obligation also came back with
     the restore (an open CoopShare) is SKIPPED, not anonymized — and the
     skip doesn't abort the rest of the replay.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.gdpr.models import DeletionLog


@pytest.mark.django_db
class TestReplayGdprDeletions:
    def test_reanonymizes_restored_active_user(self, tenant):
        """A DeletionLog whose subject is back with PII intact gets the
        FULL anonymization — Member tombstone + PII scrub — proving the
        command runs ``anonymize_user``, not the old 4-column hand-scrub
        (which never touched the Member row at all)."""
        from apps.commissioning.tests.factories import (
            JasminUserFactory,
            MemberFactory,
        )

        user = JasminUserFactory(email="restored@example.com", first_name="Restored")
        member = MemberFactory(
            user=user,
            first_name="Restored",
            address="Hauptstrasse 1",
            city="Beispielstadt",
        )
        DeletionLog.objects.create(user_email="restored@example.com")

        call_command("replay_gdpr_deletions")

        user.refresh_from_db()
        member.refresh_from_db()
        # User deactivated (the old code did this too)...
        assert user.is_active is False
        # ...but the Member row is ALSO scrubbed now — the old hand-scrub
        # left it fully intact.
        assert member.first_name == "Gelöscht"
        assert member.address is None
        assert member.city is None
        assert member.is_active is False

    def test_skips_subject_with_active_retention_obligation(self, tenant):
        """A restore can bring back an open CoopShare alongside the
        subject. ``anonymize_user`` then raises ``RetentionPeriodActive``;
        the command must SKIP that subject (leaving PII untouched) and
        keep going — not crash the whole replay."""
        from apps.commissioning.tests.factories import (
            CoopShareFactory,
            JasminUserFactory,
            MemberFactory,
        )

        user = JasminUserFactory(email="blocked@example.com", first_name="Blocked")
        member = MemberFactory(
            user=user,
            first_name="Blocked",
            address="Hauptstrasse 2",
        )
        # Open (uncancelled) share → statutory retention obligation active.
        CoopShareFactory(member=member)
        DeletionLog.objects.create(user_email="blocked@example.com")

        call_command("replay_gdpr_deletions")

        user.refresh_from_db()
        member.refresh_from_db()
        # NOT anonymized — the retention block held. The old command had
        # NO retention check and hand-scrubbed the user's name
        # ("deleted") unconditionally; the new skip path leaves the
        # subject completely intact — name included.
        assert user.is_active is True
        assert user.first_name == "Blocked"
        assert member.first_name == "Blocked"
        assert member.address == "Hauptstrasse 2"

    def test_ignores_already_anonymized_subject(self, tenant):
        """Idempotency: a DeletionLog whose subject is already inactive
        (a prior replay ran, or the email never matched a live row) is a
        no-op — the command neither re-scrubs nor raises."""
        from apps.commissioning.tests.factories import (
            JasminUserFactory,
            MemberFactory,
        )

        # Already-anonymized: inactive user, Member already tombstoned.
        user = JasminUserFactory(email="done@example.com", is_active=False)
        member = MemberFactory(user=user, first_name="Gelöscht")
        DeletionLog.objects.create(user_email="done@example.com")
        # A log for an email with no matching row at all.
        DeletionLog.objects.create(user_email="ghost@example.com")

        call_command("replay_gdpr_deletions")

        user.refresh_from_db()
        member.refresh_from_db()
        assert user.is_active is False
        assert member.first_name == "Gelöscht"
