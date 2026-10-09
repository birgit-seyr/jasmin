"""Tests for CrateOrderContentService."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.errors import (
    CrateLineOfferBound,
    CrateLineOfferBoundFields,
    CratesDisabledOnDocuments,
)
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
from apps.shared.tenants.models import TenantSettings


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
        # collapse to a single row reporting the max price; they stay distinct
        # so price / line_netto are exact and match
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
        # max-inflated 9 * 3.00 = 27.00 a max() aggregation would give.
        total = sum(Decimal(row["line_netto"]) for row in summary)
        assert total == Decimal("24.50")

    def test_each_line_says_how_many_crates_come_with_order_lines(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        _make_coc(order, crate, amount=5)
        CrateOrderContent.objects.create(
            order=order,
            crate_type=crate,
            amount=2,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
            note="Pallet",
        )

        (line,) = CrateOrderContentService.get_crates_summary_for_period(
            2026, 15, 2, reseller
        )

        assert (line["amount"], line["offer_bound_amount"], line["note"]) == (
            7,
            5,
            "Pallet",
        )

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
        row = CrateOrderContent.objects.get(crate_type=crate)
        assert result["id"] == f"{crate.pk}_{row.pk}"
        assert result["amount"] == Decimal("10")
        # Money out as canonical 2dp strings (not Decimal/float), with
        # backend-computed line_netto = 10 * 3.00.
        assert result["price_per_unit"] == "3.00"
        assert result["line_netto"] == "30.00"
        assert Order.objects.filter(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        ).exists()

    def test_rejected_when_crates_off_documents(self, tenant):
        """The manual crate-create path is gated too — a direct call while the
        tenant keeps crates OFF documents raises, closing the API bypass the
        hidden office UI would otherwise leave open."""
        TenantSettings.objects.create(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(seconds=1),
            crates_should_be_on_documents=False,
        )
        reseller = ResellerFactory()
        crate = CrateFactory()
        CrateNetPriceFactory(crate=crate, price=Decimal("3.00"))

        with pytest.raises(CratesDisabledOnDocuments):
            CrateOrderContentService.create_crate_order_content(
                crate_type_id=crate.pk,
                amount=Decimal("10"),
                year=2026,
                delivery_week=15,
                day_number=2,
                reseller=reseller.pk,
            )
        assert CrateOrderContent.objects.count() == 0

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

    def test_create_answers_with_the_note_of_the_line_it_joins(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        _make_coc(order, crate, amount=4, price=Decimal("2.00"))
        CrateOrderContent.objects.create(
            order=order,
            crate_type=crate,
            amount=1,
            price_per_unit=Decimal("2.00"),
            tax_rate=Decimal("19.00"),
            note="Pallet",
        )

        result = CrateOrderContentService.create_crate_order_content(
            crate_type_id=crate.pk,
            amount=Decimal("2"),
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller.pk,
            price_per_unit=Decimal("2.00"),
            tax_rate=Decimal("19.00"),
        )

        assert (result["amount"], result["offer_bound_amount"], result["note"]) == (
            7,
            4,
            "Pallet",
        )

    def test_explicit_zero_price_is_preserved(self, tenant):
        """An explicit ``price_per_unit=0`` (a legitimate zero-deposit
        crate) must NOT be overwritten by the crate's dated pricing. A falsy
        ``if not price_per_unit`` check would treat 0 as unset and silently
        replace it; an ``is None`` check honours the explicit 0."""
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
# update_crate_order_content_line
# ---------------------------------------------------------------------------
def _update(reseller, line_id, **update_data):
    return CrateOrderContentService.update_crate_order_content_line(
        line_id=line_id,
        year=2026,
        delivery_week=15,
        day_number=2,
        reseller=reseller,
        update_data=update_data,
    )


@pytest.mark.django_db
class TestUpdateCrateOrderContentLine:
    def test_a_line_of_one_direct_row_takes_the_new_amount_itself(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        row = CrateOrderContent.objects.create(
            order=order,
            crate_type=crate,
            amount=3,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
        )

        result = _update(reseller, f"{crate.pk}_{row.pk}", amount=5, note="Pallet")

        row.refresh_from_db()
        assert (row.amount, row.note) == (5, "Pallet")
        assert CrateOrderContent.objects.filter(crate_type=crate).count() == 1
        assert result["id"] == f"{crate.pk}_{row.pk}"

    def test_an_offer_bound_line_gets_a_direct_row_at_its_values(self, tenant):
        """An offer-bound row is rebuilt whenever its order line is saved, so
        the difference goes on a new row added to the order, at the line's
        price, rabatt and tax rate so that it stays part of the line."""
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        deposit = _make_coc(order, crate, amount=4, price=Decimal("2.50"), rabatt=5)

        result = _update(reseller, f"{crate.pk}_{deposit.pk}", amount=6)

        deposit.refresh_from_db()
        assert deposit.amount == 4
        added = CrateOrderContent.objects.get(order=order, crate_type=crate)
        assert (added.amount, added.price_per_unit, added.rabatt, added.tax_rate) == (
            2,
            Decimal("2.50"),
            5,
            Decimal("19.00"),
        )
        assert result["amount"] == 6
        assert result["id"] == f"{crate.pk}_{min(deposit.pk, added.pk)}"

    def test_a_reduction_with_a_new_price_reprices_the_rows_it_keeps(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        deposit = CrateOrderContent.objects.create(
            order=order,
            crate_type=crate,
            amount=4,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
        )
        line_id = f"{crate.pk}_{deposit.pk}"

        result = _update(
            reseller, line_id, amount=3, price_per_unit=Decimal("2.60"), rabatt=10
        )

        deposit.refresh_from_db()
        assert (deposit.amount, deposit.price_per_unit, deposit.rabatt) == (
            3,
            Decimal("2.60"),
            10,
        )
        assert list(CrateOrderContent.objects.filter(crate_type=crate)) == [deposit]
        assert (result["id"], result["amount"], result["price_per_unit"]) == (
            line_id,
            3,
            "2.60",
        )

    def test_a_bare_crate_type_id_lowers_the_type_on_its_added_rows(self, tenant):
        """A page that names a line by its crate type alone lowers the type's
        total; the crates come off the rows added to the order, and no row is
        added or left below zero."""
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        deposit = _make_coc(order, crate, amount=2)
        for amount in (2, 1):
            CrateOrderContent.objects.create(
                order=order,
                crate_type=crate,
                amount=amount,
                price_per_unit=Decimal("2.50"),
                tax_rate=Decimal("19.00"),
            )

        result = _update(reseller, crate.pk, amount=3)

        amounts = CrateOrderContent.objects.filter(crate_type=crate).values_list(
            "amount", flat=True
        )
        assert sum(amounts) == 3
        assert min(amounts) > 0
        deposit.refresh_from_db()
        assert deposit.amount == 2
        assert result["amount"] == 3

    def test_a_reduction_below_the_deposit_crates_is_refused(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        _make_coc(order, crate, amount=2)
        _make_coc(order, crate, amount=1)

        with pytest.raises(CrateLineOfferBound) as raised:
            _update(reseller, crate.pk, amount=2)

        assert raised.value.details == {"offer_bound_amount": 3}
        amounts = CrateOrderContent.objects.filter(crate_type=crate).values_list(
            "amount", flat=True
        )
        assert sorted(amounts) == [1, 2]

    @pytest.mark.parametrize(
        "change",
        [{"price_per_unit": Decimal("3.00")}, {"rabatt": 10}, {"note": "Pallet"}],
        ids=["price", "rabatt", "note"],
    )
    def test_a_price_rabatt_or_note_on_deposit_crates_is_refused(self, tenant, change):
        """The order line rebuilds its deposit rows at the dated price, with no
        rabatt and no note, so the change would not last."""
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        deposit = _make_coc(order, crate, amount=4)

        with pytest.raises(CrateLineOfferBoundFields) as raised:
            _update(reseller, f"{crate.pk}_{deposit.pk}", amount=4, **change)

        assert raised.value.code == "crate_line.offer_bound_fields"
        assert raised.value.details == {"offer_bound_amount": 4}
        deposit.refresh_from_db()
        assert (deposit.price_per_unit, deposit.rabatt, deposit.note) == (
            Decimal("2.50"),
            None,
            None,
        )

    def test_a_type_without_rows_in_the_period_is_not_found(self, tenant):
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller, year=2026, delivery_week=15, day_number=2)

        with pytest.raises(CrateOrderContent.DoesNotExist):
            _update(reseller, CrateFactory().pk, amount=5)


# ---------------------------------------------------------------------------
# delete_crate_order_content_line
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteCrateOrderContentLine:
    def test_deletes_the_rows_added_to_the_order(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        for amount in (5, 3):
            CrateOrderContent.objects.create(
                order=order,
                crate_type=crate,
                amount=amount,
                price_per_unit=Decimal("2.50"),
                tax_rate=Decimal("19.00"),
            )

        deleted = CrateOrderContentService.delete_crate_order_content_line(
            line_id=crate.pk,
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller,
        )

        assert deleted is True
        assert CrateOrderContent.objects.filter(crate_type=crate).count() == 0

    def test_deposit_crates_alone_are_refused(self, tenant):
        """Deposit crates come with their order line; the period branch leaves
        them to it like the order branch does."""
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        _make_coc(order, crate, amount=5)

        with pytest.raises(CrateLineOfferBound):
            CrateOrderContentService.delete_crate_order_content_line(
                line_id=crate.pk,
                year=2026,
                delivery_week=15,
                day_number=2,
                reseller=reseller,
            )

        assert CrateOrderContent.objects.filter(crate_type=crate).count() == 1

    def test_a_line_id_deletes_only_its_line_in_the_period(self, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        crate = CrateFactory()
        kept = _make_coc(order, crate, amount=5, price=Decimal("2.00"))
        removed = CrateOrderContent.objects.create(
            order=order,
            crate_type=crate,
            amount=3,
            price_per_unit=Decimal("2.50"),
            tax_rate=Decimal("19.00"),
        )

        deleted = CrateOrderContentService.delete_crate_order_content_line(
            line_id=f"{crate.pk}_{removed.pk}",
            year=2026,
            delivery_week=15,
            day_number=2,
            reseller=reseller,
        )

        assert deleted is True
        assert list(CrateOrderContent.objects.filter(crate_type=crate)) == [kept]

    def test_returns_false_with_no_context(self, tenant):
        deleted = CrateOrderContentService.delete_crate_order_content_line(
            line_id="fake-id",
        )
        assert deleted is False
