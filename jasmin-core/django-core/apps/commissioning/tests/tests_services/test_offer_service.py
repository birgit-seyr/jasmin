"""Tests for OfferService."""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

import pytest

from apps.commissioning.models import ForecastOfferGroup, Offer
from apps.commissioning.services.offer_service import OfferService
from apps.commissioning.tests.factories import (
    ForecastFactory,
    OfferFactory,
    OfferGroupFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
)


# ---------------------------------------------------------------------------
# annotate_offers_with_ordered_amounts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAnnotateOffersWithOrderedAmounts:
    def test_zero_when_no_orders(self, tenant):
        offer = OfferFactory(amount=Decimal("50"))
        qs = OfferService.annotate_offers_with_ordered_amounts(
            Offer.objects.filter(pk=offer.pk)
        )
        assert qs.first().amount_ordered == Decimal("0")

    def test_sums_matching_order_contents(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("50"))
        reseller = ResellerFactory()
        order_a = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        order_b = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=3
        )
        OrderContentFactory(
            order=order_a, offer=offer, share_article=None, amount=Decimal("10")
        )
        OrderContentFactory(
            order=order_b, offer=offer, share_article=None, amount=Decimal("5")
        )

        qs = OfferService.annotate_offers_with_ordered_amounts(
            Offer.objects.filter(pk=offer.pk)
        )
        assert qs.first().amount_ordered == Decimal("15")

    def test_filters_by_reseller(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("50"))
        r1 = ResellerFactory()
        r2 = ResellerFactory()
        o1 = OrderFactory(reseller=r1, year=2026, delivery_week=15, day_number=2)
        o2 = OrderFactory(reseller=r2, year=2026, delivery_week=15, day_number=2)
        OrderContentFactory(
            order=o1, offer=offer, share_article=None, amount=Decimal("10")
        )
        OrderContentFactory(
            order=o2, offer=offer, share_article=None, amount=Decimal("7")
        )

        qs = OfferService.annotate_offers_with_ordered_amounts(
            Offer.objects.filter(pk=offer.pk),
            reseller=r1,
        )
        assert qs.first().amount_ordered == Decimal("10")

    def test_filters_by_day(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("50"))
        reseller = ResellerFactory()
        o_day2 = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=2
        )
        o_day3 = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=3
        )
        OrderContentFactory(
            order=o_day2, offer=offer, share_article=None, amount=Decimal("8")
        )
        OrderContentFactory(
            order=o_day3, offer=offer, share_article=None, amount=Decimal("3")
        )

        qs = OfferService.annotate_offers_with_ordered_amounts(
            Offer.objects.filter(pk=offer.pk),
            delivery_day=2,
        )
        assert qs.first().amount_ordered == Decimal("8")


# ---------------------------------------------------------------------------
# copy_offers_to_next_week
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCopyOffersToNextWeek:
    def test_copies_to_next_week(self, tenant):
        offer = OfferFactory(
            year=2026, delivery_week=10, amount=Decimal("20"), is_finalized=True
        )

        result = OfferService.copy_offers_to_next_week([offer.pk])

        assert result["created_count"] == 1
        assert result["skipped_count"] == 0
        new_offer = Offer.objects.get(pk=result["created_ids"][0])
        assert new_offer.year == 2026
        assert new_offer.delivery_week == 11
        assert new_offer.is_finalized is False

    def test_skips_duplicate(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(
            year=2026,
            delivery_week=10,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("20"),
        )
        # Already exists in next week
        OfferFactory(
            year=2026,
            delivery_week=11,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("5"),
        )

        result = OfferService.copy_offers_to_next_week([offer.pk])

        assert result["created_count"] == 0
        assert result["skipped_count"] == 1

    def test_year_boundary(self, tenant):
        offer = OfferFactory(year=2026, delivery_week=52, amount=Decimal("10"))

        result = OfferService.copy_offers_to_next_week([offer.pk])

        assert result["created_count"] == 1
        new_offer = Offer.objects.get(pk=result["created_ids"][0])
        assert new_offer.year == 2026
        assert new_offer.delivery_week == 53

    def test_dedups_in_batch_duplicates(self, tenant):
        """COR-26: two source offers collapsing to the SAME target slot
        (same article/unit/size, same target week) must produce ONE copy,
        not two — the in-memory batch is deduped like the persisted-row
        check. Before the fix both passed the exists() check (nothing
        persisted yet) and both got created."""
        article = ShareArticleFactory()
        a = OfferFactory(
            year=2026,
            delivery_week=10,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("20"),
        )
        b = OfferFactory(
            year=2026,
            delivery_week=10,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("30"),
        )

        result = OfferService.copy_offers_to_next_week([a.pk, b.pk])

        assert result["created_count"] == 1
        assert result["skipped_count"] == 1
        assert (
            Offer.objects.filter(
                year=2026,
                delivery_week=11,
                share_article=article,
                unit="KG",
                size="M",
            ).count()
            == 1
        )


# ---------------------------------------------------------------------------
# copy_offers_to_offer_group
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCopyOffersToOfferGroup:
    def test_copies_to_group(self, tenant):
        group = OfferGroupFactory()
        offer = OfferFactory(year=2026, delivery_week=15, amount=Decimal("10"))

        result = OfferService.copy_offers_to_offer_group(
            [offer.pk],
            year=2026,
            delivery_week=15,
            offer_group=group.pk,
        )

        assert result["created_count"] == 1
        new_offer = Offer.objects.get(pk=result["created_ids"][0])
        assert new_offer.offer_group_id == group.pk
        assert new_offer.is_finalized is False

    def test_skips_existing_in_group(self, tenant):
        article = ShareArticleFactory()
        group = OfferGroupFactory()
        offer = OfferFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("10"),
        )
        OfferFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            amount=Decimal("5"),
            offer_group=group,
        )

        result = OfferService.copy_offers_to_offer_group(
            [offer.pk],
            year=2026,
            delivery_week=15,
            offer_group=group.pk,
        )

        assert result["created_count"] == 0
        assert result["skipped_count"] == 1


# ---------------------------------------------------------------------------
# create_offers
# ---------------------------------------------------------------------------
def _mock_stock_empty(year, delivery_week, day_number, storage=None):
    """Return empty stock map."""
    return {}


def _make_stock_mock(stock_entries: dict[tuple, Decimal]):
    """
    Build a mock for StockService.get_theoretical_current_stock.

    stock_entries: dict keyed by (share_article_id, unit, size) with Decimal values.
    All entries are marked for_resellers=True.
    """

    def _mock(year, delivery_week, day_number, storage=None):
        result = {}
        for (sa_id, unit, size), amount in stock_entries.items():
            key = (sa_id, unit, size, None)
            result[key] = {
                "theoretical_current_stock": amount,
                "for_resellers": True,
            }
        return result

    return _mock


@pytest.mark.django_db
class TestCreateOffers:
    """Tests for OfferService.create_offers (automatic offer creation from forecasts)."""

    @pytest.fixture(autouse=True)
    def _clean_offer_group_slate(self, tenant):
        # These tests assert exact offer / offer-group counts; the per-tenant
        # default offer group seeded by migration 0014 would add one extra
        # group and offset every count. Start from a clean slate.
        from apps.commissioning.models import OfferGroup

        OfferGroup.objects.all().delete()

    @staticmethod
    def _make_article(**kwargs):
        """Create a ShareArticle with sensible reseller defaults."""
        defaults = {
            "default_commissioning_unit": "KG",
            "default_kg_per_pu_reseller": Decimal("5.000"),
        }
        defaults.update(kwargs)
        return ShareArticleFactory(**defaults)

    @staticmethod
    def _make_pricing(article, **kwargs):
        """Create a ShareArticleNetPrice with all order pricing fields set."""
        defaults = {
            "share_article": article,
            "net_price_for_orders_kg_1": Decimal("3.00"),
            "net_price_for_orders_kg_2": Decimal("2.50"),
            "net_price_for_orders_kg_3": Decimal("2.00"),
        }
        defaults.update(kwargs)
        return ShareArticleNetPriceFactory(**defaults)

    # --- basic happy path ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_for_all_resellers_creates_offer_in_every_group(self, _mock, tenant):
        """Forecast with for_all_resellers=True → offer created in EVERY offer group."""
        article = self._make_article()
        self._make_pricing(article)

        g1 = OfferGroupFactory()
        g2 = OfferGroupFactory()

        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=100,
            unit="KG",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)

        assert result["created_count"] == 2
        offers = list(Offer.objects.all())
        assert len(offers) == 2
        assert {o.offer_group_id for o in offers} == {g1.pk, g2.pk}
        for o in offers:
            assert o.share_article == article
            assert o.unit == "KG"
            assert o.size == "M"
            assert o.amount == Decimal(100) / Decimal("5.000")
            assert o.price_1 == Decimal("3.00")
            assert o.price_2 == Decimal("2.50")
            assert o.price_3 == Decimal("2.00")
            assert o.is_finalized is False

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_missing_conversion_factor_falls_back_to_forecast_unit(self, _mock, tenant):
        """When the per-size unit-conversion factor is missing, the offer is
        created in the ORIGINAL forecast unit rather than being skipped."""
        # default_commissioning_unit=KG but NO kg_per_piece_M → PCS→KG conversion
        # is impossible. A PU factor for PCS lets the fallback offer still be made.
        article = self._make_article(
            default_commissioning_unit="KG",
            default_pieces_per_pu_reseller=Decimal("10.000"),
        )
        self._make_pricing(article)
        OfferGroupFactory()
        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=100,
            unit="PCS",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)

        assert result["created_count"] == 1
        offer = Offer.objects.get()
        assert offer.unit == "PCS"  # original forecast unit — NOT skipped
        assert offer.amount == Decimal(100) / Decimal("10.000")

    # --- query-count lock (PERF-8) ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_query_count_scale_invariant_in_offer_group_count(self, _mock, tenant):
        """Forecast preloading and the existing-offer idempotency check are
        batched once for the whole run, so adding offer groups must NOT add
        proportional queries. An amount=0 ``for_all_resellers`` forecast makes
        every group see the item but create nothing (total_available <= 0),
        isolating the preload / exists N+1 from the necessary per-offer
        INSERT."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        article = self._make_article()
        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=Decimal("0"),
            unit="KG",
            size="M",
        )

        for _ in range(2):
            OfferGroupFactory()
        with CaptureQueriesContext(connection) as small_ctx:
            small = OfferService.create_offers(2026, 15)

        for _ in range(4):
            OfferGroupFactory()
        with CaptureQueriesContext(connection) as large_ctx:
            large = OfferService.create_offers(2026, 15)

        # Non-vacuity: every group was processed and skipped the amount=0 item
        # (nothing created), so the per-group loop genuinely ran.
        assert small["created_count"] == 0
        assert large["created_count"] == 0
        assert len(large["skipped_offers"]) >= 6

        delta = len(large_ctx.captured_queries) - len(small_ctx.captured_queries)
        assert delta <= 3, (
            f"create_offers N+1 suspected: 2 groups -> "
            f"{len(small_ctx.captured_queries)} queries, 6 groups -> "
            f"{len(large_ctx.captured_queries)} queries (delta {delta})."
        )

    # --- ForecastOfferGroup linking ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_linked_forecast_creates_offer_only_in_linked_group(self, _mock, tenant):
        """Forecast linked via ForecastOfferGroup (for_all_resellers=False) → offer only in that group."""
        article = self._make_article()
        self._make_pricing(article)

        g1 = OfferGroupFactory()
        _g2 = OfferGroupFactory()

        forecast = ForecastFactory(
            share_article=article,
            for_all_resellers=False,
            amount=50,
            unit="KG",
            size="M",
        )
        ForecastOfferGroup.objects.create(forecast=forecast, offer_group=g1)

        result = OfferService.create_offers(2026, 15)

        assert result["created_count"] == 1
        offer = Offer.objects.get()
        assert offer.offer_group == g1
        assert offer.share_article == article

    # --- forecast NOT linked and NOT for_all_resellers → no offers ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_no_reseller_flag_and_no_link_creates_nothing(self, _mock, tenant):
        """Forecast with for_all_resellers=False and no ForecastOfferGroup → no offer."""
        article = self._make_article()
        self._make_pricing(article)
        OfferGroupFactory()

        ForecastFactory(
            share_article=article,
            for_all_resellers=False,
            amount=50,
            unit="KG",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)

        assert result["created_count"] == 0
        assert Offer.objects.count() == 0

    # --- stock adds to available amount ---

    def test_stock_adds_to_forecast(self, tenant):
        """Stock for_resellers=True is added to forecast amount."""
        article = self._make_article()
        self._make_pricing(article)
        OfferGroupFactory()

        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=20,
            unit="KG",
            size="M",
        )

        stock_mock = _make_stock_mock({(article.id, "KG", "M"): Decimal("30")})
        with mock.patch(
            "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
            side_effect=stock_mock,
        ):
            result = OfferService.create_offers(2026, 15)

        assert result["created_count"] == 1
        offer = Offer.objects.get()
        # total_available = 20 (forecast) + 30 (stock) = 50
        # amount_pu = 50 / 5 = 10
        assert offer.amount == Decimal("50") / Decimal("5.000")

    # --- total_available <= 0 → skipped ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_skips_when_amount_pu_less_than_one(self, _mock, tenant):
        """Offer is skipped when amount in PU is less than 1."""
        article = self._make_article(default_kg_per_pu_reseller=Decimal("100.000"))
        self._make_pricing(article)
        OfferGroupFactory()

        # amount=1 and default_kg_per_pu_reseller=100 → 1/100 = 0.01 PU < 1
        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=1,
            unit="KG",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)
        assert result["created_count"] == 0
        assert result["skipped_count"] >= 1

    # --- duplicate is skipped ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_skips_duplicate_offer(self, _mock, tenant):
        """Already-existing offer for same article/unit/size/group/week → skipped."""
        article = self._make_article()
        self._make_pricing(article)
        group = OfferGroupFactory()

        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=100,
            unit="KG",
            size="M",
        )

        # Pre-create the offer
        OfferFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            offer_group=group,
        )

        result = OfferService.create_offers(2026, 15)
        assert result["created_count"] == 0
        assert result["skipped_count"] >= 1
        # Still only the original offer
        assert Offer.objects.count() == 1

    # --- no offer groups → early return ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_no_offer_groups_returns_zero(self, _mock, tenant):
        """No OfferGroups → returns immediately with created_count=0."""
        article = self._make_article()
        self._make_pricing(article)

        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=100,
            unit="KG",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)
        assert result["created_count"] == 0

    # --- pricing is applied correctly ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_prices_from_share_article_net_price(self, _mock, tenant):
        """Offer prices come from ShareArticleNetPrice for the correct unit."""
        article = self._make_article(
            default_commissioning_unit="PCS",
            default_pieces_per_pu_reseller=Decimal("10.000"),
        )
        ShareArticleNetPriceFactory(
            share_article=article,
            net_price_for_orders_pieces_1=Decimal("1.50"),
            net_price_for_orders_pieces_2=Decimal("1.20"),
            net_price_for_orders_pieces_3=Decimal("1.00"),
        )

        OfferGroupFactory()
        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=100,
            unit="PCS",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)
        assert result["created_count"] == 1
        offer = Offer.objects.get()
        assert offer.unit == "PCS"
        assert offer.price_1 == Decimal("1.50")
        assert offer.price_2 == Decimal("1.20")
        assert offer.price_3 == Decimal("1.00")
        assert offer.amount_per_pu == Decimal("10.000")

    # --- amount_per_pu and PU conversion ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_pu_conversion_kg(self, _mock, tenant):
        """Amount is converted to PU using default_kg_per_pu_reseller."""
        article = self._make_article(default_kg_per_pu_reseller=Decimal("2.500"))
        self._make_pricing(article)
        OfferGroupFactory()

        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=25,
            unit="KG",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)
        assert result["created_count"] == 1
        offer = Offer.objects.get()
        # 25 KG / 2.5 KG per PU = 10 PU
        assert offer.amount == Decimal("25") / Decimal("2.500")
        assert offer.amount_per_pu == Decimal("2.500")

    # --- no PU conversion attribute → skipped ---

    @mock.patch(
        "apps.commissioning.services.stock_service.StockService.get_theoretical_current_stock",
        side_effect=_mock_stock_empty,
    )
    def test_skips_when_no_pu_conversion(self, _mock, tenant):
        """If PU conversion attr is not set (0 or None), the offer is skipped."""
        article = self._make_article(
            default_kg_per_pu_reseller=None,
        )
        self._make_pricing(article)
        OfferGroupFactory()

        ForecastFactory(
            share_article=article,
            for_all_resellers=True,
            amount=100,
            unit="KG",
            size="M",
        )

        result = OfferService.create_offers(2026, 15)
        assert result["created_count"] == 0
        assert result["skipped_count"] >= 1


# ---------------------------------------------------------------------------
# bulk_send_offers_via_email — render-context contract
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkSendOffersViaEmailContext:
    """The offer template references ``tenant_name``, ``reseller.name``,
    ``offer.period`` and ``offer_url``. Lock the context the service hands to
    ``send_email`` so it stops shipping a bare Reseller instance and a dead
    ``offer_url`` — and so the captured tenant context (the worker FakeTenant
    can't supply it) is threaded through. The order cutoff is per delivery
    day and enforced on the order sheet, so the email carries no single
    deadline."""

    def test_context_has_tenant_name_reseller_dict_period_and_url(self, tenant):
        offer_group = OfferGroupFactory()
        reseller = ResellerFactory(offer_group=offer_group)
        OfferFactory(year=2026, delivery_week=15, offer_group=offer_group)

        email_ctx = {
            "tenant_name": "Test Coop",
            "tenant_language": "de",
            "bank_details": "DE12 / GENODEF1XXX",
            "frontend_base_url": "https://test.example.org",
        }

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            autospec=True,
            return_value=True,
        ) as send_email:
            result = OfferService.bulk_send_offers_via_email(
                reseller_ids=[str(reseller.id)],
                year=2026,
                delivery_week=15,
                offer_group=offer_group,
                email_ctx=email_ctx,
            )

        assert result["successful"] == 1
        assert send_email.call_count == 1
        kwargs = send_email.call_args.kwargs
        assert kwargs["slug"] == "commissioning.offer"
        assert kwargs["language"] == "de"
        ctx = kwargs["context"]
        assert ctx["tenant_name"] == "Test Coop"
        assert ctx["reseller"] == {"name": reseller.contact.name}
        assert ctx["offer"]["period"] == "Week 15, 2026"
        # No single deadline — the cutoff is per delivery day and enforced
        # on the order sheet.
        assert "deadline" not in ctx["offer"]
        # A real link to the reseller's order sheet, not "".
        assert ctx["offer_url"] == (
            f"https://test.example.org/commissioning/customer-orders/{reseller.id}"
        )


# ---------------------------------------------------------------------------
# bulk_send_offers_via_email — progress denominator reconciliation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkSendOffersProgress:
    """A requested reseller id that isn't in the offer group must still be
    counted (as a failed result) so the progress bar reaches 100% and the
    office sees why it was skipped — not a job that silently looks stuck."""

    def test_id_outside_offer_group_is_a_failed_result_and_total_reconciles(
        self, tenant
    ):
        offer_group = OfferGroupFactory()
        reseller = ResellerFactory(offer_group=offer_group)
        OfferFactory(year=2026, delivery_week=15, offer_group=offer_group)
        # A reseller that exists but belongs to a DIFFERENT group → dropped by
        # the offer_group filter.
        other = ResellerFactory(offer_group=OfferGroupFactory())

        progress: list[dict] = []

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            autospec=True,
            return_value=True,
        ):
            result = OfferService.bulk_send_offers_via_email(
                reseller_ids=[str(reseller.id), str(other.id)],
                year=2026,
                delivery_week=15,
                offer_group=offer_group,
                progress_cb=progress.append,
            )

        # Denominator counts BOTH requested ids; one sent, one skipped.
        assert result["total_processed"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 1
        assert result["successful"] + result["failed"] == result["total_processed"]

        skipped = [r for r in result["results"] if r["reseller_id"] == str(other.id)]
        assert len(skipped) == 1
        assert skipped[0]["success"] is False
        assert skipped[0]["error"] == "Reseller not in this offer group"

        # The final emitted progress reaches 100% (processed == total).
        assert progress, "progress_cb should have been called"
        last = progress[-1]
        assert last["total"] == 2
        assert last["processed"] == 2
        assert last["processed"] == last["total"]
