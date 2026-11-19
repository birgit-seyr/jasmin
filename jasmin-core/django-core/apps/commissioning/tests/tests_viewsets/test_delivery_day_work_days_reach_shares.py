"""A delivery day's work days reach the shares already built for it.

A share copies the day's work days when it is built, so a day synced in without
them, or changed later, leaves its shares behind. Saving the day hands a changed
work day on to the shares of this week and later, where the share has none or
still the old one; a day set for one week stays. The shares are then recomputed,
so a share that missed the harvest list for want of a harvesting day reaches it,
and earlier weeks are left alone.

The clock is frozen on Wednesday 18 November 2026, in ISO week 47.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import TheoreticalHarvest
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)

TUESDAY, WEDNESDAY, THURSDAY = 1, 2, 3
RECOMPUTE = "apps.commissioning.services.recompute.recompute_shares"


@pytest.fixture(autouse=True)
def _wednesday_of_week_47():
    with time_machine.travel(datetime.datetime(2026, 11, 18, 12, 0), tick=False):
        yield


def _share(day, week, **day_fields):
    share = ShareFactory(
        year=2026,
        delivery_week=week,
        delivery_day=day,
        share_type_variation=ShareTypeVariationFactory(),
    )
    for field, value in day_fields.items():
        setattr(share, field, value)
    share.save()
    return share


def _patch(api_client, day, payload):
    return api_client.patch(
        reverse("share_delivery_day-detail", kwargs={"pk": day.pk}),
        payload,
        format="json",
    )


def _three_shares_of(share_content):
    """Three subscribers of the line's share at its station, whatever the
    subscriptions say."""
    share = share_content.share
    totals = {
        "basic": {(share.delivery_day_id, share.share_type_variation_id): Decimal(3)},
        "tour": {},
        "station": {
            (
                share.delivery_day_id,
                share.share_type_variation_id,
                share_content.delivery_station_id,
            ): Decimal(3)
        },
    }
    return patch(
        "apps.commissioning.services.share_content_stock"
        ".batch_get_physical_variation_totals_for_weeks",
        side_effect=lambda physical_variations, year, weeks: {
            week: totals for week in weeks
        },
    )


@pytest.mark.django_db
class TestDeliveryDayWorkDaysReachShares:
    def test_a_work_day_set_later_reaches_this_weeks_and_later_shares(
        self, api_client, tenant
    ):
        day = SharesDeliveryDayFactory(
            day_number=4,
            valid_from=datetime.date(2026, 1, 5),
            default_harvesting_day=None,
            default_packing_day=None,
        )
        last_week = _share(day, 46)
        this_week = _share(day, 47)
        next_week = _share(day, 48)

        with patch(RECOMPUTE) as recompute:
            resp = _patch(
                api_client,
                day,
                {"default_harvesting_day": WEDNESDAY, "default_packing_day": THURSDAY},
            )

        assert resp.status_code == status.HTTP_200_OK, resp.content
        for share in (this_week, next_week):
            share.refresh_from_db()
            assert (share.harvesting_day, share.packing_day) == (WEDNESDAY, THURSDAY)
        last_week.refresh_from_db()
        assert (last_week.harvesting_day, last_week.packing_day) == (None, None)
        recompute.assert_called_once_with({this_week.id, next_week.id})

    def test_a_changed_work_day_leaves_a_day_set_for_one_week(self, api_client, tenant):
        day = SharesDeliveryDayFactory(
            day_number=4,
            valid_from=datetime.date(2026, 1, 5),
            default_harvesting_day=TUESDAY,
        )
        inherited = _share(day, 47)
        set_for_its_week = _share(day, 48, harvesting_day=THURSDAY)

        with patch(RECOMPUTE) as recompute:
            resp = _patch(api_client, day, {"default_harvesting_day": WEDNESDAY})

        assert resp.status_code == status.HTTP_200_OK, resp.content
        inherited.refresh_from_db()
        set_for_its_week.refresh_from_db()
        assert inherited.harvesting_day == WEDNESDAY
        assert set_for_its_week.harvesting_day == THURSDAY
        recompute.assert_called_once_with({inherited.id})

    def test_a_save_that_changes_no_work_day_recomputes_nothing(
        self, api_client, tenant
    ):
        day = SharesDeliveryDayFactory(
            day_number=4, valid_from=datetime.date(2026, 1, 5), number_of_tours=1
        )
        _share(day, 47)

        with patch(RECOMPUTE) as recompute:
            resp = _patch(api_client, day, {"number_of_tours": 2})

        assert resp.status_code == status.HTTP_200_OK, resp.content
        recompute.assert_not_called()

    def test_a_share_reaches_the_harvest_list_once_its_day_has_a_harvesting_day(
        self, api_client, tenant
    ):
        StorageFactory(is_short_term_harvest_storage=True)
        day = SharesDeliveryDayFactory(
            day_number=4,
            valid_from=datetime.date(2026, 1, 5),
            default_harvesting_day=None,
        )
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=day)
        # Only a forecast line is harvested; a line without one is bought in.
        article = ShareArticleFactory()
        line = ShareContentFactory(
            share=_share(day, 47),
            share_article=article,
            delivery_station=station,
            forecast=ForecastFactory(
                share_article=article, year=2026, delivery_week=47, size="M"
            ),
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )

        with _three_shares_of(line):
            ShareContentService().recompute_for_shares([line.share_id])
            assert not TheoreticalHarvest.objects.filter(share_content=line).exists()

            resp = _patch(api_client, day, {"default_harvesting_day": THURSDAY})

        assert resp.status_code == status.HTTP_200_OK, resp.content
        harvest = TheoreticalHarvest.objects.get(share_content=line)
        # 5 kg for each of the three shares, on Thursday of this week.
        assert (harvest.day_number, harvest.amount) == (THURSDAY, Decimal("15"))
