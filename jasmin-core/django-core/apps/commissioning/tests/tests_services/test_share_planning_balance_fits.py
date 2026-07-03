"""Integration test: share planning -> theoreticals -> real stock input ->
running balance "fits" on the next day / next week.

End-to-end exercise of the derived-stock pipeline:

  ShareContent + ShareDelivery demand
      --> recompute_shares  (builds Theoretical* objects + a -SHARECONTENT demand
                             movement + a +HARVEST theoretical-supply movement)
      --> the office enters a real INVENTORY "current stock" count via the
          current-stock endpoint
      --> SnapshotService.compute_balance(up_to=<future>) projects the stock at
          each future point, and we assert it stays consistent ("fits", >= 0).

For year 2026 / ISO week 20 recompute dates the supply on Tue (2026-05-12) and
the demand on Wed (2026-05-13); the office counts real stock on Tue evening.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.commissioning.models import (
    MovementShareArticle,
    ShareContent,
    TheoreticalHarvest,
)
from apps.commissioning.models.choices_text import MovementTypeOptions
from apps.commissioning.services.recompute import recompute_shares
from apps.commissioning.services.snapshot_service import SnapshotService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareArticleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)
from apps.commissioning.utils.composite_id_utils import build_composite_id

YEAR, WEEK = 2026, 20
TUESDAY_DAY_NUMBER = 1  # Mon=0, Tue=1, Wed=2 — the harvest/count day for week 20


def _local(year, month, day, hour=12, minute=0):
    """Aware datetime in the project TZ. recompute/inventory store movement dates
    in the configured TIME_ZONE (noon for supply/demand, 23:00 for the inventory
    count), so the balance cutoffs must use the same TZ to stay correct."""
    return timezone.make_aware(datetime.datetime(year, month, day, hour, minute))


def _make_delivery(*, share, dsd, variation, joker_taken=False, quantity=1):
    """A ShareDelivery on a real Subscription (mirrors test_signal_recompute)."""
    member = MemberFactory()
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        payment_cycle=PaymentCycleFactory(),
        default_delivery_station_day=dsd,
        quantity=quantity,
    )
    delivery = ShareDeliveryFactory(
        share=share, delivery_station_day=dsd, joker_taken=joker_taken
    )
    delivery.subscription = subscription
    delivery.save()
    return delivery


def _balance(article, storage, *, up_to):
    return SnapshotService.compute_balance(
        article.id, "KG", "M", storage.id, up_to=up_to
    )


@pytest.mark.django_db
def test_share_planning_real_stock_balance_fits_next_day_and_week(tenant, api_client):
    # ── Arrange: a share plan that produces theoreticals via recompute ──────
    storage = StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    sdd = SharesDeliveryDayFactory(day_number=2)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=YEAR, delivery_week=WEEK, delivery_day=sdd, share_type_variation=stv
    )
    station = DeliveryStationFactory()
    dsd = DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    sc = ShareContent.objects.create(
        share=share,
        share_article=article,
        delivery_station=station,
        amount=Decimal("5"),
        unit="KG",
        size="M",
        forecast=ForecastFactory(
            share_article=article, year=YEAR, delivery_week=WEEK, size="M"
        ),
    )

    # Real demand: 2 non-joker deliveries -> total quantity 2 -> demand 5*2 = 10.
    for _ in range(2):
        _make_delivery(share=share, dsd=dsd, variation=stv)

    recompute_shares([share.id])

    # ── Theoretical objects + the demand/supply movements were created ──────
    th = TheoreticalHarvest.objects.get(share_content=sc)
    assert th.amount == Decimal("10")  # sc.amount (5) * demand (2)

    demand_mv = MovementShareArticle.objects.get(
        share_content=sc, movement_type=MovementTypeOptions.SHARE
    )
    assert demand_mv.amount == Decimal("-10.000")  # demand recorded negative
    # Wed of week 20 — compare in the project TZ (the date is stored aware).
    assert timezone.localtime(demand_mv.date).date() == datetime.date(2026, 5, 13)

    harvest_mv = MovementShareArticle.objects.get(
        theoretical_harvest=th, movement_type=MovementTypeOptions.HARVEST
    )
    assert harvest_mv.amount == Decimal("10.000")  # theoretical supply, positive
    assert timezone.localtime(harvest_mv.date).date() == datetime.date(2026, 5, 12)

    # Theoretical projection nets to zero: planned supply exactly meets demand.
    assert _balance(article, storage, up_to=None) == Decimal("0")

    # ── Act: the office counts the REAL current stock on Tue (harvest day) ──
    # The real harvest came in heavier than planned: 30 KG actually on hand.
    counted = Decimal("30")
    composite_id = build_composite_id(
        str(article.id), "KG", "M", str(storage.id), YEAR, WEEK, TUESDAY_DAY_NUMBER
    )
    url = reverse("current_stock_comparison_detail", args=[composite_id])
    resp = api_client.patch(url, {"amount": float(counted)}, format="json")
    assert resp.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)

    # ── Assert: the running balance "fits" across the following days/weeks ──
    # End of the count day (Tue): balance == the real counted stock — the
    # INVENTORY correction absorbs the theoretical-harvest projection.
    assert _balance(article, storage, up_to=_local(2026, 5, 12, 23, 59)) == counted

    # Wed (next day), after the SHARECONTENT demand outflow of 10: 30 - 10 = 20.
    next_day = _balance(article, storage, up_to=_local(2026, 5, 13, 23, 59))
    assert next_day == counted - Decimal("10")
    assert next_day >= 0  # "fits" — the planned deliveries are covered

    # Next week (no further movements): the balance is stable at 20.
    next_week = _balance(article, storage, up_to=_local(2026, 5, 20, 12))
    assert next_week == next_day
