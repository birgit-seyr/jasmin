"""The import file for the market scales, one row per PLU priced in a week,
and the scale VAT code a new PLU sells under."""

from __future__ import annotations

from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook

from apps.shared.money import to_decimal

from ..constants import get_default_tax_rate_articles
from ..errors import ScaleTaxCodeMissing, ScaleUnitUnsupported
from ..models import MarketArticle, MarketPrice, ScaleTaxCode
from ..models.choices import UnitOptions
from ..utils.tax_rate_utils import resolve_article_tax_rate

# The column names, units and yes / no values are the ones the scale software's
# import reads, so they stay German.
HEADER = [
    "PLU Nummer",
    "PLU Name",
    "Preis",
    "Maßeinheit",
    "Preisüberschreibung",
    "Rabattpreis",
    "Warengruppe",
    "MwSt. ID",
]
YES, NO = "Ja", "Nein"
# The scale either weighs by the kg or counts; a bunch is counted. A price per
# gram or litre has no scale unit it could be sold under.
SCALE_UNITS = {UnitOptions.KG: "kg", UnitOptions.PCS: "St.", UnitOptions.BUNCH: "St."}


def scale_export_workbook(year: int, delivery_week: int) -> bytes:
    """The XLSX the scales import for ``year`` / ``delivery_week``: the week's
    active prices by PLU number.

    Raises :class:`ScaleUnitUnsupported` when a PLU's unit is neither weighed
    nor counted."""
    prices = list(
        MarketPrice.objects.filter(
            year=year, delivery_week=delivery_week, is_active=True
        )
        .select_related(
            "market_article__product_group", "market_article__scale_tax_code"
        )
        .order_by("market_article__plu_number")
    )
    unsupported = [
        price.market_article.plu_number
        for price in prices
        if price.market_article.unit not in SCALE_UNITS
    ]
    if unsupported:
        raise ScaleUnitUnsupported(plu_numbers=unsupported)

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADER)
    for price in prices:
        sheet.append(_row(price))
    # A text cell starting with "=" would be stored as a formula and run when
    # the file is opened; typing every text cell as a string keeps it text.
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def default_scale_tax_code(market_article: MarketArticle) -> ScaleTaxCode:
    """The scale VAT code a new PLU sells under when none is picked: the code
    of its share article's VAT rate today, else of the farm's default rate for
    articles.

    Raises :class:`ScaleTaxCodeMissing` when the scale has no code for that
    rate."""
    rate = to_decimal(
        resolve_article_tax_rate(
            market_article,
            timezone.localdate(),
            default=get_default_tax_rate_articles(),
        )
    )
    code = ScaleTaxCode.objects.filter(tax_rate=rate).first()
    if code is None:
        raise ScaleTaxCodeMissing(tax_rate=rate)
    return code


def _row(price: MarketPrice) -> list:
    market_article = price.market_article
    product_group = market_article.product_group
    allows_override = YES if market_article.allows_price_override else NO
    allows_discount = YES if market_article.allows_discount_price else NO
    return [
        market_article.plu_number,
        " ".join(filter(None, [market_article.name, price.origin])),
        f"{price.gross_price:.2f}".replace(".", ","),
        SCALE_UNITS[market_article.unit],
        allows_override,
        allows_discount,
        product_group.number if product_group else "",
        market_article.scale_tax_code.code,
    ]
