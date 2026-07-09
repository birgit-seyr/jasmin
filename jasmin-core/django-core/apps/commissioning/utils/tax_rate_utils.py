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

from ..constants import get_default_tax_rate_articles, get_default_tax_rate_crates


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


def effective_article_tax_rate(
    content,
    date: _date,
) -> Decimal | int:
    """Canonical stored → resolved → tenant-default article tax rate.

    Folds the three-step resolution that every article line-write site
    otherwise re-spells inline:

        1. the row's own stored ``content.tax_rate`` snapshot, if set;
        2. else the dated pricing chain (``resolve_article_tax_rate``);
        3. else the tenant default (``get_default_tax_rate_articles``).

    Use this at write sites that need a guaranteed non-null rate. For
    the display-only path that must return ``None`` when nothing is
    stored/resolved, call ``resolve_article_tax_rate`` directly (no
    default).
    """
    stored = getattr(content, "tax_rate", None)
    if stored is not None:
        return stored
    return resolve_article_tax_rate(
        content, date, default=get_default_tax_rate_articles()
    )


def effective_crate_tax_rate(
    crate_type,
    date: _date,
) -> Decimal | int:
    """Canonical resolved → tenant-default crate tax rate.

    The crate's dated pricing ``tax_rate`` if present, else the tenant
    default (``get_default_tax_rate_crates``). Unlike the article helper
    there is no stored snapshot to fold in here — a crate's stored rate
    lives on the CONTENT row, not on ``crate_type`` — so callers that
    have a content row keep the ``content.tax_rate if ... is not None
    else effective_crate_tax_rate(...)`` guard at the call site.
    """
    return resolve_crate_tax_rate(
        crate_type, date, default=get_default_tax_rate_crates()
    )
