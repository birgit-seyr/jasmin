"""Shared tax-rate resolution helpers.

Canonical resolution order for any line-item tax_rate (used by Order
contents, Delivery-note contents, Invoice contents, and the crate variants
of each):

    1. The stored ``content.tax_rate`` on the row — set explicitly by the
       caller / copied from the upstream row when the document is created.
    2. ``resolve_article_tax_rate(content, date)`` / ``resolve_crate_tax_rate``
       — walks the FK chain (offer → share_article → pricing, or
       crate → pricing) and returns ``pricing.tax_rate`` on the given
       date if a record exists. ``ShareArticleNetPrice`` / ``CrateNetPrice``
       are the dated pricing tables.
    3. The tenant default — ``get_default_tax_rate_articles()`` /
       ``get_default_tax_rate_crates()`` (see
       ``apps.commissioning.constants``) — which falls back to the
       hardcoded ``DEFAULT_TAX_RATE`` / ``DEFAULT_CRATE_TAX_RATE`` if
       the tenant-settings lookup fails.

The per-row ``tax_rate`` field is therefore a **snapshot** taken at write
time; this module is the canonical resolver everywhere else (services,
viewsets, summary endpoints). Never inline a hardcoded fallback at a
call site — use one of these helpers so the resolution stays in one
place.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal


def resolve_article_tax_rate(
    content,
    date: _date,
    *,
    default: Decimal | int | None = None,
) -> Decimal | int | None:
    """Walk offer → share_article to find a tax rate on *date*.

    *content* can be an ``OrderContent``, ``InvoiceResellerContent``,
    ``DeliveryNoteContent``, or any object that exposes the same FK chain.

    If nothing is found, *default* is returned (``None`` by default;
    pass ``get_default_tax_rate_articles()`` when a fallback is needed).
    """
    if getattr(content, "offer", None) and getattr(
        content.offer, "share_article", None
    ):
        pricing = content.offer.share_article.get_pricing_on_date(date)
        if pricing and getattr(pricing, "tax_rate", None) is not None:
            return pricing.tax_rate

    if getattr(content, "share_article", None):
        pricing = content.share_article.get_pricing_on_date(date)
        if pricing and getattr(pricing, "tax_rate", None) is not None:
            return pricing.tax_rate

    return default


def resolve_crate_tax_rate(
    crate_type,
    date: _date,
    *,
    default: Decimal | int | None = None,
) -> Decimal | int | None:
    """Resolve a tax rate from a crate type's pricing valid on *date*.

    If nothing is found, *default* is returned (``None`` by default;
    pass ``get_default_tax_rate_crates()`` when a fallback is needed).
    """
    if hasattr(crate_type, "get_pricing_on_date"):
        pricing = crate_type.get_pricing_on_date(date)
        if pricing and getattr(pricing, "tax_rate", None) is not None:
            return pricing.tax_rate
    return default
