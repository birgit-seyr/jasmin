"""Tests for the canonical tax_rate resolution chain.

Walks the three-step fallback documented in
``apps.commissioning.utils.tax_rate_utils``:

    1. Stored ``content.tax_rate``
    2. ``pricing.tax_rate`` on the date (dated pricing tables)
    3. tenant default → hardcoded default

The pricing chain for **articles** is offer → share_article → pricing,
plus a direct ``content.share_article`` fallback. The chain for
**crates** is crate_type → pricing.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.commissioning.constants import (
    DEFAULT_CRATE_TAX_RATE,
    DEFAULT_TAX_RATE,
    get_default_tax_rate_articles,
    get_default_tax_rate_crates,
)
from apps.commissioning.utils.tax_rate_utils import (
    resolve_article_tax_rate,
    resolve_crate_tax_rate,
)
from apps.shared.tenants.models import TenantSettings

from ..factories import (
    CrateFactory,
    CrateNetPriceFactory,
    OfferFactory,
    OrderContentFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
)

# All `valid_from` dates must be Mondays — TimeBoundMixin enforces it.
MONDAY_2026_01_05 = datetime.date(2026, 1, 5)
SUNDAY_2026_03_29 = datetime.date(2026, 3, 29)
MONDAY_2026_03_30 = datetime.date(2026, 3, 30)
PRICING_DATE = datetime.date(2026, 4, 1)  # Wednesday — used as a lookup date only


def _ensure_settings(tenant):
    """Ensure the test tenant has a TenantSettings row so
    ``get_default_tax_rate_*`` can read from it."""
    TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults=dict(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(days=365),
            valid_until=None,
        ),
    )


# ---------------------------------------------------------------------------
# resolve_article_tax_rate
# ---------------------------------------------------------------------------
class TestResolveArticleTaxRate:
    """Three layers: stored row, dated pricing, default."""

    @pytest.mark.django_db
    def test_resolves_via_offer_share_article(self, tenant):
        """A content row attached to an Offer reads from the offer's
        share_article's pricing on the given date."""
        share_article = ShareArticleFactory()
        ShareArticleNetPriceFactory(
            share_article=share_article,
            valid_from=MONDAY_2026_01_05,
            tax_rate=Decimal("19.00"),
        )
        offer = OfferFactory(share_article=share_article)
        content = SimpleNamespace(offer=offer, share_article=None)

        result = resolve_article_tax_rate(content, PRICING_DATE)

        assert result == Decimal("19.00")

    @pytest.mark.django_db
    def test_resolves_via_direct_share_article(self, tenant):
        """A content row with `share_article` set (no offer) reads from
        that article's pricing."""
        share_article = ShareArticleFactory()
        ShareArticleNetPriceFactory(
            share_article=share_article,
            valid_from=MONDAY_2026_01_05,
            tax_rate=Decimal("7.00"),
        )
        content = SimpleNamespace(offer=None, share_article=share_article)

        assert resolve_article_tax_rate(content, PRICING_DATE) == Decimal("7.00")

    @pytest.mark.django_db
    def test_returns_default_when_no_pricing(self, tenant):
        """If no pricing record covers the date, falls back to *default*."""
        share_article = ShareArticleFactory()
        content = SimpleNamespace(offer=None, share_article=share_article)

        result = resolve_article_tax_rate(content, PRICING_DATE, default=42)

        assert result == 42

    @pytest.mark.django_db
    def test_returns_none_when_no_default(self, tenant):
        """Without a *default*, an unresolvable lookup returns None — this
        is what the OrderContent list path uses for unused offers."""
        share_article = ShareArticleFactory()
        content = SimpleNamespace(offer=None, share_article=share_article)

        assert resolve_article_tax_rate(content, PRICING_DATE) is None

    @pytest.mark.django_db
    def test_picks_latest_pricing_valid_on_date(self, tenant):
        """When multiple pricing rows exist, the one valid on the given
        date wins — proves the chain respects ``valid_from`` / ``valid_until``."""
        share_article = ShareArticleFactory()
        ShareArticleNetPriceFactory(
            share_article=share_article,
            valid_from=MONDAY_2026_01_05,
            valid_until=SUNDAY_2026_03_29,
            tax_rate=Decimal("19.00"),
        )
        ShareArticleNetPriceFactory(
            share_article=share_article,
            valid_from=MONDAY_2026_03_30,
            tax_rate=Decimal("7.00"),
        )
        content = SimpleNamespace(offer=None, share_article=share_article)

        # April → second record applies.
        result = resolve_article_tax_rate(content, datetime.date(2026, 4, 15))
        assert result == Decimal("7.00")

        # February → first record applies.
        result = resolve_article_tax_rate(content, datetime.date(2026, 2, 15))
        assert result == Decimal("19.00")


# ---------------------------------------------------------------------------
# resolve_crate_tax_rate
# ---------------------------------------------------------------------------
class TestResolveCrateTaxRate:
    @pytest.mark.django_db
    def test_resolves_via_crate_pricing(self, tenant):
        crate = CrateFactory()
        CrateNetPriceFactory(
            crate=crate,
            valid_from=MONDAY_2026_01_05,
            tax_rate=Decimal("19.00"),
        )

        assert resolve_crate_tax_rate(crate, PRICING_DATE) == Decimal("19.00")

    @pytest.mark.django_db
    def test_returns_default_when_no_pricing(self, tenant):
        crate = CrateFactory()

        assert resolve_crate_tax_rate(crate, PRICING_DATE, default=99) == 99

    def test_returns_default_when_crate_is_none(self):
        """Guard for the OrderInfoPanel-style call where no crate is selected
        yet — see crates_viewsets._get_tax_rate."""
        assert resolve_crate_tax_rate(None, PRICING_DATE, default=19) == 19


# ---------------------------------------------------------------------------
# Tenant-default helpers (third resolution layer)
# ---------------------------------------------------------------------------
class TestTenantDefaults:
    """``get_default_tax_rate_*`` is the canonical "no per-row, no
    pricing" fallback. It reads ``TenantSettings`` and falls back to the
    module-level constants if that lookup fails."""

    @pytest.mark.django_db
    def test_articles_returns_tenant_setting(self, tenant):
        _ensure_settings(tenant)
        settings = TenantSettings.get_current_settings(tenant)
        settings.default_tax_rate_articles = Decimal("10.50")
        settings.save(update_fields=["default_tax_rate_articles"])

        assert get_default_tax_rate_articles() == Decimal("10.50")

    @pytest.mark.django_db
    def test_crates_returns_tenant_setting(self, tenant):
        _ensure_settings(tenant)
        settings = TenantSettings.get_current_settings(tenant)
        settings.default_tax_rate_crates = Decimal("16.00")
        settings.save(update_fields=["default_tax_rate_crates"])

        assert get_default_tax_rate_crates() == Decimal("16.00")

    def test_articles_falls_back_to_hardcoded_constant(self, monkeypatch):
        """When the tenant-setting lookup returns ``None`` (no tenant
        context, no settings row, ...), the helper falls back to
        ``DEFAULT_TAX_RATE``.

        The previous test relied on a bare ``except Exception`` to catch
        pytest-django's ``RuntimeError`` for un-marked DB access — that
        was an implementation detail of the test harness, not a
        production failure mode. After the 2026-05-23 silent-defaults
        audit narrowed the catch, we mock the inner resolver directly
        so the test exercises the actual production contract: "if the
        lookup returns None, fall back to the constant".
        """
        from apps.commissioning import constants

        monkeypatch.setattr(constants, "_resolve_tenant_setting", lambda _: None)
        assert get_default_tax_rate_articles() == DEFAULT_TAX_RATE

    def test_crates_falls_back_to_hardcoded_constant(self, monkeypatch):
        from apps.commissioning import constants

        monkeypatch.setattr(constants, "_resolve_tenant_setting", lambda _: None)
        assert get_default_tax_rate_crates() == DEFAULT_CRATE_TAX_RATE


# ---------------------------------------------------------------------------
# End-to-end: snapshot via DN/Invoice services
# ---------------------------------------------------------------------------
class TestSnapshotPropagation:
    """The order → delivery-note → invoice flow snapshots ``tax_rate`` on
    each row. Once snapshotted, downstream pricing changes don't affect
    historical documents."""

    @pytest.mark.django_db
    def test_order_content_keeps_explicit_tax_rate(self, tenant):
        """A tax_rate set on the OrderContent survives `_serialize_order_content`."""
        from apps.commissioning.services.order_content_service import (
            OrderContentService,
        )

        oc = OrderContentFactory(tax_rate=Decimal("12.50"))

        row = OrderContentService._serialize_order_content(oc)
        assert row["tax_rate"] == Decimal("12.50")

    # NOTE: A test for the share_article-pricing fallback used to live here,
    # but `tax_rate` is now NOT NULL on OrderableItem — every OrderContent
    # carries an explicit value, so the snapshot path always reads it back
    # verbatim. The fallback chain remains exercised by the
    # `resolve_article_tax_rate` tests above (used when *creating* new rows).
