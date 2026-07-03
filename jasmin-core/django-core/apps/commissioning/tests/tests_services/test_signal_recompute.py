"""Tests for the explicit ShareContent/ShareDelivery/Forecast recompute pipeline."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import TestCase

from apps.commissioning.models import (
    MovementShareArticle,
    ShareContent,
    TheoreticalHarvest,
)
from apps.commissioning.services.recompute import recompute_shares
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


def _setup(*, with_forecast: bool = True):
    """Build a Share + Forecast + DeliveryStationDay + ShareContent (amount=5)."""
    StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    sdd = SharesDeliveryDayFactory(day_number=2)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=2026, delivery_week=20, delivery_day=sdd, share_type_variation=stv
    )
    station = DeliveryStationFactory()
    dsd = DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    sc_kwargs = dict(
        share=share,
        share_article=article,
        delivery_station=station,
        amount=Decimal("5"),
        unit="KG",
        size="M",
    )
    if with_forecast:
        sc_kwargs["forecast"] = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=20,
            size="M",
        )
    sc = ShareContent.objects.create(**sc_kwargs)
    return share, sc, dsd, article, stv


def _make_delivery(
    *, share, dsd, variation, joker_taken: bool = False, quantity: int = 1
):
    """Create a ShareDelivery linked to a real Subscription."""
    member = MemberFactory()
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        payment_cycle=PaymentCycleFactory(),
        default_delivery_station_day=dsd,
        quantity=quantity,
    )
    delivery = ShareDeliveryFactory(
        share=share,
        delivery_station_day=dsd,
        joker_taken=joker_taken,
    )
    delivery.subscription = subscription
    delivery.save()
    return delivery


@pytest.mark.usefixtures("tenant")
class RecomputeOnDeliveryChangeTests(TestCase):
    """The reverse-direction trigger: ShareDelivery → recompute."""

    def test_share_content_created_before_any_delivery_then_delivery_added(self):
        share, sc, dsd, _, stv = _setup()
        recompute_shares([share.id])

        th = TheoreticalHarvest.objects.get(share_content=sc)
        assert th.amount == Decimal("0")

        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])

        th = TheoreticalHarvest.objects.get(share_content=sc)
        assert th.amount == Decimal("5")

    def test_joker_taken_delivery_does_not_count(self):
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv, joker_taken=False)
        _make_delivery(share=share, dsd=dsd, variation=stv, joker_taken=True)
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("5")

    def test_toggling_joker_on_existing_delivery_recomputes(self):
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv)
        d2 = _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("10")

        d2.joker_taken = True
        d2.save()
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("5")

    def test_deleting_a_delivery_recomputes(self):
        share, sc, dsd, _, stv = _setup()
        d1 = _make_delivery(share=share, dsd=dsd, variation=stv)
        _make_delivery(share=share, dsd=dsd, variation=stv)
        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("15")

        d1.delete()
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("10")


@pytest.mark.usefixtures("tenant")
class RecomputeOnShareContentEditTests(TestCase):
    def test_editing_share_content_amount_rebuilds_theoreticals(self):
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv)
        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("10")

        sc.amount = Decimal("7")
        sc.save()
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("14")

    def test_recompute_is_idempotent(self):
        """Multiple recompute calls must not duplicate rows."""
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv)
        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])
        recompute_shares([share.id])
        recompute_shares([share.id])

        assert TheoreticalHarvest.objects.filter(share_content=sc).count() == 1
        assert TheoreticalHarvest.objects.get(share_content=sc).amount == Decimal("10")

    def test_recompute_dedupes_share_ids(self):
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id, share.id, share.id, share.id])

        assert TheoreticalHarvest.objects.filter(share_content=sc).count() == 1


@pytest.mark.usefixtures("tenant")
class RecomputeWipesStaleMovementsTests(TestCase):
    def test_no_duplicate_sharecontent_movements_after_repeated_edits(self):
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])

        baseline = MovementShareArticle.objects.filter(
            share_content=sc, movement_type="SHARECONTENT"
        ).count()
        assert baseline >= 1

        sc.amount = Decimal("9")
        sc.save()
        recompute_shares([share.id])

        after = MovementShareArticle.objects.filter(
            share_content=sc, movement_type="SHARECONTENT"
        ).count()
        assert after == baseline, (
            "Recompute must wipe + rebuild, not append. "
            f"baseline={baseline}, after={after}"
        )


@pytest.mark.usefixtures("tenant")
class RecomputeOnForecastChangeTests(TestCase):
    def test_forecast_change_recomputes_linked_shares(self):
        share, sc, dsd, _, stv = _setup()
        _make_delivery(share=share, dsd=dsd, variation=stv)
        recompute_shares([share.id])

        forecast = sc.forecast
        assert forecast is not None

        forecast.amount = Decimal("99")
        forecast.save()
        # Callers gather affected share_ids then recompute.
        share_ids = list(
            ShareContent.objects.filter(forecast=forecast)
            .values_list("share_id", flat=True)
            .distinct()
        )
        recompute_shares(share_ids)

        assert TheoreticalHarvest.objects.filter(share_content=sc).count() == 1


@pytest.mark.usefixtures("tenant")
class RecomputeNoopTests(TestCase):
    def test_recompute_for_empty_input_is_noop(self):
        recompute_shares([])
        recompute_shares([None])
        recompute_shares(())
