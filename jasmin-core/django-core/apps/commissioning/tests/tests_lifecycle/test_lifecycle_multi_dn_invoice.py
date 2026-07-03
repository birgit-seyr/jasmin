"""End-to-end integration tests for the Order → DeliveryNote → Invoice
chain at scale, including invoices built from multiple delivery notes.

What this exercises
-------------------
* Many orders (different resellers + same reseller, multiple weeks).
* A delivery note is created for each order; the order auto-finalizes.
* Invoices are created in two flavours:
    * ``InvoiceService.create_from_delivery_note`` — one invoice per DN.
      Creating the invoice auto-finalizes the DN (cascade-up contract).
    * ``InvoiceService.create_summary_invoice_from_delivery_notes`` —
      one summary invoice for *several* finalized DNs of the same
      reseller, with per-article amounts grouped + summed and crate
      contents merged per crate-type.
* Sums (``sum_netto`` / ``sum_brutto`` / ``tax_breakdown``) are checked
  on every level (Order, DN, Invoice) so the totals shown on the PDF
  are correct.
* Both line items and crate items are present on every invoice, so
  nothing falls off the document.

These tests are deliberately self-contained: they only use service
entry-points so the cascade-up finalize, the legal one-way contract
and the auto-cleanup behaviour are all exercised together.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateOrderContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
    Order,
)
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
    OfferFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.shared.tenants.models import TenantSettings
from core.errors import JasminError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PRICE_QUANTIZE = Decimal("0.01")


def _ensure_settings(tenant):
    TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults=dict(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(days=365),
            valid_until=None,
        ),
    )


def _quant(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PRICE_QUANTIZE)


def _line_netto(amount, price, rabatt=0, tax=Decimal("7")) -> Decimal:
    """Mirror of models.mixin._calc_line_netto for assertion math."""
    return _quant(
        Decimal(amount)
        * Decimal(price)
        * (Decimal("1") - Decimal(rabatt) / Decimal("100"))
    )


def _make_order_with_lines(
    reseller,
    *,
    week=15,
    article_lines: list[tuple[Decimal, Decimal, Decimal]] | None = None,
    crate_lines: list[tuple[int, Decimal, Decimal]] | None = None,
) -> Order:
    """Create an order with multiple article + crate rows.

    ``article_lines``: list of ``(amount, price_per_unit, tax_rate)``.
    ``crate_lines``:   list of ``(amount, price_per_unit, tax_rate)``.
    """
    article_lines = article_lines or []
    crate_lines = crate_lines or []

    order = OrderFactory(reseller=reseller, year=2026, delivery_week=week, day_number=2)

    for amount, price, tax in article_lines:
        OrderContentFactory(
            order=order,
            share_article=ShareArticleFactory(),
            amount=amount,
            price_per_unit=price,
            tax_rate=tax,
            unit="KG",
            size="M",
        )

    for amount, price, tax in crate_lines:
        CrateOrderContent.objects.create(
            order=order,
            crate_type=CrateFactory(),
            amount=amount,
            price_per_unit=price,
            tax_rate=tax,
        )

    return order


def _expected_doc_totals(article_lines, crate_lines) -> dict:
    """Compute expected sum_netto / sum_brutto / tax_breakdown
    for a single (order/DN/invoice) document with the given lines."""
    buckets: dict[Decimal, Decimal] = {}
    for amount, price, tax in list(article_lines) + list(crate_lines):
        netto = _line_netto(amount, price, tax=tax)
        buckets[Decimal(tax)] = buckets.get(Decimal(tax), Decimal("0")) + netto

    breakdown = []
    sum_netto = Decimal("0")
    sum_brutto = Decimal("0")
    for rate in sorted(buckets):
        netto = _quant(buckets[rate])
        tax = _quant(netto * rate / Decimal("100"))
        brutto = _quant(netto + tax)
        breakdown.append({"rate": rate, "netto": netto, "tax": tax, "brutto": brutto})
        sum_netto += netto
        sum_brutto += brutto

    return {
        "sum_netto": _quant(sum_netto),
        "sum_brutto": _quant(sum_brutto),
        "tax_breakdown": breakdown,
    }


def _assert_totals(doc, expected):
    """Compare a Order/DN/Invoice's computed totals against expected."""
    assert _quant(doc.sum_netto) == expected["sum_netto"], (
        f"sum_netto mismatch on {type(doc).__name__} {doc.pk}: "
        f"{doc.sum_netto} != {expected['sum_netto']}"
    )
    assert _quant(doc.sum_brutto) == expected["sum_brutto"], (
        f"sum_brutto mismatch on {type(doc).__name__} {doc.pk}: "
        f"{doc.sum_brutto} != {expected['sum_brutto']}"
    )
    actual_breakdown = [
        {
            "rate": Decimal(g["rate"]),
            "netto": _quant(g["netto"]),
            "tax": _quant(g["tax"]),
            "brutto": _quant(g["brutto"]),
        }
        for g in doc.tax_breakdown
    ]
    assert actual_breakdown == expected["tax_breakdown"], (
        f"tax_breakdown mismatch on {type(doc).__name__} {doc.pk}:\n"
        f"  actual:   {actual_breakdown}\n"
        f"  expected: {expected['tax_breakdown']}"
    )


# ===================================================================
# 1. Many orders → many DNs → individual invoices (the simple chain)
# ===================================================================
@pytest.mark.django_db
class TestManyOrdersIndividualInvoices:
    """Build a realistic batch: 5 orders for 3 different resellers, each
    with multiple article rows + multiple crate rows. For every order
    create a DN, then create an individual invoice. Verify totals on
    every level + both content types are present + cascade-up finalize
    locks every parent."""

    def test_full_chain_keeps_sums_and_finalizes_everything(self, tenant):
        _ensure_settings(connection.tenant)

        resellers = [ResellerFactory() for _ in range(3)]

        # Each row: (reseller, week, article_lines, crate_lines)
        order_specs = [
            (
                resellers[0],
                15,
                [(Decimal("2"), Decimal("3.50"), Decimal("7"))],
                [(2, Decimal("1.50"), Decimal("19"))],
            ),
            (
                resellers[0],
                16,
                [
                    (Decimal("4"), Decimal("2.00"), Decimal("7")),
                    (Decimal("1"), Decimal("9.99"), Decimal("19")),
                ],
                [(1, Decimal("2.50"), Decimal("19"))],
            ),
            (
                resellers[1],
                15,
                [
                    (Decimal("3"), Decimal("4.00"), Decimal("7")),
                    (Decimal("2"), Decimal("1.25"), Decimal("7")),
                ],
                [(3, Decimal("2.00"), Decimal("19"))],
            ),
            (
                resellers[2],
                15,
                [(Decimal("10"), Decimal("0.99"), Decimal("7"))],
                [(5, Decimal("2.00"), Decimal("19"))],
            ),
            (
                resellers[2],
                17,
                [
                    (Decimal("1"), Decimal("12.50"), Decimal("19")),
                    (Decimal("6"), Decimal("0.75"), Decimal("7")),
                ],
                [],  # no crates on this one
            ),
        ]

        invoices = []
        for reseller, week, articles, crates in order_specs:
            order = _make_order_with_lines(
                reseller, week=week, article_lines=articles, crate_lines=crates
            )
            expected = _expected_doc_totals(articles, crates)

            # Order totals correct before any finalize.
            _assert_totals(order, expected)

            dn = DeliveryNoteService.create_from_order(order=order)
            order.refresh_from_db()
            dn.refresh_from_db()

            # Cascade-up: order is now finalized.
            assert order.is_finalized is True
            assert dn.is_finalized is False

            # DN totals correct (snapshotted from order).
            _assert_totals(dn, expected)

            invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
            invoice.refresh_from_db()
            dn.refresh_from_db()
            order.refresh_from_db()

            # Cascade-up: DN auto-finalized when invoice was created.
            assert dn.is_finalized is True
            # Order stays finalized.
            assert order.is_finalized is True
            # Invoice itself is still a draft.
            assert invoice.is_finalized is False

            # Invoice totals match expected (one invoice per DN, so
            # they equal the DN's totals).
            _assert_totals(invoice, expected)

            # Both content types are wired through.
            assert invoice.items.count() == len(articles)
            assert invoice.crate_items.count() == len(crates)

            invoices.append(invoice)

        # Now finalize every invoice. The full chain must remain
        # consistent and immutable.
        for invoice in invoices:
            InvoiceService.finalize_invoice(invoice)
            invoice.refresh_from_db()
            assert invoice.is_finalized is True

        # And under the one-way contract, none of the parents can be
        # unfinalized.
        for invoice in invoices:
            with pytest.raises(JasminError, match="immutable"):
                invoice.unfinalize()


# ===================================================================
# 2. Summary invoice from multiple DNs (different weeks, same reseller)
# ===================================================================
@pytest.mark.django_db
class TestSummaryInvoiceFromMultipleDeliveryNotes:
    """Same reseller, three weeks of orders → DNs → ONE summary invoice.

    Verifies:
    * Lines with the same (article, unit, size, price) are merged across
      DNs and amounts summed.
    * Crate rows of the same crate-type are merged across DNs.
    * Sums on the summary invoice equal the sum of its source DNs.
    * Tax breakdown is per-rate, not per-line.
    * Every source DN is referenced via the invoice-content M2M.
    """

    def test_merges_articles_and_crates_across_three_dns(self, tenant):
        _ensure_settings(connection.tenant)

        reseller = ResellerFactory()

        # Two share articles + two crate types, used across three weeks.
        article_a = ShareArticleFactory()
        article_b = ShareArticleFactory()
        crate_a = CrateFactory()
        crate_b = CrateFactory()

        # Each week's order: same article_a so amounts MERGE; week 17
        # adds article_b (only on one DN).
        weekly_orders = [
            {
                "week": 15,
                "articles": [
                    # (article, amount, price, tax)
                    (article_a, Decimal("2"), Decimal("3.00"), Decimal("7")),
                ],
                "crates": [
                    # (crate, amount, price, tax)
                    (crate_a, 2, Decimal("1.50"), Decimal("19")),
                ],
            },
            {
                "week": 16,
                "articles": [
                    (article_a, Decimal("3"), Decimal("3.00"), Decimal("7")),
                ],
                "crates": [
                    (crate_a, 1, Decimal("1.50"), Decimal("19")),
                    (crate_b, 4, Decimal("2.00"), Decimal("19")),
                ],
            },
            {
                "week": 17,
                "articles": [
                    (article_a, Decimal("5"), Decimal("3.00"), Decimal("7")),
                    (article_b, Decimal("1"), Decimal("9.99"), Decimal("19")),
                ],
                "crates": [
                    (crate_b, 2, Decimal("2.00"), Decimal("19")),
                ],
            },
        ]

        delivery_notes = []
        for spec in weekly_orders:
            order = OrderFactory(
                reseller=reseller, year=2026, delivery_week=spec["week"], day_number=2
            )
            for article, amount, price, tax in spec["articles"]:
                OrderContentFactory(
                    order=order,
                    share_article=article,
                    amount=amount,
                    price_per_unit=price,
                    tax_rate=tax,
                    unit="KG",
                    size="M",
                )
            for crate, amount, price, tax in spec["crates"]:
                CrateOrderContent.objects.create(
                    order=order,
                    crate_type=crate,
                    amount=amount,
                    price_per_unit=price,
                    tax_rate=tax,
                )

            dn = DeliveryNoteService.create_from_order(order=order)
            DeliveryNoteService.finalize_delivery_note(dn)
            dn.refresh_from_db()
            assert dn.is_finalized is True
            delivery_notes.append(dn)

        # Build the summary invoice across all three DNs.
        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=delivery_notes
        )
        invoice.refresh_from_db()

        # ---- Article merge ----
        # article_a is on all three DNs → merged into ONE invoice line
        # with amount 2 + 3 + 5 = 10.
        a_lines = list(invoice.items.filter(share_article=article_a))
        assert len(a_lines) == 1
        assert a_lines[0].amount == Decimal("10")
        assert a_lines[0].price_per_unit == Decimal("3.00")
        # M2M back to source DN contents must include all three.
        assert a_lines[0].delivery_note_contents.count() == 3

        # article_b only on week 17 → ONE line, amount 1.
        b_lines = list(invoice.items.filter(share_article=article_b))
        assert len(b_lines) == 1
        assert b_lines[0].amount == Decimal("1")
        assert b_lines[0].delivery_note_contents.count() == 1

        # ---- Crate merge ----
        # crate_a on weeks 15 + 16 → merged: 2 + 1 = 3.
        ca_rows = list(invoice.crate_items.filter(crate_type=crate_a))
        assert len(ca_rows) == 1
        assert ca_rows[0].amount == 3
        # crate_b on weeks 16 + 17 → merged: 4 + 2 = 6.
        cb_rows = list(invoice.crate_items.filter(crate_type=crate_b))
        assert len(cb_rows) == 1
        assert cb_rows[0].amount == 6

        # ---- Sums consistent across DNs and the summary invoice ----
        # Build expected from the FULL flat list of all lines.
        all_articles = [
            (amount, price, tax)
            for spec in weekly_orders
            for _, amount, price, tax in spec["articles"]
        ]
        all_crates = [
            (amount, price, tax)
            for spec in weekly_orders
            for _, amount, price, tax in spec["crates"]
        ]
        expected = _expected_doc_totals(all_articles, all_crates)

        _assert_totals(invoice, expected)

        # And: invoice sum == sum of DN sums (line-level rounding may
        # diverge by one cent on per-rate aggregates, so we compare on
        # netto only).
        dn_sum_netto = sum((dn.sum_netto for dn in delivery_notes), Decimal("0"))
        assert _quant(invoice.sum_netto) == _quant(dn_sum_netto)

    def test_divergent_tax_rate_lines_are_not_merged(self, tenant):
        """Two DN lines with the SAME (article, unit, size, price) but a
        different ``tax_rate`` must stay as SEPARATE invoice lines.

        Regression: ``tax_rate`` was excluded from the grouping key, so a
        VAT-rate change with the net price held constant (e.g. across a
        16%/19% reversal) merged both into one line taxed at whichever
        rate happened to be fetched first — wrong VAT on a finalized,
        hash-locked UStG §14 document.
        """
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        article = ShareArticleFactory()

        delivery_notes = []
        for week, tax in ((15, Decimal("7")), (16, Decimal("19"))):
            order = OrderFactory(
                reseller=reseller, year=2026, delivery_week=week, day_number=2
            )
            OrderContentFactory(
                order=order,
                share_article=article,
                amount=Decimal("2"),
                price_per_unit=Decimal("3.00"),
                tax_rate=tax,
                unit="KG",
                size="M",
            )
            dn = DeliveryNoteService.create_from_order(order=order)
            DeliveryNoteService.finalize_delivery_note(dn)
            delivery_notes.append(dn)

        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=delivery_notes
        )
        invoice.refresh_from_db()

        # Two distinct rates → two distinct lines (NOT one merged line).
        lines = list(invoice.items.filter(share_article=article))
        assert len(lines) == 2
        assert {line.tax_rate for line in lines} == {Decimal("7"), Decimal("19")}
        for line in lines:
            assert line.amount == Decimal("2")
        # Tax breakdown keeps both rate buckets.
        assert {group["rate"] for group in invoice.tax_breakdown} == {
            Decimal("7"),
            Decimal("19"),
        }

    def test_divergent_rabatt_lines_are_not_merged(self, tenant):
        """Same as above but for ``rabatt``: two DN lines identical except
        for the discount must not collapse onto the first line's rabatt.
        """
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        article = ShareArticleFactory()

        delivery_notes = []
        for week, rabatt in ((15, 0), (16, 10)):
            order = OrderFactory(
                reseller=reseller, year=2026, delivery_week=week, day_number=2
            )
            OrderContentFactory(
                order=order,
                share_article=article,
                amount=Decimal("2"),
                price_per_unit=Decimal("3.00"),
                tax_rate=Decimal("7"),
                rabatt=rabatt,
                unit="KG",
                size="M",
            )
            dn = DeliveryNoteService.create_from_order(order=order)
            DeliveryNoteService.finalize_delivery_note(dn)
            delivery_notes.append(dn)

        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=delivery_notes
        )
        invoice.refresh_from_db()

        lines = list(invoice.items.filter(share_article=article))
        assert len(lines) == 2
        assert {line.rabatt for line in lines} == {0, 10}

    def test_crate_only_invoice_can_be_finalized(self, tenant):
        """A crate-only (deposit/Pfand) invoice has no article items but
        must still finalize — the empty-guard checks BOTH collections,
        not just ``items``.
        """
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        CrateOrderContent.objects.create(
            order=order,
            crate_type=CrateFactory(),
            amount=3,
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("19"),
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)

        assert invoice.items.exists() is False
        assert invoice.crate_items.exists() is True

        InvoiceService.finalize_invoice(invoice)
        invoice.refresh_from_db()
        assert invoice.is_finalized is True
        assert invoice.number is not None

    def test_crate_only_dn_is_traceable_and_not_double_billable(self, tenant):
        """DOC-2: a crate-only delivery note (no article lines) must be uniquely
        traceable to its invoice and billable at most once. Before the crate
        provenance M2M, every guard keyed solely on the (empty) article M2M — so
        a crate-only DN was invisible to lookups AND silently double-billable."""
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=17, day_number=2
        )
        CrateOrderContent.objects.create(
            order=order,
            crate_type=CrateFactory(),
            amount=3,
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("19"),
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)

        assert invoice.items.exists() is False
        assert invoice.crate_items.exists() is True

        # The crate provenance M2M links the invoice's crate line back to the DN.
        crate_item = invoice.crate_items.get()
        assert list(
            crate_item.crate_delivery_note_contents.values_list(
                "delivery_note_id", flat=True
            )
        ) == [dn.id]

        # (b) The DN now resolves to its invoice (was None → invisible invoice).
        assert InvoiceService.get_invoice_for_delivery_note(dn) == invoice

        # The serializer's "corresponding delivery notes" (UI + PDF) now lists
        # the crate-only DN too (was blank — it only walked article lines).
        from apps.commissioning.serializers.resellers_serializer import (
            InvoiceResellerSerializer,
        )

        assert (
            InvoiceResellerSerializer(invoice).data["corresponding_delivery_notes"]
            == dn.full_number
        )

        # (a) A second invoice for the same crate-only DN is refused (was a
        # silent second full invoice → double-billing).
        with pytest.raises(JasminError) as exc_info:
            InvoiceService.create_from_delivery_note(delivery_note=dn)
        assert exc_info.value.code == "invoice.already_exists"

    def test_crate_only_dn_summary_path_is_traceable_and_not_double_billable(
        self, tenant
    ):
        """DOC-2 (summary path): a crate-only DN summarized into an invoice is
        traceable and can't then be re-billed via the summary OR per-DN path."""
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=18, day_number=2
        )
        CrateOrderContent.objects.create(
            order=order,
            crate_type=CrateFactory(),
            amount=2,
            price_per_unit=Decimal("2.00"),
            tax_rate=Decimal("19"),
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_summary_invoice_from_delivery_notes([dn])

        assert invoice.items.exists() is False
        assert invoice.crate_items.exists() is True
        assert InvoiceService.get_invoice_for_delivery_note(dn) == invoice

        with pytest.raises(JasminError) as exc_info:
            InvoiceService.create_summary_invoice_from_delivery_notes([dn])
        assert exc_info.value.code == "invoice.already_exists"
        with pytest.raises(JasminError) as exc_info2:
            InvoiceService.create_from_delivery_note(delivery_note=dn)
        assert exc_info2.value.code == "invoice.already_exists"

    def test_summary_invoice_finalizes_and_locks(self, tenant):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()

        delivery_notes = []
        for week in (15, 16):
            order = _make_order_with_lines(
                reseller,
                week=week,
                article_lines=[(Decimal("2"), Decimal("3.00"), Decimal("7"))],
                crate_lines=[(1, Decimal("1.50"), Decimal("19"))],
            )
            dn = DeliveryNoteService.create_from_order(order=order)
            DeliveryNoteService.finalize_delivery_note(dn)
            delivery_notes.append(dn)

        invoice = InvoiceService.create_summary_invoice_from_delivery_notes(
            delivery_notes=delivery_notes
        )
        InvoiceService.finalize_invoice(invoice)
        invoice.refresh_from_db()

        assert invoice.is_finalized is True
        assert invoice.number is not None
        # One-way contract on the summary invoice.
        with pytest.raises(JasminError, match="immutable"):
            invoice.unfinalize()

    def test_summary_invoice_refuses_unfinalized_dn(self, tenant):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = _make_order_with_lines(
            reseller,
            week=15,
            article_lines=[(Decimal("1"), Decimal("1.00"), Decimal("7"))],
            crate_lines=[(1, Decimal("1.00"), Decimal("19"))],
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        # NOT finalized.
        with pytest.raises(JasminError, match="not finalized"):
            InvoiceService.create_summary_invoice_from_delivery_notes(
                delivery_notes=[dn]
            )

    def test_summary_invoice_refuses_mixed_resellers(self, tenant):
        _ensure_settings(connection.tenant)
        r1, r2 = ResellerFactory(), ResellerFactory()

        dns = []
        for r in (r1, r2):
            order = _make_order_with_lines(
                r,
                week=15,
                article_lines=[(Decimal("1"), Decimal("1.00"), Decimal("7"))],
                crate_lines=[],
            )
            dn = DeliveryNoteService.create_from_order(order=order)
            DeliveryNoteService.finalize_delivery_note(dn)
            dns.append(dn)

        with pytest.raises(JasminError, match="same reseller"):
            InvoiceService.create_summary_invoice_from_delivery_notes(
                delivery_notes=dns
            )


# ===================================================================
# 3. Storno reverses sums of a finalized invoice
# ===================================================================
@pytest.mark.django_db
class TestStornoMirrorsInvoice:
    """A storno is itself a finalized invoice with negated amounts.
    The sum (invoice + storno) must net to zero — that's the legal
    cancellation contract."""

    def test_storno_amounts_negate_original_invoice(self, tenant):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = _make_order_with_lines(
            reseller,
            week=15,
            article_lines=[
                (Decimal("2"), Decimal("3.50"), Decimal("7")),
                (Decimal("1"), Decimal("9.99"), Decimal("19")),
            ],
            crate_lines=[(2, Decimal("1.50"), Decimal("19"))],
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)
        invoice.refresh_from_db()

        storno = InvoiceService.create_storno(invoice, reason="customer return")
        storno.refresh_from_db()
        invoice.refresh_from_db()

        # Storno is auto-finalized.
        assert storno.is_finalized is True
        assert storno.document_type == "storno"
        # Original was marked as cancelled.
        assert invoice.cancelled_by_invoice_id == storno.id

        # Item-by-item negation, matched by share_article (default
        # queryset ordering is not stable across copies).
        assert storno.items.count() == invoice.items.count()
        assert storno.crate_items.count() == invoice.crate_items.count()
        inv_by_article = {it.share_article_id: it.amount for it in invoice.items.all()}
        st_by_article = {it.share_article_id: it.amount for it in storno.items.all()}
        assert inv_by_article.keys() == st_by_article.keys()
        for article_id, inv_amount in inv_by_article.items():
            assert st_by_article[article_id] == -inv_amount

        inv_by_crate = {ci.crate_type_id: ci.amount for ci in invoice.crate_items.all()}
        st_by_crate = {ci.crate_type_id: ci.amount for ci in storno.crate_items.all()}
        assert inv_by_crate.keys() == st_by_crate.keys()
        for crate_id, inv_amount in inv_by_crate.items():
            assert st_by_crate[crate_id] == -inv_amount

        # Sums net to zero (within rounding).
        assert _quant(invoice.sum_netto + storno.sum_netto) == Decimal("0.00")
        assert _quant(invoice.sum_brutto + storno.sum_brutto) == Decimal("0.00")

    def test_double_storno_is_refused(self, tenant):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = _make_order_with_lines(
            reseller,
            week=15,
            article_lines=[(Decimal("1"), Decimal("1.00"), Decimal("7"))],
            crate_lines=[(1, Decimal("1.00"), Decimal("19"))],
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)

        InvoiceService.create_storno(invoice, reason="first storno")
        invoice.refresh_from_db()
        # can_be_cancelled returns False once cancelled_by_invoice is set.
        assert invoice.can_be_cancelled() is False

        with pytest.raises(JasminError, match="cannot be cancelled"):
            InvoiceService.create_storno(invoice, reason="second storno")

    def test_storno_cannot_be_unfinalized_or_deleted(self, tenant):
        _ensure_settings(connection.tenant)
        reseller = ResellerFactory()
        order = _make_order_with_lines(
            reseller,
            week=15,
            article_lines=[(Decimal("1"), Decimal("1.00"), Decimal("7"))],
            crate_lines=[],
        )
        dn = DeliveryNoteService.create_from_order(order=order)
        DeliveryNoteService.finalize_delivery_note(dn)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)
        InvoiceService.finalize_invoice(invoice)
        storno = InvoiceService.create_storno(invoice, reason="r")

        with pytest.raises(JasminError, match="immutable"):
            storno.unfinalize()
        with pytest.raises(JasminError, match="immutable"):
            storno.delete()


# ===================================================================
# 4. Stress: many orders + many resellers, all contents accounted for
# ===================================================================
@pytest.mark.django_db
class TestBatchIntegrity:
    """Run a larger fan-out and assert that every line item and every
    crate row that ever existed on an order ends up on its invoice
    (nothing dropped along the way)."""

    def test_no_content_is_lost_across_chain(self, tenant):
        _ensure_settings(connection.tenant)

        N_RESELLERS = 4
        N_ORDERS_PER_RESELLER = 3
        resellers = [ResellerFactory() for _ in range(N_RESELLERS)]

        seen_articles_total = 0
        seen_crates_total = 0
        invoices_created = 0

        for reseller_idx, reseller in enumerate(resellers):
            for order_idx in range(N_ORDERS_PER_RESELLER):
                week = 15 + order_idx
                article_lines = [
                    (
                        Decimal(str(1 + order_idx)),
                        Decimal("2.50"),
                        Decimal("7"),
                    ),
                    (
                        Decimal(str(2 + reseller_idx)),
                        Decimal("4.00"),
                        Decimal("19"),
                    ),
                ]
                crate_lines = [
                    (1 + order_idx, Decimal("1.50"), Decimal("19")),
                ]
                order = _make_order_with_lines(
                    reseller,
                    week=week,
                    article_lines=article_lines,
                    crate_lines=crate_lines,
                )

                dn = DeliveryNoteService.create_from_order(order=order)
                invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)

                # Per-document content count must equal what we put in.
                assert invoice.items.count() == len(article_lines)
                assert invoice.crate_items.count() == len(crate_lines)

                seen_articles_total += len(article_lines)
                seen_crates_total += len(crate_lines)
                invoices_created += 1

        assert invoices_created == N_RESELLERS * N_ORDERS_PER_RESELLER

        # Global counts.
        assert (
            InvoiceResellerContent.objects.count() == seen_articles_total
        ), "Article-line invoice rows lost somewhere in the chain"
        assert (
            CrateContentInvoiceReseller.objects.count() == seen_crates_total
        ), "Crate invoice rows lost somewhere in the chain"

        # Every invoice has a non-zero sum and at least one of each row.
        for invoice in InvoiceReseller.objects.all():
            assert invoice.sum_netto > Decimal("0")
            assert invoice.items.exists()
            assert invoice.crate_items.exists()

        # Cascade-up locks every parent.
        assert all(o.is_finalized for o in Order.objects.all())
        assert all(d.is_finalized for d in DeliveryNoteReseller.objects.all())


# ---------------------------------------------------------------------------
# DOC-1 / DOC-2 regression: amount_per_pu must NOT diverge the legal chain
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAmountPerPuChainConsistency:
    def test_offer_amount_per_pu_does_not_scale_line_net(self, tenant):
        """An offer with ``amount_per_pu != 1`` must NOT scale the line net.
        ``OrderContent.amount`` is in physical units and ``price_per_unit`` is
        €/unit, so the order, delivery-note and invoice line totals all equal
        ``amount × price_per_unit`` (NOT × amount_per_pu). Pre-fix the order net
        was multiplied by amount_per_pu and diverged from the legally-issued
        invoice (DOC-1)."""
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        offer = OfferFactory(
            share_article=ShareArticleFactory(),
            amount_per_pu=Decimal("5.000"),
            unit="KG",
        )
        OrderContentFactory(
            order=order,
            offer=offer,
            share_article=None,
            amount=Decimal("3.000"),
            price_per_unit=Decimal("4.00"),
            tax_rate=Decimal("7.00"),
            unit="KG",
            size="M",
        )

        dn = DeliveryNoteService.create_from_order(order=order)
        invoice = InvoiceService.create_from_delivery_note(delivery_note=dn)

        expected_netto = Decimal("12.00")  # 3 units × 4 €/unit, NOT × 5
        assert _quant(order.sum_netto) == expected_netto
        assert _quant(dn.sum_netto) == expected_netto
        assert _quant(invoice.sum_netto) == expected_netto
