"""Tests for ``SubscriptionSerializer``'s solidarity-pricing floor —
specifically the TRIAL branch, which floors a trial price against the
variation's ``solidarity_min_price_per_delivery_if_trial`` (falling back to
the trial reference) instead of the regular pair.

The floor is validated the same way for the office abos path and the member
self-service path (both go through ``SubscriptionSerializer.validate``). Since
the member path forces ``is_trial=False``, the trial branch is exercised here
by re-sending ``price_per_delivery`` on an EXISTING trial draft: a partial
PATCH skips the lead-time guard (``valid_from`` unchanged) and reaches the
floor block with ``is_trial`` read from the instance. The floor is resolved at
the subscription's ``valid_from`` window (a fixed date), so the outcome does
not depend on the wall clock; the clock is frozen anyway for deterministic
fixture creation on a Monday.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine

from apps.commissioning.errors import SolidarityPriceBelowMinimum
from apps.commissioning.serializers import SubscriptionSerializer
from apps.commissioning.tests.factories import (
    ShareTypeVariationFactory,
    ShareTypeVariationGrossPriceFactory,
    SubscriptionFactory,
)

# A Monday comfortably before any relative math, matching the subscription's
# ``valid_from`` so the gross-price window resolves against a fixed date.
_FROZEN = datetime.date(2026, 1, 5)
_VALID_FROM = datetime.date(2026, 1, 5)  # Monday
_VALID_UNTIL = datetime.date(2026, 12, 27)  # Sunday


@pytest.mark.django_db
class TestSubscriptionSolidarityTrialFloor:
    @pytest.fixture(autouse=True)
    def _freeze(self):
        with time_machine.travel(_FROZEN, tick=False):
            yield

    def _enable_solidarity(self, tenant):
        from django.utils import timezone

        from apps.shared.tenants.models import TenantSettings

        return TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            allows_solidarity_pricing=True,
        )

    def _variation_with_prices(self, **gross_kwargs):
        variation = ShareTypeVariationFactory()
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=_VALID_FROM,
            **gross_kwargs,
        )
        return variation

    def _draft(self, variation, *, is_trial):
        return SubscriptionFactory(
            share_type_variation=variation,
            is_trial=is_trial,
            admin_confirmed=False,
            valid_from=_VALID_FROM,
            valid_until=_VALID_UNTIL,
        )

    def _validate_price(self, subscription, price):
        serializer = SubscriptionSerializer(
            instance=subscription,
            data={"price_per_delivery": price},
            partial=True,
        )
        # Mirrors the office/member flow: validate raises the JasminError which
        # DRF maps to a 400 with the stable code.
        serializer.is_valid(raise_exception=True)

    # ---- Present branch: an explicit trial floor is set. -------------------

    def test_trial_floor_accepts_price_below_regular_floor(self, tenant):
        # regular floor 7.00, trial floor 5.00. A trial priced 5.50 is BELOW
        # the regular floor but AT/ABOVE the trial floor → accepted. This proves
        # the trial floor (5.00) governs a trial, not the regular one (7.00).
        self._enable_solidarity(tenant)
        variation = self._variation_with_prices(
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
            price_per_delivery_if_trial=Decimal("6.00"),
            solidarity_min_price_per_delivery_if_trial=Decimal("5.00"),
        )
        subscription = self._draft(variation, is_trial=True)
        # Does not raise → the price cleared the trial floor.
        self._validate_price(subscription, "5.50")

    def test_trial_rejects_price_below_trial_floor(self, tenant):
        # Same setup; 4.50 is below the trial floor (5.00) → rejected.
        self._enable_solidarity(tenant)
        variation = self._variation_with_prices(
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
            price_per_delivery_if_trial=Decimal("6.00"),
            solidarity_min_price_per_delivery_if_trial=Decimal("5.00"),
        )
        subscription = self._draft(variation, is_trial=True)
        with pytest.raises(SolidarityPriceBelowMinimum):
            self._validate_price(subscription, "4.50")

    def test_regular_sub_rejects_same_price_proving_branch_differs(self, tenant):
        # The SAME 5.50 that a trial accepts is rejected for a NON-trial sub,
        # because the regular floor (7.00) applies — proving the two branches
        # resolve different floors (not a trials-skip-the-floor no-op).
        self._enable_solidarity(tenant)
        variation = self._variation_with_prices(
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
            price_per_delivery_if_trial=Decimal("6.00"),
            solidarity_min_price_per_delivery_if_trial=Decimal("5.00"),
        )
        subscription = self._draft(variation, is_trial=False)
        with pytest.raises(SolidarityPriceBelowMinimum):
            self._validate_price(subscription, "5.50")

    # ---- Absent branch: no explicit trial floor → trial reference. ---------

    def test_trial_without_explicit_floor_falls_back_to_trial_reference(self, tenant):
        # No trial floor set → the floor falls back to the trial REFERENCE
        # (6.00). 5.50 is below it → rejected. (A fixture that set the trial
        # floor would never test this fallback, so it's exercised explicitly.)
        self._enable_solidarity(tenant)
        variation = self._variation_with_prices(
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
            price_per_delivery_if_trial=Decimal("6.00"),
            # solidarity_min_price_per_delivery_if_trial left NULL.
        )
        subscription = self._draft(variation, is_trial=True)
        with pytest.raises(SolidarityPriceBelowMinimum):
            self._validate_price(subscription, "5.50")

    def test_trial_without_explicit_floor_accepts_at_trial_reference(self, tenant):
        # Same NULL-floor setup; 6.00 == the trial reference → accepted.
        self._enable_solidarity(tenant)
        variation = self._variation_with_prices(
            price_per_delivery=Decimal("10.00"),
            solidarity_min_price_per_delivery=Decimal("7.00"),
            price_per_delivery_if_trial=Decimal("6.00"),
        )
        subscription = self._draft(variation, is_trial=True)
        self._validate_price(subscription, "6.00")
