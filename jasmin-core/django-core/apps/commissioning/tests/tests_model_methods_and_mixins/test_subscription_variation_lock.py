"""Subscription.share_type_variation is fixed once the subscription is
admin-confirmed.

Confirmation materialises Shares / ShareDeliveries keyed by the variation, so
changing it afterwards would orphan that data (packing lists would show the
wrong variation). An unconfirmed draft (incl. an auto-renewal the office is
still reviewing) may still be re-pointed. The model-level ``clean()`` guard is
the backstop against a direct ORM ``save()``.
"""

from __future__ import annotations

import pytest

from apps.commissioning.errors import SubscriptionVariationLocked
from apps.commissioning.tests.factories import (
    ShareTypeVariationFactory,
    SubscriptionFactory,
)


@pytest.mark.django_db
class TestSubscriptionVariationLock:
    def test_change_blocked_once_confirmed(self, tenant):
        subscription = SubscriptionFactory(admin_confirmed=True)
        subscription.share_type_variation = ShareTypeVariationFactory()
        with pytest.raises(SubscriptionVariationLocked):
            subscription.save()

    def test_change_allowed_while_draft(self, tenant):
        # An unconfirmed draft (still being set up) can freely change variation.
        subscription = SubscriptionFactory(admin_confirmed=False)
        other = ShareTypeVariationFactory()
        subscription.share_type_variation = other
        subscription.save()
        subscription.refresh_from_db()
        assert subscription.share_type_variation_id == other.pk

    def test_unrelated_save_not_blocked(self, tenant):
        # Changing an unrelated field on a confirmed sub doesn't touch the
        # variation → allowed.
        subscription = SubscriptionFactory(admin_confirmed=True)
        subscription.cancellation_reason = "moved away"
        subscription.save()
        subscription.refresh_from_db()
        assert subscription.cancellation_reason == "moved away"
