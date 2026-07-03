"""Lock-down tests for ``OrderContent.resolve_*`` methods.

These two resolvers are the **single source of truth** for how an
OrderContent's effective ``share_article`` and ``amount_per_pu`` get
derived. Many call sites depend on the fallback chain agreeing exactly
— line-pricing (``line_netto``), the commissioning list, the
OrderContent API serializer, and the Forecast-lookup in
``create_all_theoretical_objects`` all route through these.

``unit`` and ``size`` are NOT resolved — they're direct OrderContent
columns. When an OC is created from an offer, the service copies
``offer.unit`` / ``offer.size`` onto the row (see
``OrderContentService.create_order_with_content_and_crates``), so the
on-row value is always populated regardless of whether the OC is
offer-bound or ad-hoc. If you're tempted to add a resolver for them,
don't.

**Model invariant** (enforced in ``OrderableItem.clean``): an
OrderContent row has **exactly one** of ``offer`` or ``share_article``
populated. The resolver's precedence between the two is therefore
academic — only one branch is ever live for any given row. The
defensive "both set" / "neither set" branches in the resolver exist
for paranoia (e.g. raw-SQL writes that bypass clean) and are not
exercised here.

If any of these tests start failing, the regression is almost
certainly that someone reintroduced an inline
``offer.X if offer else content.X`` pattern somewhere and the
resolver's precedence has diverged from it. Fix the caller (route
it through ``resolve_*``), don't loosen the test — the whole point of
the resolver is that there is exactly one place to change the
precedence.

The fallback chain (canonical, as of the audit on 2026-06-06):

  resolve_share_article : content.share_article → offer.share_article → None
  resolve_amount_per_pu : offer.amount_per_pu   → article.get_amount_per_pu_for_reseller(content.unit) → Decimal("1")
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.commissioning.tests.factories import (
    OfferFactory,
    OrderContentFactory,
    OrderFactory,
    ShareArticleFactory,
)


# ---------------------------------------------------------------------------
# Model invariant — locks the precondition the resolvers assume.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExactlyOneItemTypeInvariant:
    """``OrderableItem.clean`` requires exactly one of (offer, share_article).

    The resolvers' precedence is documented for clarity but only one
    branch is ever taken on any given persisted row. If this invariant
    is ever relaxed, revisit the resolver precedence — see the module
    docstring.
    """

    def test_cannot_save_with_both_set(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article)
        with pytest.raises(ValidationError, match="exactly one"):
            OrderContentFactory(offer=offer, share_article=article)

    def test_cannot_save_with_neither_set(self, tenant):
        with pytest.raises(ValidationError, match="exactly one"):
            OrderContentFactory(offer=None, share_article=None)


# ---------------------------------------------------------------------------
# OrderContent.resolve_share_article
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestResolveShareArticle:
    def test_offer_bound_oc_returns_offer_share_article(self, tenant):
        """Offer-bound OC: ``share_article`` is null on the row; the
        article comes from ``offer.share_article``."""
        offer_article = ShareArticleFactory(name="OnOffer")
        offer = OfferFactory(share_article=offer_article)
        oc = OrderContentFactory(offer=offer, share_article=None)
        assert oc.resolve_share_article() == offer_article

    def test_ad_hoc_oc_returns_content_share_article(self, tenant):
        """Ad-hoc OC (no offer): ``share_article`` is set on the row."""
        article = ShareArticleFactory()
        oc = OrderContentFactory(offer=None, share_article=article)
        assert oc.resolve_share_article() == article


# ---------------------------------------------------------------------------
# OrderContent.resolve_amount_per_pu
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestResolveAmountPerPu:
    def test_offer_value_used_when_present(self, tenant):
        offer = OfferFactory(amount_per_pu=Decimal("7.500"))
        oc = OrderContentFactory(offer=offer, share_article=None)
        assert oc.resolve_amount_per_pu() == Decimal("7.500")

    def test_falls_back_to_article_kg_for_kg_unit(self, tenant):
        """No offer, unit=KG: pulls from ``default_kg_per_pu_reseller``."""
        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=Decimal("10.000"),
        )
        oc = OrderContentFactory(offer=None, share_article=article, unit="KG")
        assert oc.resolve_amount_per_pu() == Decimal("10.000")

    def test_falls_back_to_article_pcs_for_pcs_unit(self, tenant):
        article = ShareArticleFactory(
            default_movement_unit="PCS",
            default_pieces_per_pu_reseller=20,
        )
        oc = OrderContentFactory(offer=None, share_article=article, unit="PCS")
        assert oc.resolve_amount_per_pu() == Decimal("20")

    def test_falls_back_to_one_when_article_has_no_value_for_unit(self, tenant):
        """Article exists but has nothing configured for the line's unit
        — last-resort default is 1 (preserves pre-existing behaviour for
        unknown units)."""
        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=None,
        )
        oc = OrderContentFactory(offer=None, share_article=article, unit="KG")
        assert oc.resolve_amount_per_pu() == Decimal("1")

    def test_offer_zero_amount_per_pu_falls_through_to_offer_article(self, tenant):
        """``offer.amount_per_pu == 0`` is falsy — must NOT win the
        chain, since 0 would zero out every line_netto on that order.

        The fallback uses the OFFER's share_article (the OC row's
        share_article is null by invariant when offer is set).
        """
        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=Decimal("4.000"),
        )
        offer = OfferFactory(
            share_article=article, amount_per_pu=Decimal("0.000"), unit="KG"
        )
        oc = OrderContentFactory(offer=offer, share_article=None, unit="KG")
        assert oc.resolve_amount_per_pu() == Decimal("4.000")


# ---------------------------------------------------------------------------
# OrderContent.line_netto is UNIT-based: ``amount × price_per_unit``
#
# ``amount`` is in physical units (kg/pcs/bunch) and ``price_per_unit`` is
# €/unit, so ``amount_per_pu`` must NOT enter line pricing — it's only for the
# PU conversion used by ``ordered_amount`` / offer-stock debiting. This keeps
# the order line net equal to the delivery-note and invoice line nets (which
# inherit the same base ``LinePricingMixin`` formula) and to the frontend
# ``computeLineNetto`` mirror. Previously OrderContent multiplied by
# ``amount_per_pu``, over-charging by that factor and diverging from the
# legally-issued invoice (DOC-1 / DOC-2).
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLineNettoIsUnitBased:
    def test_line_netto_ignores_article_amount_per_pu(self, tenant):
        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=Decimal("10.000"),
        )
        oc = OrderContentFactory(
            offer=None,
            share_article=article,
            unit="KG",
            amount=Decimal("2.000"),
            price_per_unit=Decimal("3.00"),
            rabatt=None,
            tax_rate=Decimal("7.00"),
        )
        # 2 units × 3 €/unit = 6.00 — the article's amount_per_pu (10) is
        # irrelevant to pricing.
        assert oc.line_netto == Decimal("6.00")

    def test_line_netto_ignores_offer_amount_per_pu(self, tenant):
        """An offer's amount_per_pu does NOT scale the line price — the net is
        amount × price_per_unit, matching the delivery-note / invoice lines."""
        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=Decimal("10.000"),
        )
        offer = OfferFactory(
            share_article=article,
            amount_per_pu=Decimal("5.000"),
            unit="KG",
        )
        oc = OrderContentFactory(
            offer=offer,
            share_article=None,
            unit="KG",
            amount=Decimal("2.000"),
            price_per_unit=Decimal("3.00"),
            rabatt=None,
            tax_rate=Decimal("7.00"),
        )
        # 2 units × 3 €/unit = 6.00 (offer amount_per_pu 5 does not apply).
        assert oc.line_netto == Decimal("6.00")


# ---------------------------------------------------------------------------
# Wire-level: commissioning list endpoint reflects resolved fields
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCommissioningListUsesResolver:
    def test_no_offer_ad_hoc_line_uses_article_defaults(self, tenant):
        from apps.commissioning.viewsets.resellers_viewsets import (
            _build_content_entry,
        )

        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=Decimal("8.000"),
        )
        order = OrderFactory()
        oc = OrderContentFactory(
            order=order,
            offer=None,
            share_article=article,
            amount=Decimal("3.000"),
            unit="KG",
            size="M",
        )
        entry = _build_content_entry(oc)
        assert entry["amount_per_pu"] == 8.0
        assert entry["unit"] == "KG"
        assert entry["size"] == "M"
        assert entry["share_article_id"] == str(article.id)

    def test_offer_bound_line_uses_offer_values(self, tenant):
        from apps.commissioning.viewsets.resellers_viewsets import (
            _build_content_entry,
        )

        article = ShareArticleFactory(
            default_movement_unit="KG",
            default_kg_per_pu_reseller=Decimal("8.000"),
        )
        offer = OfferFactory(
            share_article=article,
            unit="KG",
            size="L",
            amount_per_pu=Decimal("2.500"),
        )
        order = OrderFactory()
        oc = OrderContentFactory(
            order=order,
            offer=offer,
            share_article=None,
            amount=Decimal("3.000"),
            unit="KG",
            size="L",
        )
        entry = _build_content_entry(oc)
        # Offer's 2.5 must win over the article's 8.
        assert entry["amount_per_pu"] == 2.5
        assert entry["size"] == "L"
        # share_article_id comes from offer.share_article (OC row has none).
        assert entry["share_article_id"] == str(article.id)
