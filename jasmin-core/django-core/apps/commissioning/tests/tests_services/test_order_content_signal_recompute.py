"""Tests for the explicit OrderContent recompute pipeline.

OrderContent is the resellers analog of ShareContent. Each OrderContent
owns its own theoreticals (TheoreticalHarvest/Purchase/Wash/Clean via
``order_content`` FK) plus MovementShareArticle rows with
movement_type="ORDERCONTENT".

Unlike ShareContent there is NO demand-aggregation step (Order is the
source document). So each theoretical equals OrderContent.amount * 1.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import TestCase

from apps.commissioning.models import (
    MovementShareArticle,
    TheoreticalHarvest,
)
from apps.commissioning.services.recompute import recompute_order_contents
from apps.commissioning.tests.factories import (
    ForecastFactory,
    OrderContentFactory,
    ShareArticleFactory,
    StorageFactory,
)


def _setup_order_content(amount: Decimal = Decimal("10")):
    storage = StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    # TheoreticalHarvest is only emitted when a matching Forecast exists
    # (year/week/share_article/size). Without it OrderContent only produces
    # ORDERCONTENT movements, not theoreticals.
    ForecastFactory(
        share_article=article,
        year=2026,
        delivery_week=15,
        size="M",
        storage=storage,
    )
    return OrderContentFactory(
        share_article=article,
        amount=amount,
        unit="KG",
        size="M",
    )


@pytest.mark.usefixtures("tenant")
class OrderContentRecomputeTests(TestCase):
    def test_recompute_creates_theoreticals(self):
        oc = _setup_order_content(Decimal("10"))
        recompute_order_contents([oc.id])

        th = TheoreticalHarvest.objects.get(order_content=oc)
        assert th.amount == Decimal("10")

    def test_editing_order_content_amount_rebuilds_theoreticals(self):
        oc = _setup_order_content(Decimal("10"))
        recompute_order_contents([oc.id])
        assert TheoreticalHarvest.objects.get(order_content=oc).amount == Decimal("10")

        oc.amount = Decimal("25")
        oc.save()
        recompute_order_contents([oc.id])

        assert TheoreticalHarvest.objects.get(order_content=oc).amount == Decimal("25")

    def test_deleting_order_content_cascades_theoreticals(self):
        oc = _setup_order_content(Decimal("10"))
        recompute_order_contents([oc.id])
        oc_id = oc.id
        assert TheoreticalHarvest.objects.filter(order_content_id=oc_id).exists()

        oc.delete()

        assert not TheoreticalHarvest.objects.filter(order_content_id=oc_id).exists()
        assert not MovementShareArticle.objects.filter(
            order_content_id=oc_id, movement_type="ORDERCONTENT"
        ).exists()

    def test_no_duplicate_movements_after_repeated_recomputes(self):
        oc = _setup_order_content(Decimal("10"))
        recompute_order_contents([oc.id])

        baseline = MovementShareArticle.objects.filter(
            order_content=oc, movement_type="ORDERCONTENT"
        ).count()
        assert baseline >= 1

        for new_amount in (Decimal("12"), Decimal("15"), Decimal("8")):
            oc.amount = new_amount
            oc.save()
            recompute_order_contents([oc.id])

        after = MovementShareArticle.objects.filter(
            order_content=oc, movement_type="ORDERCONTENT"
        ).count()
        assert after == baseline, (
            "Recompute must wipe + rebuild ORDERCONTENT movements, not append. "
            f"baseline={baseline}, after={after}"
        )

    def test_recompute_dedupes_order_content_ids(self):
        oc = _setup_order_content(Decimal("10"))
        # Same id passed 5x — must produce one theoretical row.
        recompute_order_contents([oc.id, oc.id, oc.id, oc.id, oc.id])

        assert TheoreticalHarvest.objects.filter(order_content=oc).count() == 1

    def test_recompute_for_empty_input_is_noop(self):
        recompute_order_contents([])
        recompute_order_contents([None])
        recompute_order_contents(())
