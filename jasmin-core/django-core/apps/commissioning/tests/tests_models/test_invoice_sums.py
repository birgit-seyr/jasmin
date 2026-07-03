"""Tests for InvoiceReseller.sum_netto with various articles, tax rates, and discounts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    InvoiceResellerContent,
)
from apps.commissioning.services import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
    InvoiceResellerFactory,
    ShareArticleFactory,
)


def _add_item(
    invoice, *, amount, price_per_unit, rabatt=None, tax_rate=Decimal("7.00")
):
    """Add an article line item to an invoice.

    ``tax_rate`` is required on the column now, so the helper defaults to
    7 % (the canonical article tax rate). Tests that exercise multi-rate
    invoices override it.
    """
    return InvoiceResellerContent.objects.create(
        invoice=invoice,
        share_article=ShareArticleFactory(),
        amount=Decimal(str(amount)),
        price_per_unit=Decimal(str(price_per_unit)),
        unit="KG",
        size="M",
        rabatt=rabatt,
        tax_rate=Decimal(str(tax_rate)),
    )


def _add_crate(
    invoice, *, amount, price_per_unit, rabatt=None, tax_rate=Decimal("19.00")
):
    """Add a crate line item to an invoice."""
    return CrateContentInvoiceReseller.objects.create(
        invoice=invoice,
        crate_type=CrateFactory(),
        amount=amount,
        price_per_unit=Decimal(str(price_per_unit)),
        rabatt=rabatt,
        tax_rate=tax_rate,
    )


def _tax_for_item(amount, price_per_unit, tax_rate, rabatt=0):
    """Compute the expected tax for a single line item."""
    amount = Decimal(str(amount))
    price = Decimal(str(price_per_unit))
    rabatt = Decimal(str(rabatt or 0))
    rate = Decimal(str(tax_rate or 0))
    net = amount * price * (1 - rabatt / 100)
    return (net * rate / 100).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# sum_netto (net) — article items
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTotalPriceSingleItem:
    def test_single_item_no_discount(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.50")

        # 10 * 2.50 = 25.00
        assert invoice.sum_netto == Decimal("25.00")

    def test_single_item_with_discount(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.50", rabatt=20)

        # 10 * 2.50 * (1 - 20/100) = 25 * 0.80 = 20.00
        assert invoice.sum_netto == Decimal("20.00")

    def test_single_item_100_percent_discount(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=5, price_per_unit="10.00", rabatt=100)

        assert invoice.sum_netto == Decimal("0.00")

    def test_single_item_fractional_amount(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount="0.500", price_per_unit="3.40")

        # 0.500 * 3.40 = 1.70
        assert invoice.sum_netto == Decimal("1.70")


@pytest.mark.django_db
class TestTotalPriceMultipleItems:
    def test_multiple_articles_different_prices(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.50")  # 25.00
        _add_item(invoice, amount=5, price_per_unit="4.00")  # 20.00
        _add_item(invoice, amount=3, price_per_unit="1.00")  #  3.00

        assert invoice.sum_netto == Decimal("48.00")

    def test_multiple_articles_different_discounts(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.00", rabatt=0)  # 20.00
        _add_item(invoice, amount=10, price_per_unit="2.00", rabatt=10)  # 18.00
        _add_item(invoice, amount=10, price_per_unit="2.00", rabatt=50)  # 10.00

        assert invoice.sum_netto == Decimal("48.00")

    def test_multiple_articles_different_tax_rates_net_unaffected(self, tenant):
        """tax_rate does NOT affect sum_netto (which is net)."""
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.00", tax_rate="7.00")
        _add_item(invoice, amount=10, price_per_unit="2.00", tax_rate="19.00")

        # Net total: 20 + 20 = 40  (tax_rate does not change net)
        assert invoice.sum_netto == Decimal("40.00")


# ---------------------------------------------------------------------------
# sum_netto — crate items
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTotalPriceCrates:
    def test_crate_items_included_in_total(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_crate(invoice, amount=4, price_per_unit="2.50")

        # 4 * 2.50 = 10.00
        assert invoice.sum_netto == Decimal("10.00")

    def test_crate_with_discount(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_crate(invoice, amount=10, price_per_unit="5.00", rabatt=25)

        # 10 * 5.00 * 0.75 = 37.50
        assert invoice.sum_netto == Decimal("37.50")


# ---------------------------------------------------------------------------
# sum_netto — mixed articles + crates
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTotalPriceMixed:
    def test_articles_and_crates_summed(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.50")  # 25.00
        _add_item(invoice, amount=5, price_per_unit="4.00", rabatt=10)  # 18.00
        _add_crate(invoice, amount=4, price_per_unit="2.50")  # 10.00

        assert invoice.sum_netto == Decimal("53.00")

    def test_many_items_full_scenario(self, tenant):
        """Realistic invoice: several articles at 7% tax, one at 19%, crates at 19%."""
        invoice = InvoiceResellerFactory()

        # Carrots: 25.500 kg @ 1.80 /kg, no discount, 7% tax
        _add_item(
            invoice, amount="25.500", price_per_unit="1.80", rabatt=0, tax_rate="7.00"
        )
        # Potatoes: 40.000 kg @ 0.95 /kg, 5% discount, 7% tax
        _add_item(
            invoice, amount="40.000", price_per_unit="0.95", rabatt=5, tax_rate="7.00"
        )
        # Tomatoes: 12.000 kg @ 3.50 /kg, no discount, 7% tax
        _add_item(
            invoice, amount="12.000", price_per_unit="3.50", rabatt=0, tax_rate="7.00"
        )
        # Herbs (processed): 2.000 kg @ 12.00 /kg, 10% discount, 19% tax
        _add_item(
            invoice, amount="2.000", price_per_unit="12.00", rabatt=10, tax_rate="19.00"
        )
        # Crates: 6 @ 2.50 each, no discount, 19% tax
        _add_crate(invoice, amount=6, price_per_unit="2.50", rabatt=0, tax_rate="19.00")

        # Line-by-line net:
        # Carrots:  25.500 * 1.80 * 1.00  = 45.90
        # Potatoes: 40.000 * 0.95 * 0.95  = 36.10
        # Tomatoes: 12.000 * 3.50 * 1.00  = 42.00
        # Herbs:     2.000 * 12.00 * 0.90 = 21.60
        # Crates:    6     * 2.50  * 1.00  = 15.00
        expected_net = (
            Decimal("45.90")
            + Decimal("36.10")
            + Decimal("42.00")
            + Decimal("21.60")
            + Decimal("15.00")
        )
        assert expected_net == Decimal("160.60")
        assert invoice.sum_netto == expected_net


# ---------------------------------------------------------------------------
# storno creates negated amounts → sum_netto cancels out
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStornoSums:
    def test_storno_has_negated_total(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="3.00", rabatt=0)
        _add_item(invoice, amount=5, price_per_unit="4.00", rabatt=20)
        InvoiceService.finalize_invoice(invoice, user=user)

        # Net: 30.00 + 16.00 = 46.00
        assert invoice.sum_netto == Decimal("46.00")

        storno = InvoiceService.create_storno(
            invoice, reason="Test cancellation", user=user
        )

        # Storno should have the same magnitude but negative
        assert storno.sum_netto == Decimal("-46.00")
        assert storno.document_type == "storno"
        assert storno.is_finalized is True

    def test_storno_with_mixed_items(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = InvoiceResellerFactory()
        _add_item(
            invoice, amount="15.000", price_per_unit="2.00", rabatt=10, tax_rate="7.00"
        )
        _add_item(
            invoice, amount="8.000", price_per_unit="5.00", rabatt=0, tax_rate="19.00"
        )
        InvoiceService.finalize_invoice(invoice, user=user)

        # Net: 15*2*0.9 = 27.00 + 8*5*1.0 = 40.00 → 67.00
        assert invoice.sum_netto == Decimal("67.00")

        storno = InvoiceService.create_storno(invoice, reason="Bad delivery", user=user)
        assert storno.sum_netto == Decimal("-67.00")


# ---------------------------------------------------------------------------
# Storno mirrors original (sums + line-by-line equivalence)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStornoMirrorsOriginal:
    """A storno must be the exact negative of the cancelled invoice — same
    line items, same crate items, same per-line attributes, opposite amounts.

    These tests would fail before the crate_items copy was added to
    ``InvoiceService.create_storno``: the original invoice had crates but the
    storno did not, so ``sum_netto`` and ``sum_brutto`` would not cancel out.
    """

    def _build_full_invoice(self):
        """Build a realistic invoice with mixed line items and crate items."""
        invoice = InvoiceResellerFactory()
        # 7% items
        _add_item(
            invoice,
            amount="25.500",
            price_per_unit="1.80",
            rabatt=0,
            tax_rate="7.00",
        )
        _add_item(
            invoice,
            amount="40.000",
            price_per_unit="0.95",
            rabatt=5,
            tax_rate="7.00",
        )
        # 19% item
        _add_item(
            invoice,
            amount="2.000",
            price_per_unit="12.00",
            rabatt=10,
            tax_rate="19.00",
        )
        # Crate items at two different tax rates / discounts
        _add_crate(invoice, amount=6, price_per_unit="2.50", rabatt=0, tax_rate="19.00")
        _add_crate(invoice, amount=4, price_per_unit="3.00", rabatt=10, tax_rate="7.00")
        return invoice

    def test_storno_net_total_cancels_original(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = self._build_full_invoice()
        InvoiceService.finalize_invoice(invoice, user=user)

        storno = InvoiceService.create_storno(
            invoice, reason="Test cancellation", user=user
        )

        assert storno.sum_netto == -invoice.sum_netto
        assert invoice.sum_netto + storno.sum_netto == Decimal("0.00")

    def test_storno_gross_total_cancels_original(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = self._build_full_invoice()
        InvoiceService.finalize_invoice(invoice, user=user)

        storno = InvoiceService.create_storno(
            invoice, reason="Test cancellation", user=user
        )

        assert storno.sum_brutto == -invoice.sum_brutto
        assert invoice.sum_brutto + storno.sum_brutto == Decimal("0.00")

    def test_storno_has_same_number_of_line_items(self, tenant):
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = self._build_full_invoice()
        InvoiceService.finalize_invoice(invoice, user=user)

        storno = InvoiceService.create_storno(
            invoice, reason="Test cancellation", user=user
        )

        assert storno.items.count() == invoice.items.count()
        assert storno.crate_items.count() == invoice.crate_items.count()
        # Sanity check: the fixture really does include crates.
        assert invoice.crate_items.count() == 2

    def test_storno_line_items_mirror_originals(self, tenant):
        """Each storno article line copies all per-line attributes from the
        corresponding original line and negates only ``amount``."""
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = self._build_full_invoice()
        InvoiceService.finalize_invoice(invoice, user=user)

        storno = InvoiceService.create_storno(invoice, reason="Mirror test", user=user)

        # Pair each original item with the storno item built from it. We
        # match by (share_article_id, price_per_unit, tax_rate) since those
        # are unique within this test fixture.
        original_by_key = {
            (i.share_article_id, i.price_per_unit, i.tax_rate, i.rabatt): i
            for i in invoice.items.all()
        }
        for storno_item in storno.items.all():
            key = (
                storno_item.share_article_id,
                storno_item.price_per_unit,
                storno_item.tax_rate,
                storno_item.rabatt,
            )
            original = original_by_key[key]
            assert storno_item.amount == -original.amount
            assert storno_item.unit == original.unit
            assert storno_item.size == original.size
            assert storno_item.order_content_id == original.order_content_id
            assert storno_item.offer_id == original.offer_id

    def test_storno_crate_items_mirror_originals(self, tenant):
        """Each storno crate line copies all per-line attributes from the
        corresponding original crate line and negates only ``amount``."""
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = self._build_full_invoice()
        InvoiceService.finalize_invoice(invoice, user=user)

        storno = InvoiceService.create_storno(invoice, reason="Mirror test", user=user)

        original_by_key = {
            (c.crate_type_id, c.price_per_unit, c.tax_rate, c.rabatt): c
            for c in invoice.crate_items.all()
        }
        for storno_crate in storno.crate_items.all():
            key = (
                storno_crate.crate_type_id,
                storno_crate.price_per_unit,
                storno_crate.tax_rate,
                storno_crate.rabatt,
            )
            original = original_by_key[key]
            assert storno_crate.amount == -original.amount
            assert storno_crate.note == original.note

    def test_storno_metadata(self, tenant):
        """The storno itself is finalized, typed correctly, and links back
        to the cancelled invoice (and vice versa)."""
        from apps.commissioning.tests.factories import JasminUserFactory

        user = JasminUserFactory()
        invoice = self._build_full_invoice()
        InvoiceService.finalize_invoice(invoice, user=user)

        storno = InvoiceService.create_storno(
            invoice, reason="Metadata test", user=user
        )

        invoice.refresh_from_db()
        assert storno.document_type == "storno"
        assert storno.is_finalized is True
        assert storno.cancels_invoice_id == invoice.id
        assert storno.correction_reason == "Metadata test"
        assert storno.reseller_id == invoice.reseller_id
        assert invoice.cancelled_by_invoice_id == storno.id


# ---------------------------------------------------------------------------
# Tax computation helpers (per line item, for verification)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTaxComputation:
    """Verify that tax can be correctly computed per tax rate grouping."""

    def test_tax_amounts_per_rate(self, tenant):
        invoice = InvoiceResellerFactory()

        # 7% items
        _add_item(
            invoice, amount=10, price_per_unit="2.00", rabatt=0, tax_rate="7.00"
        )  # net 20.00
        _add_item(
            invoice, amount=5, price_per_unit="4.00", rabatt=10, tax_rate="7.00"
        )  # net 18.00

        # 19% items
        _add_item(
            invoice, amount=3, price_per_unit="10.00", rabatt=0, tax_rate="19.00"
        )  # net 30.00

        # 19% crate
        _add_crate(
            invoice, amount=4, price_per_unit="2.50", rabatt=0, tax_rate="19.00"
        )  # net 10.00

        # Group by tax rate and compute tax
        tax_groups: dict[Decimal, Decimal] = {}
        for item in invoice.items.all():
            rate = item.tax_rate or Decimal("0")
            net = Decimal(str(item.amount)) * Decimal(str(item.price_per_unit))
            net *= 1 - Decimal(str(item.rabatt or 0)) / 100
            tax_groups[rate] = tax_groups.get(rate, Decimal("0")) + net * rate / 100

        for crate in invoice.crate_items.all():
            rate = crate.tax_rate or Decimal("0")
            net = Decimal(str(crate.amount)) * Decimal(str(crate.price_per_unit))
            net *= 1 - Decimal(str(crate.rabatt or 0)) / 100
            tax_groups[rate] = tax_groups.get(rate, Decimal("0")) + net * rate / 100

        # 7% group: (20 + 18) = 38 * 0.07 = 2.66
        assert tax_groups[Decimal("7.00")].quantize(Decimal("0.01")) == Decimal("2.66")

        # 19% group: (30 + 10) = 40 * 0.19 = 7.60
        assert tax_groups[Decimal("19.00")].quantize(Decimal("0.01")) == Decimal("7.60")

        # Total net
        assert invoice.sum_netto == Decimal("78.00")

        # Total gross = net + all taxes
        total_tax = sum(v.quantize(Decimal("0.01")) for v in tax_groups.values())
        assert total_tax == Decimal("10.26")
        assert invoice.sum_netto + total_tax == Decimal("88.26")

    def test_full_invoice_breakdown(self, tenant):
        """Complete real-world invoice with net/tax/gross breakdown."""
        invoice = InvoiceResellerFactory()

        # Vegetables (7% tax)
        _add_item(
            invoice, amount="30.000", price_per_unit="1.50", rabatt=0, tax_rate="7.00"
        )  # 45.00
        _add_item(
            invoice, amount="20.000", price_per_unit="2.20", rabatt=15, tax_rate="7.00"
        )  # 37.40
        _add_item(
            invoice, amount="10.000", price_per_unit="3.00", rabatt=0, tax_rate="7.00"
        )  # 30.00
        _add_item(
            invoice, amount="5.500", price_per_unit="4.80", rabatt=5, tax_rate="7.00"
        )  # 25.08

        # Processed goods (19% tax)
        _add_item(
            invoice, amount="3.000", price_per_unit="8.50", rabatt=0, tax_rate="19.00"
        )  # 25.50
        _add_item(
            invoice, amount="1.500", price_per_unit="15.00", rabatt=10, tax_rate="19.00"
        )  # 20.25

        # Crates (19% tax)
        _add_crate(
            invoice, amount=8, price_per_unit="2.50", rabatt=0, tax_rate="19.00"
        )  # 20.00
        _add_crate(
            invoice, amount=3, price_per_unit="3.00", rabatt=0, tax_rate="19.00"
        )  #  9.00

        # Expected nets by line:
        net_7 = (
            Decimal("45.00") + Decimal("37.40") + Decimal("30.00") + Decimal("25.08")
        )  # 137.48
        net_19 = (
            Decimal("25.50") + Decimal("20.25") + Decimal("20.00") + Decimal("9.00")
        )  #  74.75
        total_net = net_7 + net_19  # 212.23

        assert net_7 == Decimal("137.48")
        assert net_19 == Decimal("74.75")
        assert total_net == Decimal("212.23")
        assert invoice.sum_netto == total_net

        # Tax
        tax_7 = (net_7 * Decimal("7") / 100).quantize(Decimal("0.01"))  # 9.62
        tax_19 = (net_19 * Decimal("19") / 100).quantize(Decimal("0.01"))  # 14.20

        assert tax_7 == Decimal("9.62")
        assert tax_19 == Decimal("14.20")

        # Gross
        total_gross = total_net + tax_7 + tax_19  # 236.05
        assert total_gross == Decimal("236.05")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEdgeCases:
    def test_empty_invoice(self, tenant):
        invoice = InvoiceResellerFactory()
        assert invoice.sum_netto == Decimal("0.00")

    def test_item_with_zero_amount(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=0, price_per_unit="5.00")

        assert invoice.sum_netto == Decimal("0.00")

    def test_item_with_zero_price(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="0.00")

        assert invoice.sum_netto == Decimal("0.00")

    def test_item_with_no_rabatt(self, tenant):
        """rabatt=None should be treated as 0% discount."""
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount=10, price_per_unit="2.00", rabatt=None)

        assert invoice.sum_netto == Decimal("20.00")

    def test_small_fractional_amounts(self, tenant):
        invoice = InvoiceResellerFactory()
        _add_item(invoice, amount="0.001", price_per_unit="0.01")

        # 0.001 * 0.01 = 0.00001 → quantized to 0.00
        assert invoice.sum_netto == Decimal("0.00")

    def test_large_invoice_many_items(self, tenant):
        """Invoice with 20 items to ensure summation accuracy."""
        invoice = InvoiceResellerFactory()

        expected = Decimal("0")
        for i in range(1, 21):
            amount = Decimal(str(i))
            price = Decimal("1.50")
            rabatt = i % 3 * 5  # 0, 5, 10, 0, 5, 10, ...
            _add_item(
                invoice,
                amount=amount,
                price_per_unit=price,
                rabatt=rabatt,
                tax_rate="7.00" if i % 2 == 0 else "19.00",
            )
            # Mirror the model: round each line individually before summing,
            # which is the standard invoice convention (sum-of-rounded-lines,
            # not rounded-sum-of-raw-lines).
            line_net = (amount * price * (1 - Decimal(str(rabatt)) / 100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            expected += line_net

        assert invoice.sum_netto == expected.quantize(Decimal("0.01"))
