"""Tests for OrderContentService."""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.commissioning.models import (
    CrateOrderContent,
    Order,
    OrderContent,
)
from apps.commissioning.services.crate_order_content_service import (
    CrateOrderContentService,
)
from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.tests.factories import (
    CrateFactory,
    CrateNetPriceFactory,
    OfferFactory,
    OrderContentFactory,
    OrderFactory,
    OrdersDeliveryDayFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.shared.tenants.models import TenantSettings
from core.errors import JasminError


def _noop_theoretical(*a, **kw):
    """Stub for create_all_theoretical_objects — avoids heavy setup."""
    return {"harvests": [], "purchases": [], "washes": [], "cleans": []}


def _noop_movements(*a, **kw):
    """Stub for create_movements — avoids StockService dependency."""
    return []


# ---------------------------------------------------------------------------
# create_order_with_content_and_crates
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateOrderWithContentAndCrates:
    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_creates_order_and_content(self, _mock_theo, _mock_mv, tenant):
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
        )

        result = OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("10"),
        )

        assert result["offer"] == offer.pk
        assert result["amount"] == Decimal("10")
        assert Order.objects.filter(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        ).exists()

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_reuses_existing_order(self, _mock_theo, _mock_mv, tenant):
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        _order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        offer = OfferFactory(
            share_article=article, amount=Decimal("100"), unit="KG", size="M"
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("5"),
        )

        assert (
            Order.objects.filter(
                reseller=reseller, year=2026, delivery_week=15, day_number=2
            ).count()
            == 1
        )

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_creates_crate_order_content(self, _mock_theo, _mock_mv, tenant):
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
            used_crate=crate,
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("10"),
        )

        assert CrateOrderContent.objects.count() == 1
        coc = CrateOrderContent.objects.first()
        assert coc.crate_type == crate

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_no_crate_order_content_when_crates_off_documents(
        self, _mock_theo, _mock_mv, tenant
    ):
        """When the tenant keeps crates OFF documents, ordering an article whose
        offer carries a crate creates NO CrateOrderContent — so nothing cascades
        onto delivery notes / invoices (the root gate the whole feature hangs
        off). Contrast ``test_creates_crate_order_content`` (default → 1)."""
        TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            crates_should_be_on_documents=False,
        )
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
            used_crate=crate,
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("10"),
        )

        assert CrateOrderContent.objects.count() == 0

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_zero_amount_creates_no_crate_order_content(
        self, _mock_theo, _mock_mv, tenant
    ):
        """BL-6: a zero-amount line must NOT spawn a crate row on create — the
        create path now mirrors the update path's ``amount > 0`` guard, so the
        two leave identical crate artefacts (no dead amount-0 crate row + stray
        empty VAT bucket downstream)."""
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
            used_crate=crate,
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("0"),
        )

        assert CrateOrderContent.objects.count() == 0

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_crate_amount_rounds_up(self, _mock_theo, _mock_mv, tenant):
        """Crate count = ceil(order amount / amount_per_pu): a partial crate
        still needs a whole physical crate (10 / 3 = 3.33 → 4), not the
        implicit int()-truncation (→ 3) of the old bare division."""
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
            used_crate=crate,
            amount_per_pu=Decimal("3"),
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("10"),
        )

        coc = CrateOrderContent.objects.get(crate_type=crate)
        assert coc.amount == 4

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_updates_offer_available_amount(self, _mock_theo, _mock_mv, tenant):
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("50"),
            unit="KG",
            size="M",
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("10"),
        )

        offer.refresh_from_db()
        assert offer.amount == Decimal("40")

    def test_raises_if_not_enough_stock(self, tenant):
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )

        with pytest.raises(JasminError, match="Not enough stock"):
            OrderContentService.create_order_with_content_and_crates(
                reseller=reseller,
                year=2026,
                delivery_week=15,
                day_number=2,
                offer=offer,
                amount=Decimal("100"),
            )

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_populates_day_fields_from_defaults(self, _mock_theo, _mock_mv, tenant):
        OrdersDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_packing_day=2,
        )
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("100"), unit="KG", size="M"
        )

        OrderContentService.create_order_with_content_and_crates(
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
            offer=offer,
            amount=Decimal("10"),
        )

        order = Order.objects.get(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        assert order.harvesting_day == 1
        assert order.packing_day == 2


# ---------------------------------------------------------------------------
# update_order_content
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateOrderContent:
    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_updates_amount(self, _mock_theo, _mock_mv, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("90"), unit="KG", size="M"
        )
        oc = OrderContentFactory(offer=offer, share_article=None, amount=Decimal("10"))

        result = OrderContentService.update_order_content(
            order_content_id=oc.pk,
            amount=Decimal("15"),
        )

        assert result["amount"] == Decimal("15")
        offer.refresh_from_db()
        # offer amount should decrease by the difference (5)
        assert offer.amount == Decimal("85")

    def test_raises_if_finalized(self, tenant):
        # Build without save (FinalizedProtectedMixin blocks save of finalized objects)
        oc = OrderContentFactory(amount=Decimal("10"))
        OrderContent.objects.filter(pk=oc.pk).update(is_finalized=True)
        oc.refresh_from_db()

        with pytest.raises(JasminError, match="finalized"):
            OrderContentService.update_order_content(
                order_content_id=oc.pk,
                amount=Decimal("20"),
            )

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    def test_recreates_crate_order_content_with_tax_rate(
        self, _mock_theo, _mock_mv, tenant
    ):
        """Regression: update_order_content used to recreate the
        CrateOrderContent without passing tax_rate, which violates the
        NOT NULL constraint on `commissioning_crateordercontent.tax_rate`
        and surfaced to the API as a 409 "Database integrity error".

        Path: offer has a used_crate → on update, the service deletes the
        existing CrateOrderContent and creates a fresh one for the new
        amount. The fresh-create has to mirror what the CREATE path does
        (resolve via crate pricing → tenant default → constant fallback).
        """
        article = ShareArticleFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("90"),
            unit="KG",
            size="M",
            used_crate=crate,
        )
        oc = OrderContentFactory(offer=offer, share_article=None, amount=Decimal("10"))
        # Pre-existing CrateOrderContent (mirrors what CREATE would have
        # produced). Delete any factory-built one so the count assertion
        # is unambiguous.
        CrateOrderContent.objects.filter(order_content=oc).delete()
        CrateOrderContent.objects.create(
            order_content=oc,
            crate_type=crate,
            amount=Decimal("1"),
            price_per_unit=Decimal("3.00"),
            tax_rate=Decimal("19"),
        )

        # Before the fix: this raised django.db.IntegrityError because the
        # service's CrateOrderContent.create() call omitted tax_rate.
        OrderContentService.update_order_content(
            order_content_id=oc.pk,
            amount=Decimal("15"),
        )

        # The old crate row is replaced and the new one has a non-null
        # tax_rate (resolved through the same chain as the CREATE path).
        crates = CrateOrderContent.objects.filter(order_content=oc)
        assert crates.count() == 1
        new_crate = crates.first()
        assert new_crate.tax_rate is not None
        assert new_crate.amount == Decimal("15")  # new_amount / pu_divisor(=1)


# ---------------------------------------------------------------------------
# delete_order_content
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteOrderContent:
    def test_deletes_and_restores_offer_amount(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("40"), unit="KG", size="M"
        )
        order = OrderFactory()
        oc = OrderContentFactory(
            order=order, offer=offer, share_article=None, amount=Decimal("10")
        )

        _result = OrderContentService.delete_order_content(oc.pk)

        offer.refresh_from_db()
        assert offer.amount == Decimal("50")
        assert not OrderContent.objects.filter(pk=oc.pk).exists()

    def test_restores_offer_amount_in_pu_when_amount_per_pu_not_one(self, tenant):

        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("40"),
            amount_per_pu=Decimal("5"),
            unit="KG",
            size="M",
        )
        order = OrderFactory()
        oc = OrderContentFactory(
            order=order, offer=offer, share_article=None, amount=Decimal("10")
        )

        OrderContentService.delete_order_content(oc.pk)

        offer.refresh_from_db()
        assert offer.amount == Decimal("42")  # 40 + 10/5, not 40 + 10

    def test_deletes_empty_order(self, tenant):
        order = OrderFactory()
        oc = OrderContentFactory(order=order, amount=Decimal("10"))

        result = OrderContentService.delete_order_content(oc.pk)

        assert result["order_deleted"] is True
        assert not Order.objects.filter(pk=order.pk).exists()

    def test_keeps_order_with_remaining_content(self, tenant):
        order = OrderFactory()
        oc1 = OrderContentFactory(order=order, amount=Decimal("10"))
        _oc2 = OrderContentFactory(order=order, amount=Decimal("5"))

        result = OrderContentService.delete_order_content(oc1.pk)

        assert result["order_deleted"] is False
        assert Order.objects.filter(pk=order.pk).exists()

    def test_raises_for_not_found(self, tenant):
        with pytest.raises(JasminError, match="not found"):
            OrderContentService.delete_order_content(999999)


# ---------------------------------------------------------------------------
# Wiring: every mutation path must trigger ``recompute_order_contents``
# ---------------------------------------------------------------------------
# These tests verify the single-entry-point invariant that mirrors the
# ShareContent side (``recompute_shares``). The mutation methods MUST go
# through the public ``recompute_order_contents`` helper so any other
# code path (management commands, backfills, future callers) gets the
# same wipe + rebuild behaviour for free.
#
# We patch ``recompute_order_contents`` at the module path where the
# service imports it (the deferred import in
# ``order_content_service.py``). The service does ``from .recompute
# import recompute_order_contents`` inside the function body, so the
# patch target is the recompute MODULE's symbol — that's what the
# service binds to at call time.
@pytest.mark.django_db
class TestRecomputeOrderContentsWiring:
    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    @patch("apps.commissioning.services.recompute.recompute_order_contents")
    def test_create_path_triggers_recompute(
        self, mock_recompute, _mock_theo, _mock_mv, tenant
    ):
        reseller = ResellerFactory()
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article,
            amount=Decimal("100"),
            unit="KG",
            size="M",
        )

        result = OrderContentService.create_order_with_content_and_crates(
            offer=offer,
            amount=Decimal("10"),
            reseller=reseller,
            year=2026,
            delivery_week=15,
            day_number=2,
        )

        # The newly-created OrderContent id is what gets passed to recompute.
        mock_recompute.assert_called_once_with([result["id"]])

    @patch.object(OrderContentService, "create_movements", side_effect=_noop_movements)
    @patch.object(
        OrderContentService,
        "create_all_theoretical_objects",
        side_effect=_noop_theoretical,
    )
    @patch("apps.commissioning.services.recompute.recompute_order_contents")
    def test_update_path_triggers_recompute(
        self, mock_recompute, _mock_theo, _mock_mv, tenant
    ):
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("90"), unit="KG", size="M"
        )
        oc = OrderContentFactory(offer=offer, share_article=None, amount=Decimal("10"))

        OrderContentService.update_order_content(
            order_content_id=oc.pk,
            amount=Decimal("15"),
        )

        mock_recompute.assert_called_once_with([oc.pk])

    @patch("apps.commissioning.services.recompute.recompute_order_contents")
    def test_delete_path_does_not_call_recompute(self, mock_recompute, tenant):
        """Delete is the exception: the OrderContent is gone, so there's
        no id to recompute. Cleanup of theoreticals happens via FK CASCADE
        and snapshots are fixed up by ``SnapshotService.cascade_for_movements``
        on the captured movement list (see ``delete_order_content``).

        This test pins the asymmetry so a future "let's call recompute
        everywhere for symmetry" refactor doesn't silently make this path
        a no-op call.
        """
        article = ShareArticleFactory()
        offer = OfferFactory(
            share_article=article, amount=Decimal("40"), unit="KG", size="M"
        )
        order = OrderFactory()
        oc = OrderContentFactory(
            order=order, offer=offer, share_article=None, amount=Decimal("10")
        )

        OrderContentService.delete_order_content(oc.pk)

        mock_recompute.assert_not_called()


# ---------------------------------------------------------------------------
# get_offers_and_order_content — top-level ``order`` block (crates-only orders)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetOffersAndOrderContentOrderBlock:
    def test_crates_only_order_surfaces_top_level_order(self, tenant):
        """A crates-only order (zero OrderContent rows) still exposes its
        identity via the top-level ``order`` block, so the Orders page can
        render and progress it instead of treating the period as orderless."""
        reseller = ResellerFactory()
        crate = CrateFactory()

        created = CrateOrderContentService.create_crate_order_content(
            crate_type_id=crate.id,
            amount=3,
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller.id,
        )

        result = OrderContentService.get_offers_and_order_content(
            reseller.id, 2026, 15, 2
        )

        # No share-article content rows, but the order IS surfaced.
        assert result["items"] == []
        assert result["order"] is not None
        assert result["order"]["order_id"] == created["order_id"]
        assert result["order"]["order_is_finalized"] is False
        assert result["order"]["has_invoice"] is False
        assert result["order"]["delivery_note_id"] is None

    def test_period_without_order_returns_null_order(self, tenant):
        reseller = ResellerFactory()

        result = OrderContentService.get_offers_and_order_content(
            reseller.id, 2026, 16, 3
        )

        assert result["order"] is None
        assert result["items"] == []
