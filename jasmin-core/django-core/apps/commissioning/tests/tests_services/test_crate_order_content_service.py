"""Tests for CrateOrderContentService."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.models import CrateOrderContent, Order
from apps.commissioning.services.crate_order_content_service import (
    CrateOrderContentService,
)
from apps.commissioning.tests.factories import (
    CrateFactory,
    CrateNetPriceFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_coc(order, crate, amount=10, price=Decimal("2.50"), **kw):
    oc = OrderContentFactory(order=order)
    kw.setdefault("tax_rate", Decimal("19.00"))
    return CrateOrderContent.objects.create(
        order_content=oc,
        crate_type=crate,
        amount=amount,
        price_per_unit=price,
        **kw,
    )


# ---------------------------------------------------------------------------
# get_crates_summary_for_period
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetCratesSummaryForPeriod:
    def test_aggregates_by_crate_type(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("2.50"))
        _make_coc(order, crate, amount=5, price=Decimal("2.50"))
        _make_coc(order, crate, amount=3, price=Decimal("2.50"))

        summary = CrateOrderContentService.get_crates_summary_for_period(
            2026,
            15,
            2,
            reseller,
        )

        assert len(summary) == 1
        assert summary[0]["amount"] == 8
        assert summary[0]["crate_type_name"] == crate.name
        # Money is emitted as canonical 2dp strings, with line_netto
        # (amount * price * (1 - rabatt)) computed once in Decimal.
        assert summary[0]["price_per_unit"] == "2.50"
        assert summary[0]["line_netto"] == "20.00"

    def test_mixed_prices_yield_separate_rows_not_max(self, tenant):
        # Two lines for the SAME crate type at DIFFERENT prices must NOT
        # collapse to a single row reporting the max price (the old max()
        # bug); they stay distinct so price / line_netto are exact and match
        # the delivery-note / invoice crate summary.
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        _make_coc(order, crate, amount=5, price=Decimal("2.50"))
        _make_coc(order, crate, amount=4, price=Decimal("3.00"))

        summary = CrateOrderContentService.get_crates_summary_for_period(
            2026,
            15,
            2,
            reseller,
        )

        assert len(summary) == 2
        by_price = {row["price_per_unit"]: row for row in summary}
        assert set(by_price) == {"2.50", "3.00"}
        assert by_price["2.50"]["amount"] == 5
        assert by_price["2.50"]["line_netto"] == "12.50"  # 5 * 2.50
        assert by_price["3.00"]["amount"] == 4
        assert by_price["3.00"]["line_netto"] == "12.00"  # 4 * 3.00
        # The grouped nets sum to the true total (24.50), never the
        # max-inflated 9 * 3.00 = 27.00 the old aggregation produced.
        total = sum(Decimal(row["line_netto"]) for row in summary)
        assert total == Decimal("24.50")

    def test_empty_for_different_reseller(self, tenant):
        r1 = ResellerFactory()
        r2 = ResellerFactory()
        order = OrderFactory(reseller=r1, year=2026, delivery_week=15, day_number=2)
        crate = CrateFactory()
        _make_coc(order, crate, amount=5)

        summary = CrateOrderContentService.get_crates_summary_for_period(
            2026,
            15,
            2,
            r2,
        )

        assert summary == []


# ---------------------------------------------------------------------------
# create_crate_order_content
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateCrateOrderContent:
    def test_creates_record_and_order(self, tenant):
        reseller = ResellerFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))

        result = CrateOrderContentService.create_crate_order_content(
            crate_type_id=crate.pk,
            amount=Decimal("10"),
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller.pk,
        )

        assert result["crate_type"] == crate.pk
        assert result["amount"] == Decimal("10")
        # Money out as canonical 2dp strings (not Decimal/float), with
        # backend-computed line_netto = 10 * 3.00.
        assert result["price_per_unit"] == "3.00"
        assert result["line_netto"] == "30.00"
        assert Order.objects.filter(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        ).exists()

    def test_create_result_carries_display_number_and_prefix(self, tenant):
        # The create response must carry the order's ``display_number`` (e.g.
        # "39v" for an unfinalized draft) AND ``prefix`` — identical to the
        # OrderContent path and the reload metadata block — so a crates-first
        # save renders the right number immediately instead of
        # "undefined-<raw number>" until the next reload.
        reseller = ResellerFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))

        result = CrateOrderContentService.create_crate_order_content(
            crate_type_id=crate.pk,
            amount=Decimal("10"),
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller.pk,
        )

        order = Order.objects.get(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        # display_number (string), NOT the raw integer ``number``: a fresh
        # draft is unfinalized, so it renders "<number>v".
        assert result["order_number"] == order.display_number
        assert isinstance(result["order_number"], str)
        assert result["order_number"].endswith("v")
        assert result["order_number_prefix"] == order.prefix

    def test_reuses_existing_order(self, tenant):
        reseller = ResellerFactory()
        _order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("2.00"))

        CrateOrderContentService.create_crate_order_content(
            crate_type_id=crate.pk,
            amount=Decimal("5"),
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller.pk,
        )

        assert (
            Order.objects.filter(
                reseller=reseller, year=2026, delivery_week=15, day_number=2
            ).count()
            == 1
        )

    def test_explicit_zero_price_is_preserved(self, tenant):
        """BL-7: an explicit ``price_per_unit=0`` (a legitimate zero-deposit
        crate) must NOT be overwritten by the crate's dated pricing. The old
        ``if not price_per_unit`` falsy check treated 0 as unset and silently
        replaced it; the ``is None`` check honours the explicit 0."""
        reseller = ResellerFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))

        result = CrateOrderContentService.create_crate_order_content(
            crate_type_id=crate.pk,
            amount=Decimal("10"),
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller.pk,
            price_per_unit=Decimal("0"),
        )

        # Honoured the explicit 0 — did NOT fall back to the dated 3.00.
        # (Compare as Decimal so the wire format "0" vs "0.00" doesn't matter.)
        assert Decimal(result["price_per_unit"]) == Decimal("0")
        assert Decimal(result["line_netto"]) == Decimal("0")
        assert CrateOrderContent.objects.get().price_per_unit == Decimal("0")


# ---------------------------------------------------------------------------
# delete_crate_order_content_by_crate_type
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteCrateOrderContentByCrateType:
    def test_deletes_matching_records(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        _make_coc(order, crate, amount=5)
        _make_coc(order, crate, amount=3)

        deleted = CrateOrderContentService.delete_crate_order_content_by_crate_type(
            crate_type_id=crate.pk,
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller,
        )

        assert deleted is True
        assert CrateOrderContent.objects.filter(crate_type=crate).count() == 0

    def test_returns_false_with_no_context(self, tenant):
        deleted = CrateOrderContentService.delete_crate_order_content_by_crate_type(
            crate_type_id="fake-id",
        )
        assert deleted is False
