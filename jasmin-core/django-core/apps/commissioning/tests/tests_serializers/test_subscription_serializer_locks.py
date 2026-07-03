"""Tests for the ``SubscriptionSerializer`` cancellation lockdown.

The cancellation triplet (``cancelled_at``, ``cancelled_effective_at``,
``cancelled_by``) is stamped by
``SubscriptionService.cancel_subscription`` via the ``POST
/api/commissioning/subscriptions/{id}/cancel/`` action. Going through
the service is the ONLY way to get correct side effects:

  * ``cancelled_by`` populated → audit trail intact
  * future ``ShareDelivery`` rows deleted
  * PLANNED ``ChargeSchedule`` rows dropped, ISSUED/PAID preserved
  * ``recompute_shares`` fires for affected weeks

The frontend Abos.tsx no longer lets office users edit
``cancelled_effective_at`` inline — they're routed through a Cancel
button + modal that hits the action endpoint. This test is the
server-side belt-and-braces guard against direct API PATCH calls.

If you add a new cancellation field, make sure it's in
``SubscriptionSerializer.Meta.read_only_fields`` AND extend the
parametrised test below.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.serializers import SubscriptionSerializer
from apps.commissioning.tests.factories import JasminUserFactory, SubscriptionFactory

_LOCKED_FIELDS = ("cancelled_at", "cancelled_effective_at", "cancelled_by")


@pytest.mark.django_db
class TestCancellationFieldsAreReadOnly:
    """PATCH cannot mutate the cancellation triplet directly — the
    only legitimate writer is ``SubscriptionService.cancel_subscription``.

    DRF serializers DROP read_only fields silently on input rather than
    raising — so the assertion is "the field on the instance didn't
    change", not "the call raised".
    """

    def _make_subscription(self, **overrides):
        # ``valid_from`` must be a Monday and ``valid_until`` must be a
        # Sunday — enforced by ``TimeBoundMixin``. Picking real dates so
        # the fixture matches the model invariants.
        defaults = {
            "valid_from": datetime.date(2026, 1, 5),  # Monday
            "valid_until": datetime.date(2026, 12, 27),  # Sunday
            "admin_confirmed": True,
            "admin_confirmed_at": timezone.now(),
        }
        defaults.update(overrides)
        return SubscriptionFactory(**defaults)

    def test_cancelled_effective_at_patch_is_silently_dropped(self, tenant):
        subscription = self._make_subscription()
        assert subscription.cancelled_effective_at is None

        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"cancelled_effective_at": "2026-06-30"},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        subscription.refresh_from_db()
        # The field stayed None because it's read-only on input.
        assert subscription.cancelled_effective_at is None

    def test_cancelled_at_patch_is_silently_dropped(self, tenant):
        subscription = self._make_subscription()
        assert subscription.cancelled_at is None

        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"cancelled_at": timezone.now().isoformat()},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        subscription.refresh_from_db()
        assert subscription.cancelled_at is None

    def test_cancelled_by_patch_is_silently_dropped(self, tenant):
        subscription = self._make_subscription()
        actor = JasminUserFactory()

        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"cancelled_by": actor.pk},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        subscription.refresh_from_db()
        assert subscription.cancelled_by is None

    def test_admin_confirmed_locks_every_field(self, tenant):
        """Lockdown is total — any PATCH attempt on an admin-confirmed
        row raises ``LockedAfterAdminConfirmation``. Only the cancel
        action (which bypasses the serializer) may end the term."""
        from apps.commissioning.errors import LockedAfterAdminConfirmation

        subscription = self._make_subscription(quantity=1)
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"quantity": 3},
            partial=True,
        )
        with pytest.raises(LockedAfterAdminConfirmation):
            serializer.is_valid(raise_exception=True)

    def test_draft_subscription_still_patches_through(self, tenant):
        """Sanity check: the lockdown only fires for admin-confirmed
        rows — drafts remain freely editable."""
        subscription = SubscriptionFactory(
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
            admin_confirmed=False,
            quantity=1,
        )
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"quantity": 3},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        subscription.refresh_from_db()
        assert subscription.quantity == 3

    def test_admin_confirmed_cannot_be_forged_on_draft(self, tenant):
        """SEC-1: a plain PATCH must not be able to flip a DRAFT to
        admin_confirmed=True — that would bypass the confirm action's capacity
        backstop + share/delivery/charge materialisation. The field is
        read-only, so DRF drops it silently (the row stays a draft)."""
        subscription = SubscriptionFactory(
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
            admin_confirmed=False,
            quantity=1,
        )
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"admin_confirmed": True},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()
        subscription.refresh_from_db()
        assert subscription.admin_confirmed is False

    @pytest.mark.parametrize("field", _LOCKED_FIELDS)
    def test_field_appears_in_read_only_fields(self, field):
        """Lock-down via class metadata so even an accidentally-added
        explicit field declaration would have to opt back in."""
        assert field in SubscriptionSerializer.Meta.read_only_fields


@pytest.mark.django_db
class TestOpenEndedSubscriptionForbidden:
    """CHG-1: a subscription must carry an end date (``valid_until``). An
    open-ended sub materialises no deliveries and silently never bills, so the
    serializer rejects creating one or clearing the end date on an existing one.
    """

    def _unconfirmed(self, **overrides):
        # admin_confirmed=False so the confirmation lockdown doesn't pre-empt the
        # end-date check.
        defaults = {
            "valid_from": datetime.date(2026, 1, 5),  # Monday
            "valid_until": datetime.date(2026, 12, 27),  # Sunday
            "admin_confirmed": False,
        }
        defaults.update(overrides)
        return SubscriptionFactory(**defaults)

    def test_patch_clearing_valid_until_is_rejected(self, tenant):
        from apps.commissioning.errors import OpenEndedSubscriptionNotAllowed

        sub = self._unconfirmed()
        serializer = SubscriptionSerializer(
            instance=sub, data={"valid_until": None}, partial=True
        )
        # JasminError (not a DRF ValidationError) propagates through is_valid().
        with pytest.raises(OpenEndedSubscriptionNotAllowed):
            serializer.is_valid()

    def test_patch_not_touching_valid_until_passes(self, tenant):
        # A partial update that leaves valid_until alone keeps the existing end
        # date and must NOT trip the guard.
        sub = self._unconfirmed()
        serializer = SubscriptionSerializer(
            instance=sub, data={"quantity": 2}, partial=True
        )
        assert serializer.is_valid(), serializer.errors
