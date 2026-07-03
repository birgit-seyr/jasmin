"""Integration tests: verify that create/update/delete of OrderContent
correctly creates, recreates, or cascade-deletes MovementShareArticle and
theoretical objects (TheoreticalHarvest, TheoreticalPurchase,
TheoreticalWashAmount, TheoreticalCleanAmount).

Unlike test_order_content_service.py these tests do NOT mock out
create_movements / create_all_theoretical_objects.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.models import (
    MovementShareArticle,
    OrderContent,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
)
from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.tests.factories import (
    ForecastFactory,
    OfferFactory,
    OrderContentFactory,
    OrderFactory,
    OrdersDeliveryDayFactory,
    ResellerFactory,
    ShareArticleFactory,
    StorageFactory,
)

# ── Helpers ──────────────────────────────────────────


def _base_kwargs(reseller, *, day_number=2):
    return dict(reseller=reseller, year=2026, delivery_week=15, day_number=day_number)


def _create(reseller, offer, amount, **extra):
    return OrderContentService.create_order_with_content_and_crates(
        **_base_kwargs(reseller),
        offer=offer,
        amount=amount,
        **extra,
    )


# ═══════════════════════════════════════════════════════
# CREATE – movements
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateMovements:
    """create_order_with_content_and_crates should create ORDERCONTENT movements."""

    def test_creates_ordercontent_movement(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))

        oc = OrderContent.objects.get(pk=result["id"])
        movements = MovementShareArticle.objects.filter(
            order_content=oc, is_theoretical=False
        )
        assert movements.exists(), "Expected at least one non-theoretical movement"
        assert all(m.movement_type == "ORDERCONTENT" for m in movements)
        # total movement amount should equal −10 (negative = stock leaves)
        total = sum(m.amount for m in movements)
        assert total == Decimal("-10")

    def test_movement_uses_short_term_storage_when_no_stock(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        _create(reseller, offer, Decimal("5"))

        oc = OrderContent.objects.first()
        mv = MovementShareArticle.objects.get(order_content=oc, is_theoretical=False)
        assert mv.storage == storage


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalHarvest
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateTheoreticalHarvest:
    def test_creates_theoretical_harvest_when_forecast_exists(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))

        oc = OrderContent.objects.get(pk=result["id"])
        th = TheoreticalHarvest.objects.filter(order_content=oc)
        assert th.exists(), "TheoreticalHarvest should be created when Forecast exists"
        assert th.first().amount == Decimal("10")
        assert th.first().share_article == article

    def test_creates_theoretical_harvest_movement(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        _create(reseller, offer, Decimal("10"))

        oc = OrderContent.objects.first()
        th = TheoreticalHarvest.objects.get(order_content=oc)
        mv = MovementShareArticle.objects.filter(
            theoretical_harvest=th, is_theoretical=True
        )
        assert mv.exists(), "Theoretical HARVEST movement should be created"
        assert mv.first().amount == Decimal("10")
        assert mv.first().movement_type == "HARVEST"

    def test_no_theoretical_harvest_without_forecast(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        _create(reseller, offer, Decimal("10"))

        assert not TheoreticalHarvest.objects.exists()


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalPurchase
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateTheoreticalPurchase:
    def test_creates_theoretical_purchase_for_purchased_article(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory(is_purchased=True)
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("20"))

        oc = OrderContent.objects.get(pk=result["id"])
        tp = TheoreticalPurchase.objects.filter(order_content=oc)
        assert (
            tp.exists()
        ), "TheoreticalPurchase should be created for purchased article"
        assert tp.first().amount == Decimal("20")

    def test_creates_theoretical_purchase_movement(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory(is_purchased=True)
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        _create(reseller, offer, Decimal("20"))

        tp = TheoreticalPurchase.objects.first()
        mv = MovementShareArticle.objects.filter(
            theoretical_purchase=tp, is_theoretical=True
        )
        assert mv.exists(), "Theoretical PURCHASE movement should be created"
        assert mv.first().movement_type == "PURCHASE"
        assert mv.first().amount == Decimal("20")

    def test_no_theoretical_purchase_for_non_purchased_article(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory(is_purchased=False)
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        _create(reseller, offer, Decimal("10"))

        assert not TheoreticalPurchase.objects.exists()


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalWashAmount
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateTheoreticalWashAmount:
    def test_creates_theoretical_wash_when_washing_enabled(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        OrdersDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_washing_day=1,
        )
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"), washing=True)

        result = _create(reseller, offer, Decimal("15"))

        oc = OrderContent.objects.get(pk=result["id"])
        tw = TheoreticalWashAmount.objects.filter(order_content=oc)
        assert tw.exists(), "TheoreticalWashAmount should be created when washing=True"
        assert tw.first().amount == Decimal("15")

    def test_no_theoretical_wash_when_washing_disabled(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("100"), washing=False
        )

        _create(reseller, offer, Decimal("10"))

        assert not TheoreticalWashAmount.objects.exists()


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalCleanAmount
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateTheoreticalCleanAmount:
    def test_creates_theoretical_clean_when_cleaning_enabled(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        OrdersDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_cleaning_day=1,
        )
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("100"), cleaning=True
        )

        result = _create(reseller, offer, Decimal("12"))

        oc = OrderContent.objects.get(pk=result["id"])
        tc = TheoreticalCleanAmount.objects.filter(order_content=oc)
        assert (
            tc.exists()
        ), "TheoreticalCleanAmount should be created when cleaning=True"
        assert tc.first().amount == Decimal("12")

    def test_no_theoretical_clean_when_cleaning_disabled(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("100"), cleaning=False
        )

        _create(reseller, offer, Decimal("10"))

        assert not TheoreticalCleanAmount.objects.exists()


# ═══════════════════════════════════════════════════════
# UPDATE – movements & theoretical objects are recreated
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestUpdateRecreatesRelatedObjects:
    def test_update_recreates_movements(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]

        old_mv_ids = set(
            MovementShareArticle.objects.filter(
                order_content_id=oc_id, is_theoretical=False
            ).values_list("id", flat=True)
        )
        assert old_mv_ids, "Should have movements after create"

        OrderContentService.update_order_content(
            order_content_id=oc_id, amount=Decimal("20")
        )

        new_mvs = MovementShareArticle.objects.filter(
            order_content_id=oc_id, is_theoretical=False
        )
        new_mv_ids = set(new_mvs.values_list("id", flat=True))

        # Old movements should be gone, new ones created
        assert not old_mv_ids & new_mv_ids, "Old movements should be replaced"
        assert new_mvs.exists(), "New movements should exist"
        total = sum(m.amount for m in new_mvs)
        assert total == Decimal("-20")

    def test_update_recreates_theoretical_harvest(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]

        old_th_ids = set(
            TheoreticalHarvest.objects.filter(order_content_id=oc_id).values_list(
                "id", flat=True
            )
        )
        assert old_th_ids

        OrderContentService.update_order_content(
            order_content_id=oc_id, amount=Decimal("25")
        )

        new_ths = TheoreticalHarvest.objects.filter(order_content_id=oc_id)
        new_th_ids = set(new_ths.values_list("id", flat=True))
        assert (
            not old_th_ids & new_th_ids
        ), "Old theoretical harvests should be replaced"
        assert new_ths.first().amount == Decimal("25")

    def test_update_recreates_theoretical_purchase(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory(is_purchased=True)
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]

        old_tp_ids = set(
            TheoreticalPurchase.objects.filter(order_content_id=oc_id).values_list(
                "id", flat=True
            )
        )
        assert old_tp_ids

        OrderContentService.update_order_content(
            order_content_id=oc_id, amount=Decimal("30")
        )

        new_tps = TheoreticalPurchase.objects.filter(order_content_id=oc_id)
        new_tp_ids = set(new_tps.values_list("id", flat=True))
        assert not old_tp_ids & new_tp_ids
        assert new_tps.first().amount == Decimal("30")


# ═══════════════════════════════════════════════════════
# DELETE – cascade-deletes movements & theoretical objects
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestDeleteCascadesRelatedObjects:
    def test_delete_removes_movements(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]

        assert MovementShareArticle.objects.filter(order_content_id=oc_id).exists()

        OrderContentService.delete_order_content(oc_id)

        assert not MovementShareArticle.objects.filter(order_content_id=oc_id).exists()

    def test_delete_removes_theoretical_harvest(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]
        assert TheoreticalHarvest.objects.filter(order_content_id=oc_id).exists()

        OrderContentService.delete_order_content(oc_id)

        assert not TheoreticalHarvest.objects.filter(order_content_id=oc_id).exists()

    def test_delete_removes_theoretical_purchase(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory(is_purchased=True)
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]
        assert TheoreticalPurchase.objects.filter(order_content_id=oc_id).exists()

        OrderContentService.delete_order_content(oc_id)

        assert not TheoreticalPurchase.objects.filter(order_content_id=oc_id).exists()

    def test_delete_removes_theoretical_wash(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        OrdersDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_washing_day=1,
        )
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100"), washing=True)

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]
        assert TheoreticalWashAmount.objects.filter(order_content_id=oc_id).exists()

        OrderContentService.delete_order_content(oc_id)

        assert not TheoreticalWashAmount.objects.filter(order_content_id=oc_id).exists()

    def test_delete_removes_theoretical_clean(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        OrdersDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_cleaning_day=1,
        )
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("100"), cleaning=True
        )

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]
        assert TheoreticalCleanAmount.objects.filter(order_content_id=oc_id).exists()

        OrderContentService.delete_order_content(oc_id)

        assert not TheoreticalCleanAmount.objects.filter(
            order_content_id=oc_id
        ).exists()

    def test_delete_removes_all_related_at_once(self, tenant):
        """Create an order content with both forecast (→harvest) and purchased
        article (→purchase), then delete and assert everything is gone."""
        storage = StorageFactory(is_short_term_harvest_storage=True)
        reseller = ResellerFactory()
        article = ShareArticleFactory(is_purchased=True)
        ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        offer = OfferFactory(share_article=article, amount=Decimal("100"))

        result = _create(reseller, offer, Decimal("10"))
        oc_id = result["id"]

        assert TheoreticalHarvest.objects.filter(order_content_id=oc_id).exists()
        assert TheoreticalPurchase.objects.filter(order_content_id=oc_id).exists()
        assert MovementShareArticle.objects.filter(order_content_id=oc_id).exists()

        OrderContentService.delete_order_content(oc_id)

        assert not TheoreticalHarvest.objects.filter(order_content_id=oc_id).exists()
        assert not TheoreticalPurchase.objects.filter(order_content_id=oc_id).exists()
        assert not MovementShareArticle.objects.filter(order_content_id=oc_id).exists()
        assert not OrderContent.objects.filter(pk=oc_id).exists()


# ═══════════════════════════════════════════════════════
# Query-count lock — Forecast lookup is batched
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateAllTheoreticalObjectsForecastBatching:
    """``create_all_theoretical_objects`` must look up Forecasts in ONE query
    for the whole batch, not one ``filter(...).first()`` per order content."""

    def _content_with_forecast(self, order, *, size="M"):
        article = ShareArticleFactory()
        ForecastFactory(
            year=order.year,
            delivery_week=order.delivery_week,
            share_article=article,
            size=size,
        )
        return OrderContentFactory(
            order=order, share_article=article, size=size, unit="KG"
        )

    def test_forecast_lookup_is_batched(self, tenant):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        StorageFactory(is_short_term_harvest_storage=True)
        order = OrderFactory(year=2026, delivery_week=15)

        def _forecast_selects(ctx) -> int:
            # Exact table match (trailing quote) so the
            # ForecastShareTypeVariation table isn't counted.
            return sum(
                1
                for q in ctx.captured_queries
                if '"commissioning_forecast"' in q["sql"].lower()
            )

        few = [self._content_with_forecast(order) for _ in range(2)]
        with CaptureQueriesContext(connection) as ctx_small:
            OrderContentService.create_all_theoretical_objects(few)
        small = _forecast_selects(ctx_small)

        many = [self._content_with_forecast(order) for _ in range(6)]
        with CaptureQueriesContext(connection) as ctx_large:
            OrderContentService.create_all_theoretical_objects(many)
        large = _forecast_selects(ctx_large)

        assert small <= 1, f"expected <=1 Forecast SELECT, got {small}"
        assert large <= 1, (
            "Forecast lookup not batched: "
            f"2 contents -> {small} selects, 6 contents -> {large} selects"
        )
