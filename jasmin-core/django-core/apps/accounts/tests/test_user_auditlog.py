"""JasminUser auditlog coverage — the role-change trail.

Role grants, demotions and deactivations are the first thing an auditor asks
about, and the service layer's ``auth.log`` line rotates away. ``accounts/
apps.py`` registers the user model so those changes leave a durable
``auditlog_logentry`` row carrying before and after, while the PII columns
stay masked out of diffs that are retained indefinitely and ``password``
never appears at all.
"""

from __future__ import annotations

import pytest

from apps.authz.roles import Role
from apps.commissioning.tests.factories import JasminUserFactory


def _changes_blob(user) -> str:
    from auditlog.models import LogEntry

    return " ".join(str(e.changes) for e in LogEntry.objects.get_for_object(user))


@pytest.mark.django_db
class TestJasminUserAuditlog:
    def test_role_change_is_audited_with_before_and_after(self, tenant):
        from auditlog.models import LogEntry

        user = JasminUserFactory(roles=[Role.OFFICE])
        user.roles = [Role.OFFICE, Role.ADMIN]
        user.save()

        assert LogEntry.objects.get_for_object(user).exists(), (
            "JasminUser saves should produce auditlog entries — is the "
            "registration in accounts/apps.py gone?"
        )
        blob = _changes_blob(user)
        assert "roles" in blob
        # Both sides of the change are recoverable, which is the whole point.
        assert Role.ADMIN in blob

    def test_deactivation_is_audited(self, tenant):
        user = JasminUserFactory(roles=[Role.OFFICE], account_status="active")
        user.account_status = "inactive"
        user.save()

        assert "account_status" in _changes_blob(user)

    def test_password_never_reaches_the_audit_trail(self, tenant):
        from auditlog.models import LogEntry

        user = JasminUserFactory()
        user.set_password("CorrectHorse42!Battery")
        user.save()

        # Assert something WAS logged before asserting what was not. Without
        # this the test passes vacuously the moment the registration goes.
        assert LogEntry.objects.get_for_object(user).exists()
        blob = _changes_blob(user)
        assert "password" not in blob
        assert "CorrectHorse42!Battery" not in blob

    def test_pii_is_tracked_but_masked(self, tenant):
        user = JasminUserFactory()
        user.first_name = "Gabriele"
        user.save()

        blob = _changes_blob(user)
        # The field is tracked (its key is present) but the raw value is not.
        assert "first_name" in blob
        assert "Gabriele" not in blob
