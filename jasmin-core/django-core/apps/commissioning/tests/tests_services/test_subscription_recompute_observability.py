"""BIZ-4: a recompute failure during subscription materialization must surface
WHICH subscription failed (it previously bubbled up context-free) while still
rolling back the just-created ShareDeliveries."""

from __future__ import annotations

import datetime
import logging

import pytest

from apps.commissioning.models import ShareDelivery
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.members import PaymentCycleFactory


def _draft_subscription():
    delivery_day = SharesDeliveryDayFactory()
    delivery_station_day = DeliveryStationDayFactory(delivery_day=delivery_day)
    share_type = ShareTypeFactory(share_option="HARVEST_SHARE")
    variation = ShareTypeVariationFactory(share_type=share_type)
    return SubscriptionFactory(
        share_type_variation=variation,
        default_delivery_station_day=delivery_station_day,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 1, 11),
        quantity=1,
        payment_cycle=PaymentCycleFactory(),
    )


@pytest.mark.django_db
class TestRecomputeFailureObservability:
    def test_recompute_failure_logs_subscription_and_rolls_back(
        self, tenant, monkeypatch, caplog
    ):
        sub = _draft_subscription()

        def boom(*_args, **_kwargs):
            raise ValueError("forecast missing")

        # The service does a function-local ``from .recompute import
        # recompute_shares`` per call, so patching the source symbol takes.
        monkeypatch.setattr(
            "apps.commissioning.services.recompute.recompute_shares", boom
        )

        # apps.* loggers set propagate=False, so caplog's root handler never
        # sees them — attach caplog's handler to the service logger directly
        # (same pattern as test_services_charge_schedule.py).
        service_logger = logging.getLogger(
            "apps.commissioning.services.subscription_service"
        )
        service_logger.addHandler(caplog.handler)
        try:
            with pytest.raises(ValueError, match="forecast missing"):
                SubscriptionService().materialize_confirmed_subscription(sub)
        finally:
            service_logger.removeHandler(caplog.handler)

        # (a) the subscription identifier is now in the log …
        assert any(
            f"recompute failed for subscription={sub.pk}" in r.getMessage()
            for r in caplog.records
        ), f"no contextual recompute-failure log for subscription={sub.pk}"

        # (b) … and the rollback was NOT swallowed: no deliveries persisted.
        assert ShareDelivery.objects.filter(subscription=sub).count() == 0
