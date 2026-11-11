"""The XLSX the market scales import for one week, and the scale VAT code a
new PLU sells under."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from django.utils import timezone
from isoweek import Week
from openpyxl import load_workbook

from apps.commissioning.constants import get_default_tax_rate_articles
from apps.commissioning.errors import ScaleTaxCodeMissing, ScaleUnitUnsupported
from apps.commissioning.models import MarketArticle
from apps.commissioning.services.market_scale_export import (
    HEADER,
    default_scale_tax_code,
    scale_export_workbook,
)
from apps.commissioning.tests.factories import (
    MarketArticleFactory,
    MarketPriceFactory,
    MarketProductGroupFactory,
    ScaleTaxCodeFactory,
    ShareArticleFactory,
    ShareArticleNetPriceFactory,
)
from apps.shared.money import to_decimal

WEEK = {"year": 2025, "delivery_week": 10}


def _rows(content: bytes) -> list[tuple]:
    sheet = load_workbook(BytesIO(content)).active
    return list(sheet.iter_rows(values_only=True))


@pytest.mark.django_db
class TestScaleExport:
    def test_rows_by_plu_number_with_origin_unit_flags_group_and_tax_code(self, tenant):
        MarketPriceFactory(
            **WEEK,
            market_article=MarketArticleFactory(
                plu_number=205,
                share_article=None,
                unit="PCS",
                name="Rye bread",
                allows_discount_price=False,
                scale_tax_code=ScaleTaxCodeFactory(tax_rate=Decimal("19.00"), code=2),
            ),
            gross_price=Decimal("4.20"),
        )
        MarketPriceFactory(
            **WEEK,
            market_article=MarketArticleFactory(
                plu_number=101,
                product_group=MarketProductGroupFactory(number=4),
                name="Elstar apple",
                scale_tax_code=ScaleTaxCodeFactory(tax_rate=Decimal("7.00"), code=1),
            ),
            gross_price=Decimal("3.49"),
            origin="DE",
        )

        rows = _rows(scale_export_workbook(**WEEK))

        assert rows == [
            tuple(HEADER),
            (101, "Elstar apple DE", "3,49", "kg", "Ja", "Ja", 4, 1),
            (205, "Rye bread", "4,20", "St.", "Ja", "Nein", None, 2),
        ]

    def test_the_queries_do_not_grow_with_the_rows(
        self, tenant, django_assert_max_num_queries
    ):
        for _ in range(10):
            MarketPriceFactory(
                **WEEK,
                market_article=MarketArticleFactory(
                    product_group=MarketProductGroupFactory()
                ),
            )

        with django_assert_max_num_queries(2):
            rows = _rows(scale_export_workbook(**WEEK))

        assert len(rows) == 11

    def test_bunches_are_counted(self, tenant):
        MarketPriceFactory(**WEEK, market_article=MarketArticleFactory(unit="BUNCH"))

        assert _rows(scale_export_workbook(**WEEK))[1][3] == "St."

    def test_inactive_and_other_weeks_are_left_out(self, tenant):
        plu = MarketArticleFactory()
        MarketPriceFactory(**WEEK, market_article=plu, is_active=False)
        MarketPriceFactory(year=2025, delivery_week=11, market_article=plu)

        assert _rows(scale_export_workbook(**WEEK)) == [tuple(HEADER)]

    def test_a_formula_in_a_name_stays_text(self, tenant):
        MarketPriceFactory(
            **WEEK, market_article=MarketArticleFactory(name='=HYPERLINK("x")')
        )

        sheet = load_workbook(BytesIO(scale_export_workbook(**WEEK))).active

        assert sheet["B2"].data_type == "s"
        assert sheet["B2"].value == '=HYPERLINK("x")'

    def test_a_plu_sold_by_the_gram_refuses_the_export(self, tenant):
        MarketPriceFactory(
            **WEEK, market_article=MarketArticleFactory(plu_number=120, unit="G")
        )

        with pytest.raises(ScaleUnitUnsupported) as refusal:
            scale_export_workbook(**WEEK)

        assert refusal.value.details == {"plu_numbers": "120"}


@pytest.mark.django_db
class TestDefaultScaleTaxCode:
    def test_the_code_of_the_articles_rate_today(self, tenant):
        ScaleTaxCodeFactory(tax_rate=Decimal("7.00"), code=1)
        nineteen = ScaleTaxCodeFactory(tax_rate=Decimal("19.00"), code=2)
        article = ShareArticleFactory()
        ShareArticleNetPriceFactory(
            share_article=article,
            valid_from=Week.withdate(timezone.localdate()).monday(),
            tax_rate=Decimal("19.00"),
        )

        assert default_scale_tax_code(MarketArticle(share_article=article)) == nineteen

    def test_an_article_without_a_price_today_takes_the_default_rate(self, tenant):
        default = ScaleTaxCodeFactory(
            tax_rate=to_decimal(get_default_tax_rate_articles()), code=5
        )
        plu = MarketArticle(share_article=ShareArticleFactory())

        assert default_scale_tax_code(plu) == default

    def test_a_plu_without_article_takes_the_default_rate(self, tenant):
        default = ScaleTaxCodeFactory(
            tax_rate=to_decimal(get_default_tax_rate_articles()), code=5
        )

        assert default_scale_tax_code(MarketArticle(share_article=None)) == default

    def test_a_rate_the_scale_has_no_code_for_is_refused(self, tenant):
        rate = to_decimal(get_default_tax_rate_articles())
        ScaleTaxCodeFactory(tax_rate=rate + 1, code=2)

        with pytest.raises(ScaleTaxCodeMissing) as refusal:
            default_scale_tax_code(MarketArticle(share_article=None))

        assert refusal.value.field == "scale_tax_code"
        assert refusal.value.details == {"tax_rate": f"{rate.normalize():f}"}
