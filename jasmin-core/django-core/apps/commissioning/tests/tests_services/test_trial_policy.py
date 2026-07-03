"""Server-side enforcement of the tenant's trial-related settings.

The decision tree locked here:

    Member(is_trial=True):
      allowed iff allows_trial_subscriptions
                  AND allows_trial_subscriptions_for_trial_members.
      Reason: a trial member exists only to hold a trial sub; if
      either flag is off, the concept is moot.

    Subscription(is_trial=True):
      ├── allows_trial_subscriptions=False → reject
      └── True  → if member.is_trial AND
                    NOT allows_trial_subscriptions_for_trial_members:
                  reject (trial member can't hold trial sub).
                else allow.

``Subscription.member`` is structurally NOT NULL — the old
``only_members_can_have_subscriptions`` flag was a no-op and got
dropped pre-squash. ``allows_trial_members`` was likewise dropped
(pre-squash) because it was fully derivable from the surviving pair.

Settings missing entirely (no current overlay row) defaults to
"allow" — a freshly-provisioned tenant must remain usable before
the first configuration save.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.errors import (
    TrialMembersNotAllowed,
    TrialSubscriptionsNotAllowed,
    TrialSubscriptionsOnlyForFullMembers,
)
from apps.commissioning.services.trial_policy import (
    assert_member_creation_allowed,
    assert_subscription_creation_allowed,
)
from apps.commissioning.tests.factories import MemberFactory
from apps.shared.tenants.models import TenantSettings


def _make_settings(tenant, **kwargs) -> TenantSettings:
    """Tiny helper that materialises a current TenantSettings row.

    Any field passed as kwargs overrides the model default; everything
    else inherits the default (which is "allow" for the trial flags).
    """
    return TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        **kwargs,
    )


@pytest.mark.django_db
class TestAssertMemberCreationAllowed:
    """Trial-member creation = ``allows_trial_subscriptions`` AND
    ``allows_trial_subscriptions_for_trial_members``."""

    def test_non_trial_creation_always_passes(self, tenant):
        _make_settings(
            tenant,
            allows_trial_subscriptions=False,
            allows_trial_subscriptions_for_trial_members=False,
        )
        assert_member_creation_allowed(is_trial=False)

    def test_trial_creation_passes_when_both_flags_on(self, tenant):
        _make_settings(
            tenant,
            allows_trial_subscriptions=True,
            allows_trial_subscriptions_for_trial_members=True,
        )
        assert_member_creation_allowed(is_trial=True)

    def test_trial_creation_raises_when_subscriptions_disabled(self, tenant):
        _make_settings(
            tenant,
            allows_trial_subscriptions=False,
            allows_trial_subscriptions_for_trial_members=True,
        )
        with pytest.raises(TrialMembersNotAllowed):
            assert_member_creation_allowed(is_trial=True)

    def test_trial_creation_raises_when_only_full_members_can_hold_trial_subs(
        self, tenant
    ):
        # No work for a trial member to do → reject.
        _make_settings(
            tenant,
            allows_trial_subscriptions=True,
            allows_trial_subscriptions_for_trial_members=False,
        )
        with pytest.raises(TrialMembersNotAllowed):
            assert_member_creation_allowed(is_trial=True)

    def test_no_overlay_defaults_to_allow(self, tenant):
        assert_member_creation_allowed(is_trial=True)


@pytest.mark.django_db
class TestAssertSubscriptionCreationAllowed:
    def test_non_trial_subscription_always_passes(self, tenant):
        _make_settings(
            tenant,
            allows_trial_subscriptions=False,
            allows_trial_subscriptions_for_trial_members=False,
        )
        member = MemberFactory(is_trial=True)
        assert_subscription_creation_allowed(is_trial=False, member=member)

    def test_trial_subscription_raises_when_disabled(self, tenant):
        _make_settings(tenant, allows_trial_subscriptions=False)
        member = MemberFactory()
        with pytest.raises(TrialSubscriptionsNotAllowed):
            assert_subscription_creation_allowed(is_trial=True, member=member)

    def test_full_member_can_always_hold_trial_sub_when_subs_enabled(self, tenant):
        # Even when allows_trial_subscriptions_for_trial_members=False, a full
        # member is unaffected — that branch only restricts trial
        # MEMBERS from holding trial subs.
        _make_settings(
            tenant,
            allows_trial_subscriptions=True,
            allows_trial_subscriptions_for_trial_members=False,
        )
        full_member = MemberFactory(is_trial=False)
        assert_subscription_creation_allowed(is_trial=True, member=full_member)

    def test_trial_member_can_hold_trial_sub_when_flag_on(self, tenant):
        _make_settings(
            tenant,
            allows_trial_subscriptions=True,
            allows_trial_subscriptions_for_trial_members=True,
        )
        trial_member = MemberFactory(is_trial=True)
        assert_subscription_creation_allowed(is_trial=True, member=trial_member)

    def test_trial_member_blocked_when_flag_off(self, tenant):
        _make_settings(
            tenant,
            allows_trial_subscriptions=True,
            allows_trial_subscriptions_for_trial_members=False,
        )
        trial_member = MemberFactory(is_trial=True)
        with pytest.raises(TrialSubscriptionsOnlyForFullMembers):
            assert_subscription_creation_allowed(is_trial=True, member=trial_member)

    def test_no_overlay_defaults_to_allow(self, tenant):
        trial_member = MemberFactory(is_trial=True)
        full_member = MemberFactory(is_trial=False)
        assert_subscription_creation_allowed(is_trial=True, member=trial_member)
        assert_subscription_creation_allowed(is_trial=True, member=full_member)
