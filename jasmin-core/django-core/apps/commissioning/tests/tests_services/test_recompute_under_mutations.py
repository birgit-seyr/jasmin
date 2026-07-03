"""Integration test: recompute correctly creates / rebuilds / cascade-cleans
Theoretical* objects and movements as the share plan is mutated.

One Share carries several ShareContents that between them exercise every
theoretical type:

  * forecast present            -> TheoreticalHarvest (+ HARVEST movement)
  * share_article.is_purchased  -> TheoreticalPurchase (+ PURCHASE movement)
  * ShareContent.washing=True   -> TheoreticalWashAmount
  * ShareContent.cleaning=True  -> TheoreticalCleanAmount
  * any demand                  -> a -SHARECONTENT (demand) movement

Then the plan is mutated step by step and we recompute after each change:
new ShareContent arrives, a ShareContent is deleted, a ShareContent loses its
forecast, a Forecast is deleted (which cascade-deletes its ShareContent), and
the delivered demand changes — asserting the derived objects track the plan and
stale ones are wiped.

Demand is supplied by real Subscriptions/ShareDeliveries (per variation), so all
of the share's ShareContents share the same demand quantity.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.models import (
    MovementShareArticle,
    ShareContent,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
)
from apps.commissioning.models.choices_text import MovementTypeOptions
from apps.commissioning.services.recompute import recompute_shares
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareArticleFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)

YEAR, WEEK = 2026, 15


def _make_delivery(*, share, dsd, variation, quantity=1):
    """A non-joker ShareDelivery on a real Subscription (adds ``quantity`` demand)."""
    member = MemberFactory()
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        payment_cycle=PaymentCycleFactory(),
        default_delivery_station_day=dsd,
        quantity=quantity,
    )
    from apps.commissioning.tests.factories import ShareDeliveryFactory

    delivery = ShareDeliveryFactory(
        share=share, delivery_station_day=dsd, joker_taken=False
    )
    delivery.subscription = subscription
    delivery.save()
    return delivery


def _sharecontent_movement_count():
    return MovementShareArticle.objects.filter(
        movement_type=MovementTypeOptions.SHARE
    ).count()


def _theoretical_movement_count(movement_type):
    """Count is_theoretical supply movements (HARVEST / PURCHASE / ...). These
    carry ``share_content=NULL`` and hang off their ``theoretical_*`` parent, so
    they survive a ShareContent delete only through that CASCADE chain — worth
    asserting separately from the SHARECONTENT demand movements."""
    return MovementShareArticle.objects.filter(
        movement_type=movement_type, is_theoretical=True
    ).count()


@pytest.mark.django_db
def test_recompute_tracks_share_content_and_forecast_mutations(tenant):
    storage = StorageFactory(is_short_term_harvest_storage=True)
    sdd = SharesDeliveryDayFactory(day_number=2)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=YEAR, delivery_week=WEEK, delivery_day=sdd, share_type_variation=stv
    )
    station = DeliveryStationFactory()
    dsd = DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    def _sc(article, *, with_forecast=False, **overrides):
        kwargs = dict(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            **overrides,
        )
        if with_forecast:
            kwargs["forecast"] = ForecastFactory(
                share_article=article,
                year=YEAR,
                delivery_week=WEEK,
                size="M",
                storage=storage,
            )
        return ShareContent.objects.create(**kwargs)

    # ── Arrange: four ShareContents -> every theoretical type ───────────────
    art_a = ShareArticleFactory()
    art_b = ShareArticleFactory()
    art_c = ShareArticleFactory(is_purchased=True)
    art_d = ShareArticleFactory()

    sc_a = _sc(art_a, with_forecast=True)  # -> TheoreticalHarvest
    sc_b = _sc(art_b, with_forecast=True, washing=True)  # -> Harvest + Wash
    sc_c = _sc(art_c)  # purchased, no forecast -> TheoreticalPurchase
    sc_d = _sc(art_d, with_forecast=True, cleaning=True)  # -> Harvest + Clean

    # Real demand: 3 deliveries on the variation -> quantity 3 for every SC.
    for _ in range(3):
        _make_delivery(share=share, dsd=dsd, variation=stv)

    recompute_shares([share.id])

    # ── a "lot of" theoreticals, one of each kind ───────────────────────────
    assert TheoreticalHarvest.objects.count() == 3  # a, b, d (have forecast)
    assert TheoreticalPurchase.objects.count() == 1  # c (purchased)
    assert TheoreticalWashAmount.objects.count() == 1  # b
    assert TheoreticalCleanAmount.objects.count() == 1  # d
    assert _sharecontent_movement_count() == 4  # one demand movement per SC
    # ...and the theoretical SUPPLY movements: HARVEST for a/b/d, PURCHASE for c.
    assert _theoretical_movement_count(MovementTypeOptions.HARVEST) == 3
    assert _theoretical_movement_count(MovementTypeOptions.PURCHASE) == 1
    assert TheoreticalHarvest.objects.get(share_content=sc_a).amount == Decimal("15")
    assert MovementShareArticle.objects.get(
        share_content=sc_a, movement_type=MovementTypeOptions.SHARE
    ).amount == Decimal("-15.000")

    # ── Mutation 1: a NEW ShareContent arrives -> new theoreticals ──────────
    art_e = ShareArticleFactory()
    sc_e = _sc(art_e, with_forecast=True)
    recompute_shares([share.id])

    assert TheoreticalHarvest.objects.count() == 4  # a, b, d, e
    assert TheoreticalHarvest.objects.filter(share_content=sc_e).exists()
    assert _sharecontent_movement_count() == 5

    # ── Mutation 2: DELETE a ShareContent -> its derived objects cascade ────
    sc_c_id = sc_c.id
    sc_c.delete()  # CASCADE: removes its TheoreticalPurchase + SHARECONTENT movement
    recompute_shares([share.id])

    assert not TheoreticalPurchase.objects.exists()
    assert not MovementShareArticle.objects.filter(share_content_id=sc_c_id).exists()
    # The theoretical PURCHASE movement cascaded away with its TheoreticalPurchase.
    assert _theoretical_movement_count(MovementTypeOptions.PURCHASE) == 0
    assert not MovementShareArticle.objects.filter(
        theoretical_purchase__share_content_id=sc_c_id
    ).exists()
    assert _sharecontent_movement_count() == 4  # a, b, d, e

    # ── Mutation 3: a ShareContent LOSES its forecast (kept, but no harvest) ─
    sc_a.forecast = None
    sc_a.save(update_fields=["forecast"])
    recompute_shares([share.id])

    assert not TheoreticalHarvest.objects.filter(share_content=sc_a).exists()
    # ...but the demand movement for sc_a still exists (demand is independent).
    assert MovementShareArticle.objects.filter(
        share_content=sc_a, movement_type=MovementTypeOptions.SHARE
    ).exists()
    assert TheoreticalHarvest.objects.count() == 3  # b, d, e
    assert _sharecontent_movement_count() == 4  # a, b, d, e unchanged

    # ── Mutation 4: DELETE a Forecast -> cascade-deletes its ShareContent ───
    sc_b_id = sc_b.id
    # CASCADE: deleting the Forecast deletes sc_b, which in turn cascades its
    # TheoreticalHarvest + TheoreticalWashAmount objects and its HARVEST +
    # SHARECONTENT movements (there is no separate wash MOVEMENT here — wash/clean
    # movements are only emitted for long-term-storage ShareContents).
    sc_b.forecast.delete()
    assert not ShareContent.objects.filter(id=sc_b_id).exists()
    recompute_shares([share.id])

    assert not TheoreticalWashAmount.objects.exists()  # b's wash theoretical gone
    assert not MovementShareArticle.objects.filter(share_content_id=sc_b_id).exists()
    # sc_b's theoretical HARVEST movement cascaded away with it; only d, e remain.
    assert not MovementShareArticle.objects.filter(
        theoretical_harvest__share_content_id=sc_b_id
    ).exists()
    assert _theoretical_movement_count(MovementTypeOptions.HARVEST) == 2  # d, e
    assert TheoreticalHarvest.objects.count() == 2  # d, e
    assert _sharecontent_movement_count() == 3  # a, d, e

    # ── Mutation 5: delivered DEMAND changes (3 -> 6) -> amounts update ──────
    for _ in range(3):
        _make_delivery(share=share, dsd=dsd, variation=stv)
    recompute_shares([share.id])

    assert TheoreticalHarvest.objects.get(share_content=sc_d).amount == Decimal("30")
    assert MovementShareArticle.objects.get(
        share_content=sc_d, movement_type=MovementTypeOptions.SHARE
    ).amount == Decimal("-30.000")

    # ── Idempotency: recomputing again changes neither counts NOR amounts ────
    def _snapshot():
        return (
            TheoreticalHarvest.objects.count(),
            _sharecontent_movement_count(),
            TheoreticalHarvest.objects.get(share_content=sc_d).amount,
        )

    before = _snapshot()
    recompute_shares([share.id])
    after = _snapshot()
    assert before == after == (2, 3, Decimal("30"))
