"""Trial-member lifecycle: confirmation, conversion, member_number,
entry_date.

A "trial member" in this codebase is a Member with ``is_trial=True``.
Under the GenG, such a person is NOT yet a Mitglied — they have no
Geschäftsanteil (CoopShare). The platform-level consequences:

  * confirming a trial member does NOT assign a ``member_number`` OR
    an ``entry_date`` (both are reserved for GenG members)
  * acquiring the first CoopShare auto-converts them to a full
    member: ``is_trial`` flips to False, ``trial_converted_at`` is
    stamped, ``member_number`` is generated via the same advisory-
    locked sequence office confirmation uses, AND ``entry_date`` is
    stamped to today's date (GenG §30 Eintrittsdatum).

The conversion is idempotent: a real member who acquires a second
CoopShare doesn't get re-stamped. And a Member who was never on
trial (``is_trial=False`` from creation) keeps ``trial_converted_at``
NULL forever — only ``is_trial=True → False`` transitions stamp it.

``entry_date`` is NEVER overwritten if it's already set. This
matters for migrated members whose real Eintrittsdatum predates the
platform; the office sets the historical date, the auto-stamp here
respects it.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.commissioning.services.trial_conversion import (
    convert_trial_member_on_first_coop_share,
)
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
)


@pytest.mark.django_db
class TestPostConfirmGuardsMemberNumber:
    """``Member._post_confirm`` must skip ``_generate_member_number``
    AND the ``entry_date`` stamp when ``is_trial=True`` — both are
    GenG-Mitglieder artifacts that trial members don't get."""

    def test_full_member_confirmation_assigns_number_and_entry_date(self, tenant):
        member = MemberFactory(member_number=None, is_trial=False, entry_date=None)
        assert member.member_number is None
        assert member.entry_date is None

        member._post_confirm(admin_user=None)
        member.refresh_from_db()

        assert member.member_number is not None
        assert member.entry_date == timezone.localdate(), (
            "Full members must have Eintrittsdatum stamped to today "
            "(GenG §30) at admin confirm."
        )

    def test_trial_member_confirmation_does_not_stamp_either(self, tenant):
        member = MemberFactory(member_number=None, is_trial=True, entry_date=None)
        member._post_confirm(admin_user=None)
        member.refresh_from_db()

        assert (
            member.member_number is None
        ), "Trial members are not Mitglieder under GenG — no Mitgliedsnummer."
        assert (
            member.entry_date is None
        ), "Trial members are not Mitglieder under GenG — no Eintrittsdatum."

    def test_existing_entry_date_is_preserved(self, tenant):
        """Migrated members whose real Eintrittsdatum predates the
        platform have the office set a historical ``entry_date``.
        Confirming such a member must NOT overwrite it with today."""
        historical = timezone.localdate().replace(year=2018)
        member = MemberFactory(
            member_number=None, is_trial=False, entry_date=historical
        )

        member._post_confirm(admin_user=None)
        member.refresh_from_db()

        assert member.entry_date == historical
        assert member.member_number is not None

    def test_activating_linked_user_still_runs_for_trial(self, tenant):
        """The JasminUser activation half of ``_post_confirm`` is
        unrelated to GenG and must NOT be skipped for trial members."""
        user = JasminUserFactory(account_status="pending_approval")
        member = MemberFactory(member_number=None, is_trial=True, user=user)

        member._post_confirm(admin_user=None)
        user.refresh_from_db()

        assert user.account_status == "active"


@pytest.mark.django_db
class TestCoopShareTriggersTrialConversion:
    """CONFIRMING a CoopShare for a trial member auto-converts them — a
    still-pending (unconfirmed) share does NOT, since acquiring *confirmed*
    equity is the GenG admission act (see CoopShare.confirm)."""

    def test_pending_share_does_not_convert_then_confirm_does(self, tenant):
        member = MemberFactory(member_number=None, is_trial=True, entry_date=None)
        assert member.trial_converted_at is None
        assert member.entry_date is None

        # A pending (unconfirmed) self-subscribed share must NOT convert.
        share = CoopShareFactory(member=member, admin_confirmed=False)
        member.refresh_from_db()
        assert member.is_trial is True
        assert member.trial_converted_at is None

        # Confirming it admits the member → trial→full conversion.
        share.confirm(admin_user=None)
        member.refresh_from_db()
        assert member.is_trial is False
        assert member.trial_converted_at is not None
        assert (
            member.member_number is not None
        ), "Conversion must assign the GenG Mitgliedsnummer."
        assert (
            member.entry_date == timezone.localdate()
        ), "Conversion must stamp Eintrittsdatum to today (GenG §30)."

    def test_coop_share_on_full_member_preserves_existing_fields(self, tenant):
        """Confirming a CoopShare for a member who was never on trial does
        not touch ``trial_converted_at`` and does not overwrite
        ``entry_date``."""
        historical = timezone.localdate().replace(year=2018)
        member = MemberFactory(is_trial=False, entry_date=historical)
        original_number = member.member_number

        CoopShareFactory(member=member).confirm(admin_user=None)
        member.refresh_from_db()

        assert member.is_trial is False
        assert (
            member.trial_converted_at is None
        ), "Direct full members should never have a conversion timestamp."
        assert member.member_number == original_number
        assert member.entry_date == historical

    def test_second_coop_share_does_not_re_stamp(self, tenant):
        """Once converted, a second equity acquisition is irrelevant."""
        member = MemberFactory(member_number=None, is_trial=True)
        CoopShareFactory(member=member).confirm(admin_user=None)
        member.refresh_from_db()

        first_stamp = member.trial_converted_at
        first_number = member.member_number
        assert first_stamp is not None

        CoopShareFactory(member=member).confirm(admin_user=None)
        member.refresh_from_db()

        assert member.trial_converted_at == first_stamp
        assert member.member_number == first_number


@pytest.mark.django_db
class TestConvertTrialMemberServiceDirect:
    """Service-level idempotency + return-value contract."""

    def test_returns_true_on_actual_conversion(self, tenant):
        member = MemberFactory(member_number=None, is_trial=True)
        assert convert_trial_member_on_first_coop_share(member) is True
        member.refresh_from_db()
        assert member.is_trial is False

    def test_returns_false_for_already_full_member(self, tenant):
        member = MemberFactory(is_trial=False)
        assert convert_trial_member_on_first_coop_share(member) is False

    def test_double_call_is_idempotent(self, tenant):
        member = MemberFactory(member_number=None, is_trial=True)
        assert convert_trial_member_on_first_coop_share(member) is True
        # The service converts the row in the DB but — since the BIZ-2 row-lock
        # re-fetch — no longer mutates the passed instance in place; read the
        # stamp back from the DB.
        member.refresh_from_db()
        first_stamp = member.trial_converted_at

        assert convert_trial_member_on_first_coop_share(member) is False
        member.refresh_from_db()
        assert member.trial_converted_at == first_stamp


@pytest.mark.django_db(transaction=True)
class TestTrialConvertedEmail:
    """P2-1 (commissioning.trial_converted): the trial→full transition
    schedules a welcome email via ``on_commit``. A successful flip
    fires; a no-op call (already full) does not; a rollback discards
    the scheduled dispatch.
    """

    def _patch_send(self):
        from unittest.mock import patch

        # EmailService is imported lazily inside
        # ``_send_trial_converted_email`` so it is NOT a module-level
        # attribute of ``trial_conversion``. Patch the real module path
        # — every call site goes through the same class.
        return patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        )

    def test_conversion_dispatches_email_after_commit(self, tenant):
        from django.test import TestCase

        member = MemberFactory(
            email="trial@example.org",
            member_number=None,
            is_trial=True,
        )
        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                assert convert_trial_member_on_first_coop_share(member) is True

        send_mock.assert_called_once()
        assert send_mock.call_args.kwargs["slug"] == "commissioning.trial_converted"

    def test_no_op_call_does_not_dispatch(self, tenant):
        from django.test import TestCase

        member = MemberFactory(email="full@example.org", is_trial=False)
        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                assert convert_trial_member_on_first_coop_share(member) is False

        send_mock.assert_not_called()

    def test_member_without_email_does_not_dispatch(self, tenant):
        from django.test import TestCase

        member = MemberFactory(email=None, member_number=None, is_trial=True)
        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                assert convert_trial_member_on_first_coop_share(member) is True

        send_mock.assert_not_called()

    def test_outer_rollback_discards_scheduled_email(self, tenant):
        from django.db import transaction
        from django.test import TestCase

        member = MemberFactory(
            email="rollback@example.org",
            member_number=None,
            is_trial=True,
        )
        with self._patch_send() as send_mock:
            with TestCase.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        convert_trial_member_on_first_coop_share(member)
                        raise RuntimeError("simulated downstream failure")
                except RuntimeError:
                    pass

        send_mock.assert_not_called()
