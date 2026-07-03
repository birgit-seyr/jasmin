"""Tests for AdminConfirmableMixin — confirm, reject, properties."""

from __future__ import annotations

import pytest

from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory


@pytest.mark.django_db
class TestConfirm:
    def test_sets_confirmed_fields(self, tenant):
        member = MemberFactory()
        admin = JasminUserFactory()

        member.confirm(admin)

        assert member.admin_confirmed is True
        assert member.admin_confirmed_by == admin
        assert member.admin_confirmed_at is not None

    def test_clears_rejection_reason(self, tenant):
        member = MemberFactory()
        admin = JasminUserFactory()
        member.admin_rejection_reason = "Some old reason"

        member.confirm(admin)

        assert member.admin_rejection_reason is None

    def test_save_false_skips_db(self, tenant):
        member = MemberFactory()
        admin = JasminUserFactory()

        member.confirm(admin, save=False)
        member.refresh_from_db()

        # DB should still have the old value
        assert member.admin_confirmed is False


@pytest.mark.django_db
class TestReject:
    def test_sets_rejection_fields(self, tenant):
        member = MemberFactory()
        admin = JasminUserFactory()

        member.reject(admin, reason="Not approved")

        assert member.admin_confirmed is False
        assert member.admin_confirmed_by == admin
        assert member.admin_rejection_reason == "Not approved"

    def test_save_false_skips_db(self, tenant):
        member = MemberFactory()
        admin = JasminUserFactory()

        member.reject(admin, reason="Rejected", save=False)
        member.refresh_from_db()

        assert member.admin_rejection_reason is None


@pytest.mark.django_db
class TestAdminConfirmableProperties:
    def test_is_confirmed(self, tenant):
        member = MemberFactory()
        member.admin_confirmed = True
        assert member.is_confirmed is True

    def test_is_pending_when_no_rejection(self, tenant):
        member = MemberFactory()
        assert member.is_pending is True

    def test_not_pending_when_rejected(self, tenant):
        # ``is_pending`` is driven by the ``admin_rejected_at``
        # TIMESTAMP, not by ``admin_rejection_reason`` — the reason
        # is optional and shouldn't decide whether the row is still
        # awaiting an office decision. Earlier versions of this test
        # set only the reason; that no longer trips the flag (and
        # the office can reject without typing a reason).
        from django.utils import timezone

        member = MemberFactory()
        member.admin_rejected_at = timezone.now()
        member.admin_rejection_reason = "Reason"
        assert member.is_pending is False
        assert member.is_rejected is True
