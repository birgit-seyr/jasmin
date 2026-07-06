"""Regression: admin-confirming a Subscription must materialise charges."""

from __future__ import annotations

import datetime

import pytest

from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    PaymentCycleFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)
from apps.payments.models import ChargeSchedule


@pytest.mark.django_db
class TestAdminConfirmMaterializes:
    def _validated(self, *, valid_until):
        member = MemberFactory()
        variation = ShareTypeVariationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        return {
            "member": member.pk,
            "share_type_variation": variation.pk,
            "valid_from": datetime.date(2026, 4, 6),
            "valid_until": valid_until,
            "quantity": 1,
            "payment_cycle": PaymentCycleFactory(),
            "default_delivery_station_day": station_day,
            "price_per_delivery": "10.00",
        }

    def test_confirm_with_full_data_creates_charges(self, tenant):
        svc = SubscriptionService()
        sub = svc.create_bare_subscription(
            self._validated(valid_until=datetime.date(2026, 4, 26))
        )
        assert ChargeSchedule.objects.filter(subscription=sub).count() == 0

        sub.confirm(admin_user=JasminUserFactory(), save=True)

        # Should now have at least one PLANNED row.
        assert ChargeSchedule.objects.filter(subscription=sub).count() >= 1

    def test_open_ended_subscription_is_rejected(self, tenant):
        """A subscription without valid_until is rejected outright — no silent
        zero-charge sub."""
        from apps.commissioning.errors import OpenEndedSubscriptionNotAllowed

        svc = SubscriptionService()
        with pytest.raises(OpenEndedSubscriptionNotAllowed):
            svc.create_bare_subscription(self._validated(valid_until=None))

    def test_materialize_stamps_is_opted_in_for_on_by_default_optin(self, tenant):
        """Regression: bulk_create bypasses ShareDelivery.save(), which stamps
        is_opted_in from the variation's default_optin_state. An on-by-default
        opt-in variation was materialised opted-OUT, silently suppressing both
        its billing and its production demand."""
        from apps.commissioning.models import ShareDelivery

        member = MemberFactory()
        variation = ShareTypeVariationFactory(
            requires_optin=True, default_optin_state=True
        )
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
        validated = {
            "member": member.pk,
            "share_type_variation": variation.pk,
            "valid_from": datetime.date(2026, 4, 6),
            "valid_until": datetime.date(2026, 4, 26),
            "quantity": 1,
            "payment_cycle": PaymentCycleFactory(),
            "default_delivery_station_day": station_day,
            "price_per_delivery": "10.00",
        }
        sub = SubscriptionService().create_bare_subscription(validated)
        sub.confirm(admin_user=JasminUserFactory(), save=True)

        deliveries = ShareDelivery.objects.filter(subscription=sub)
        assert deliveries.exists()
        assert all(d.is_opted_in for d in deliveries)
