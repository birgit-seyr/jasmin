"""BL-14: assert_delivery_station_day_covers_subscription must verify the default
DeliveryStationDay's successor chain covers the whole subscription window
CONTIGUOUSLY — not merely that some later DSD exists. A gap, or a successor
that itself ends before the subscription, must be rejected."""

from __future__ import annotations

import datetime

import pytest

from apps.commissioning.errors import SubscriptionDeliveryStationDayOutOfRange
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    SharesDeliveryDayFactory,
)

_MON = datetime.date(2026, 1, 5)
_DEFAULT_END = datetime.date(2026, 2, 1)  # Sunday
_CONTIGUOUS_START = datetime.date(2026, 2, 2)  # Monday after the default ends
_GAP_START = datetime.date(2026, 3, 2)  # Monday, weeks later → leaves a gap
_EARLY_END = datetime.date(2026, 3, 1)  # Sunday, before the subscription ends
_SUB_END = datetime.date(2026, 4, 5)  # Sunday


@pytest.mark.django_db
class TestAssertDsdCoversSubscription:
    def _default_dsd(self):
        station = DeliveryStationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        default = DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=_MON,
            valid_until=_DEFAULT_END,
        )
        return station, day, default

    def test_gap_in_successor_chain_is_rejected(self, tenant):
        station, day, default = self._default_dsd()
        # Successor starts weeks after the default ends — weeks in between have
        # no valid DSD.
        DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=_GAP_START,
            valid_until=None,
        )
        with pytest.raises(SubscriptionDeliveryStationDayOutOfRange):
            SubscriptionService.assert_delivery_station_day_covers_subscription(
                delivery_station_day=default, valid_from=_MON, valid_until=_SUB_END
            )

    def test_successor_ending_early_is_rejected(self, tenant):
        station, day, default = self._default_dsd()
        # Contiguous, but the successor itself ends before the subscription.
        DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=_CONTIGUOUS_START,
            valid_until=_EARLY_END,
        )
        with pytest.raises(SubscriptionDeliveryStationDayOutOfRange):
            SubscriptionService.assert_delivery_station_day_covers_subscription(
                delivery_station_day=default, valid_from=_MON, valid_until=_SUB_END
            )

    def test_contiguous_open_successor_is_accepted(self, tenant):
        station, day, default = self._default_dsd()
        DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=day,
            valid_from=_CONTIGUOUS_START,
            valid_until=None,  # open → covers the rest of the window
        )
        # No raise.
        SubscriptionService.assert_delivery_station_day_covers_subscription(
            delivery_station_day=default, valid_from=_MON, valid_until=_SUB_END
        )
