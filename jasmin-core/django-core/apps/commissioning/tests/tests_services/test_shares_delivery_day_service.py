"""Tests for SharesDeliveryDayService."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from apps.commissioning.services.shares_delivery_day_service import (
    SharesDeliveryDayService,
    _is_future_and_within_validity,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)


# ---------------------------------------------------------------------------
# _is_future_and_within_validity  (pure — no DB)
# ---------------------------------------------------------------------------
class TestIsFutureAndWithinValidity:
    def test_future_within_bounds(self):
        tb = MagicMock()
        tb.valid_from = datetime.date(2026, 1, 1)
        tb.valid_until = datetime.date(2026, 12, 31)
        assert _is_future_and_within_validity(
            datetime.date(2026, 6, 1), datetime.date(2026, 1, 1), tb
        )

    def test_past_date_rejected(self):
        tb = MagicMock()
        tb.valid_from = datetime.date(2026, 1, 1)
        tb.valid_until = datetime.date(2026, 12, 31)
        assert not _is_future_and_within_validity(
            datetime.date(2025, 6, 1), datetime.date(2026, 1, 1), tb
        )

    def test_same_day_rejected(self):
        """record_date == today should return False (not strictly future)."""
        tb = MagicMock()
        tb.valid_from = None
        tb.valid_until = None
        assert not _is_future_and_within_validity(
            datetime.date(2026, 5, 1), datetime.date(2026, 5, 1), tb
        )

    def test_before_valid_from(self):
        tb = MagicMock()
        tb.valid_from = datetime.date(2026, 6, 1)
        tb.valid_until = None
        assert not _is_future_and_within_validity(
            datetime.date(2026, 5, 1), datetime.date(2026, 1, 1), tb
        )

    def test_after_valid_until(self):
        tb = MagicMock()
        tb.valid_from = None
        tb.valid_until = datetime.date(2026, 3, 1)
        assert not _is_future_and_within_validity(
            datetime.date(2026, 6, 1), datetime.date(2026, 1, 1), tb
        )

    def test_no_bounds(self):
        tb = MagicMock()
        tb.valid_from = None
        tb.valid_until = None
        assert _is_future_and_within_validity(
            datetime.date(2026, 6, 1), datetime.date(2026, 1, 1), tb
        )


# ---------------------------------------------------------------------------
# update_delivery_station_days
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateDeliveryStationDays:
    def test_closes_old_and_creates_new(self, tenant):
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )
        dsd = DeliveryStationDayFactory(delivery_day=old_day, tour_number=1)

        valid_from = datetime.date(2026, 6, 29)
        new_copies = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_day,
            existing_delivery_day=old_day,
            validated_data={"valid_from": valid_from},
        )

        # Old station day should have valid_until set
        dsd.refresh_from_db()
        assert dsd.valid_until == valid_from - datetime.timedelta(days=1)

        # New copy should exist
        assert len(new_copies) == 1
        assert new_copies[0].delivery_day == new_day
        assert new_copies[0].valid_from == valid_from

    def test_empty_when_no_station_days(self, tenant):
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )

        result = SharesDeliveryDayService.update_delivery_station_days(
            instance=new_day,
            existing_delivery_day=old_day,
            validated_data={"valid_from": datetime.date(2026, 6, 29)},
        )
        assert result == []


# ---------------------------------------------------------------------------
# update_shares_for_delivery_day
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateSharesForDeliveryDay:
    def test_updates_future_shares(self, tenant):
        variation = ShareTypeVariationFactory()
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )

        # Create a share far in the future
        share = ShareFactory(
            year=2030,
            delivery_week=10,
            delivery_day=old_day,
            share_type_variation=variation,
        )

        count = SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_day,
            old_delivery_day=old_day,
        )

        assert count == 1
        share.refresh_from_db()
        assert share.delivery_day == new_day

    def test_skips_past_shares(self, tenant):
        variation = ShareTypeVariationFactory()
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )

        # Create a share in the past
        ShareFactory(
            year=2020,
            delivery_week=10,
            delivery_day=old_day,
            share_type_variation=variation,
        )

        count = SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_day,
            old_delivery_day=old_day,
        )
        assert count == 0

    def test_zero_when_day_numbers_differ(self, tenant):
        old_day = SharesDeliveryDayFactory(day_number=2)
        new_day = SharesDeliveryDayFactory(day_number=3)

        count = SharesDeliveryDayService.update_shares_for_delivery_day(
            new_delivery_day=new_day,
            old_delivery_day=old_day,
        )
        assert count == 0

    def test_recomputes_reassigned_shares(self, tenant):
        """Reassigning a share's recompute-relevant day fields during
        succession must trigger a recompute. Forecast/default-only shares
        have no ShareDelivery, so the sibling
        update_share_deliveries_for_delivery_day never rebuilds them — this
        method must, or their theoreticals/movements stay computed off the
        old days."""
        variation = ShareTypeVariationFactory()
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )
        share = ShareFactory(
            year=2030,
            delivery_week=10,
            delivery_day=old_day,
            share_type_variation=variation,
        )

        # Patch the source module: the service uses a deferred
        # `from .recompute import recompute_shares` import.
        with patch(
            "apps.commissioning.services.recompute.recompute_shares"
        ) as mock_recompute:
            count = SharesDeliveryDayService.update_shares_for_delivery_day(
                new_delivery_day=new_day,
                old_delivery_day=old_day,
            )

        assert count == 1
        mock_recompute.assert_called_once()
        recomputed_ids = mock_recompute.call_args.args[0]
        assert share.id in recomputed_ids

    def test_does_not_recompute_when_no_future_shares(self, tenant):
        """No future shares to reassign -> no recompute query is issued."""
        variation = ShareTypeVariationFactory()
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )
        ShareFactory(
            year=2020,
            delivery_week=10,
            delivery_day=old_day,
            share_type_variation=variation,
        )

        with patch(
            "apps.commissioning.services.recompute.recompute_shares"
        ) as mock_recompute:
            count = SharesDeliveryDayService.update_shares_for_delivery_day(
                new_delivery_day=new_day,
                old_delivery_day=old_day,
            )

        assert count == 0
        mock_recompute.assert_not_called()


# ---------------------------------------------------------------------------
# update_share_deliveries_for_delivery_day
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateShareDeliveriesForDeliveryDay:
    def test_remaps_station_days(self, tenant):
        variation = ShareTypeVariationFactory()
        old_day = SharesDeliveryDayFactory(
            day_number=2, valid_until=datetime.date(2026, 6, 28)
        )
        new_day = SharesDeliveryDayFactory(
            day_number=2, valid_from=datetime.date(2026, 6, 29)
        )

        old_dsd = DeliveryStationDayFactory(delivery_day=old_day, tour_number=1)
        new_dsd = DeliveryStationDayFactory(
            delivery_day=new_day,
            delivery_station=old_dsd.delivery_station,
            tour_number=1,
        )

        share = ShareFactory(
            year=2030,
            delivery_week=10,
            delivery_day=old_day,
            share_type_variation=variation,
        )
        sd = ShareDeliveryFactory(share=share, delivery_station_day=old_dsd)

        count = SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_day,
            old_delivery_day=old_day,
        )

        assert count == 1
        sd.refresh_from_db()
        assert sd.delivery_station_day == new_dsd

    def test_zero_when_no_old_day(self, tenant):
        new_day = SharesDeliveryDayFactory(day_number=2)
        count = SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_day,
            old_delivery_day=None,
        )
        assert count == 0

    def test_zero_when_day_numbers_differ(self, tenant):
        old_day = SharesDeliveryDayFactory(day_number=2)
        new_day = SharesDeliveryDayFactory(day_number=3)

        count = SharesDeliveryDayService.update_share_deliveries_for_delivery_day(
            new_delivery_day=new_day,
            old_delivery_day=old_day,
        )
        assert count == 0
