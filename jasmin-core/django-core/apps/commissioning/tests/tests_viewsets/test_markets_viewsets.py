"""Endpoints of the market price lists: market product groups, PLUs, the
weekly prices with their copy and scale export, and the scale tax codes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.constants import get_default_tax_rate_articles
from apps.commissioning.models import MarketPrice
from apps.commissioning.tests.factories import (
    JasminUserFactory,
    MarketArticleFactory,
    MarketPriceFactory,
    MarketProductGroupFactory,
    ScaleTaxCodeFactory,
    ShareArticleFactory,
)
from apps.shared.money import to_decimal

PRICES = reverse("market_prices-list")
WEEK = {"year": 2025, "delivery_week": 10}


def _client(*roles: str) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=JasminUserFactory(roles=list(roles)))
    return client


@pytest.mark.django_db
class TestMarketProductGroups:
    URL = reverse("market_product_groups-list")

    def test_a_group_with_plus_cannot_be_deleted(self, api_client, tenant):
        group = MarketProductGroupFactory()
        MarketArticleFactory(product_group=group)

        resp = api_client.delete(
            reverse("market_product_groups-detail", args=[group.pk])
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "market_product_group.in_use"

    def test_an_unused_group_is_deleted(self, api_client, tenant):
        group = MarketProductGroupFactory()

        resp = api_client.delete(
            reverse("market_product_groups-detail", args=[group.pk])
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT

    def test_the_plu_list_names_the_group(self, api_client, tenant):
        group = MarketProductGroupFactory(name="Apples")
        MarketArticleFactory(product_group=group)
        MarketArticleFactory(product_group=None)

        resp = api_client.get(reverse("market_articles-list"))

        assert sorted(row["product_group_name"] or "" for row in resp.data) == [
            "",
            "Apples",
        ]

    def test_staff_read_but_only_the_office_writes(self, tenant):
        staff = _client("staff")

        assert staff.get(self.URL).status_code == status.HTTP_200_OK
        resp = staff.post(self.URL, {"number": 1, "name": "Apples"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestMarketArticles:
    URL = reverse("market_articles-list")

    def _payload(self, **fields):
        return {
            "plu_number": 101,
            "share_article": ShareArticleFactory().pk,
            "unit": "BUNCH",
            "size": "M",
            "name": "Radish",
            **fields,
        }

    def test_a_plu_sold_by_the_bunch(self, api_client, tenant):
        code = ScaleTaxCodeFactory()
        article = ShareArticleFactory(name="Radish")

        resp = api_client.post(
            self.URL,
            self._payload(share_article=article.pk, scale_tax_code=code.pk),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["share_article_name"] == "Radish"

    def test_a_plu_of_bought_in_goods_names_no_article(self, api_client, tenant):
        code = ScaleTaxCodeFactory()

        resp = api_client.post(
            self.URL,
            self._payload(share_article=None, scale_tax_code=code.pk),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["share_article"] is None
        assert resp.data["share_article_name"] is None

    def test_a_new_plu_without_a_code_takes_the_default_rates(self, api_client, tenant):
        """An article without a price falls back to the farm's default rate,
        whose code the PLU then sells under."""
        code = ScaleTaxCodeFactory(
            tax_rate=to_decimal(get_default_tax_rate_articles()), code=4
        )

        resp = api_client.post(self.URL, self._payload(), format="json")

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["scale_tax_code"] == code.pk

    @pytest.mark.parametrize("cleared", [None, ""])
    def test_a_new_plu_with_a_cleared_code_takes_the_default_rates(
        self, api_client, tenant, cleared
    ):
        code = ScaleTaxCodeFactory(
            tax_rate=to_decimal(get_default_tax_rate_articles()), code=4
        )

        resp = api_client.post(
            self.URL, self._payload(scale_tax_code=cleared), format="json"
        )

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["scale_tax_code"] == code.pk

    def test_clearing_the_code_of_a_plu_takes_the_default_rates(
        self, api_client, tenant
    ):
        default = ScaleTaxCodeFactory(
            tax_rate=to_decimal(get_default_tax_rate_articles()), code=4
        )
        other = ScaleTaxCodeFactory(tax_rate=default.tax_rate + 12, code=2)
        plu = MarketArticleFactory(scale_tax_code=other)

        resp = api_client.patch(
            reverse("market_articles-detail", args=[plu.pk]),
            {"scale_tax_code": None},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["scale_tax_code"] == default.pk

    def test_a_picked_code_is_kept(self, api_client, tenant):
        ScaleTaxCodeFactory()
        nineteen = ScaleTaxCodeFactory(tax_rate=Decimal("19.00"), code=2)

        resp = api_client.post(
            self.URL, self._payload(scale_tax_code=nineteen.pk), format="json"
        )

        assert resp.data["scale_tax_code"] == nineteen.pk

    def test_a_rate_the_scale_has_no_code_for_is_refused(self, api_client, tenant):
        resp = api_client.post(self.URL, self._payload(), format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "scale_tax_code.missing"
        assert resp.json()["field"] == "scale_tax_code"

    def test_a_plu_with_prices_cannot_be_deleted(self, api_client, tenant):
        price = MarketPriceFactory()
        url = reverse("market_articles-detail", args=[price.market_article_id])

        resp = api_client.delete(url)

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "market_article.in_use"

    def test_a_plu_without_prices_is_deleted(self, api_client, tenant):
        plu = MarketArticleFactory()

        resp = api_client.delete(reverse("market_articles-detail", args=[plu.pk]))

        assert resp.status_code == status.HTTP_204_NO_CONTENT

    def test_the_list_queries_do_not_grow_with_the_rows(
        self, api_client, tenant, django_assert_max_num_queries
    ):
        for _ in range(10):
            MarketArticleFactory(product_group=MarketProductGroupFactory())

        with django_assert_max_num_queries(6):
            resp = api_client.get(reverse("market_articles-list"))

        assert len(resp.data) == 10


@pytest.mark.django_db
class TestMarketPriceList:
    def test_the_week_is_required(self, api_client, tenant):
        resp = api_client.get(PRICES, {"year": 2025})

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_sorted_by_group_number_then_plu(self, api_client, tenant):
        second = MarketProductGroupFactory(number=2)
        first = MarketProductGroupFactory(number=1)
        for plu_number, group in ((5, first), (3, second), (4, first)):
            MarketPriceFactory(
                **WEEK,
                market_article=MarketArticleFactory(
                    plu_number=plu_number, product_group=group
                ),
            )

        resp = api_client.get(PRICES, WEEK)

        assert [row["plu_number"] for row in resp.data] == [4, 5, 3]
        assert resp.data[0]["product_group_number"] == 1

    def test_a_plu_without_group_lists_none(self, api_client, tenant):
        MarketPriceFactory(**WEEK)

        resp = api_client.get(PRICES, WEEK)

        assert resp.data[0]["product_group_number"] is None
        assert resp.data[0]["product_group_name"] is None

    def test_changes_against_the_week_before(self, api_client, tenant):
        """A new price, another price and another origin are changes; the same
        price and origin are not."""
        for name, before, now in (
            ("same", ("2.00", "DE"), ("2.00", "DE")),
            ("price", ("2.00", "DE"), ("2.20", "DE")),
            ("origin", ("2.00", "DE"), ("2.00", "ES")),
            ("new", None, ("2.00", None)),
        ):
            plu = MarketArticleFactory(name=name)
            if before:
                MarketPriceFactory(
                    market_article=plu,
                    year=2025,
                    delivery_week=9,
                    gross_price=Decimal(before[0]),
                    origin=before[1],
                )
            MarketPriceFactory(
                **WEEK,
                market_article=plu,
                gross_price=Decimal(now[0]),
                origin=now[1],
            )

        resp = api_client.get(PRICES, WEEK)

        rows = {row["name"]: row for row in resp.data}
        assert {label: row["is_changed"] for label, row in rows.items()} == {
            "same": False,
            "price": True,
            "origin": True,
            "new": True,
        }
        assert rows["price"]["previous_gross_price"] == "2.00"
        assert rows["new"]["previous_gross_price"] is None

    def test_the_queries_do_not_grow_with_the_rows(
        self, api_client, tenant, django_assert_max_num_queries
    ):
        for _ in range(10):
            price = MarketPriceFactory(
                **WEEK, market_article__product_group=MarketProductGroupFactory()
            )
            MarketPriceFactory(
                market_article=price.market_article, year=2025, delivery_week=9
            )

        with django_assert_max_num_queries(6):
            resp = api_client.get(PRICES, WEEK)

        assert len(resp.data) == 10

    def test_week_one_compares_with_week_53(self, api_client, tenant):
        plu = MarketArticleFactory()
        MarketPriceFactory(
            market_article=plu, year=2020, delivery_week=53, gross_price=Decimal("1")
        )
        MarketPriceFactory(
            market_article=plu, year=2021, delivery_week=1, gross_price=Decimal("1")
        )

        resp = api_client.get(PRICES, {"year": 2021, "delivery_week": 1})

        assert resp.data[0]["is_changed"] is False


@pytest.mark.django_db
class TestMarketPriceWrites:
    def test_an_edit_answers_with_the_change_marker(self, api_client, tenant):
        before = MarketPriceFactory(year=2025, delivery_week=9)
        price = MarketPriceFactory(**WEEK, market_article=before.market_article)
        url = reverse("market_prices-detail", args=[price.pk])

        resp = api_client.patch(url, {"gross_price": "9.99"}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_changed"] is True
        assert resp.data["previous_gross_price"] == str(before.gross_price)

    def test_an_edit_cannot_move_the_price_to_another_week(self, api_client, tenant):
        price = MarketPriceFactory(**WEEK)
        url = reverse("market_prices-detail", args=[price.pk])

        api_client.patch(url, {"delivery_week": 11}, format="json")

        price.refresh_from_db()
        assert price.delivery_week == 10

    def test_a_second_price_for_the_plu_in_the_week_is_refused(
        self, api_client, tenant
    ):
        price = MarketPriceFactory(**WEEK)

        resp = api_client.post(
            PRICES,
            {**WEEK, "market_article": price.market_article_id, "gross_price": "1.00"},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert MarketPrice.objects.count() == 1

    def test_staff_read_but_only_the_office_writes(self, tenant):
        staff = _client("staff")
        price = MarketPriceFactory(**WEEK)

        assert staff.get(PRICES, WEEK).status_code == status.HTTP_200_OK
        resp = staff.patch(
            reverse("market_prices-detail", args=[price.pk]),
            {"gross_price": "1.00"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_copy_to_next_week(self, api_client, tenant):
        price = MarketPriceFactory(**WEEK)

        resp = api_client.post(
            reverse("market_prices-bulk-copy-to-next-week"),
            {"ids": [price.pk]},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data == {
            "total_requested": 1,
            "total_copied": 1,
            "skipped_count": 0,
        }
        assert MarketPrice.objects.filter(year=2025, delivery_week=11).exists()

    def test_takes_the_selected_prices_off_sale_and_back(self, api_client, tenant):
        first, second = MarketPriceFactory(**WEEK), MarketPriceFactory(**WEEK)
        untouched = MarketPriceFactory(**WEEK)
        url = reverse("market_prices-bulk-set-active")

        resp = api_client.post(
            url, {"ids": [first.pk, second.pk], "is_active": False}, format="json"
        )

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert set(
            MarketPrice.objects.filter(is_active=False).values_list("pk", flat=True)
        ) == {first.pk, second.pk}
        untouched.refresh_from_db()
        assert untouched.is_active is True

        api_client.post(url, {"ids": [first.pk], "is_active": True}, format="json")

        first.refresh_from_db()
        assert first.is_active is True

    def test_set_active_needs_the_flag(self, api_client, tenant):
        price = MarketPriceFactory(**WEEK)

        resp = api_client.post(
            reverse("market_prices-bulk-set-active"),
            {"ids": [price.pk]},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "required_field.missing"
        assert resp.json()["field"] == "is_active"
        price.refresh_from_db()
        assert price.is_active is True

    def test_set_active_needs_ids(self, api_client, tenant):
        resp = api_client.post(
            reverse("market_prices-bulk-set-active"),
            {"is_active": True},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "required_field.missing"
        assert resp.json()["field"] == "ids"

    def test_copy_needs_ids(self, api_client, tenant):
        resp = api_client.post(
            reverse("market_prices-bulk-copy-to-next-week"), {}, format="json"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestScaleExportEndpoint:
    URL = reverse("market_prices-scale-export")

    def test_answers_an_xlsx_file(self, api_client, tenant):
        MarketPriceFactory(**WEEK)

        resp = api_client.get(self.URL, WEEK)

        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert 'filename="scale_export_2025_10.xlsx"' in resp["Content-Disposition"]
        assert resp.content.startswith(b"PK")

    def test_a_unit_the_scale_cannot_sell_answers_409(self, api_client, tenant):
        MarketPriceFactory(
            **WEEK, market_article=MarketArticleFactory(plu_number=7, unit="L")
        )

        resp = api_client.get(self.URL, WEEK)

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.json()["code"] == "scale_unit.unsupported"
        assert resp.json()["details"] == {"plu_numbers": "7"}

    def test_staff_cannot_export(self, tenant):
        resp = _client("staff").get(self.URL, WEEK)

        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestScaleTaxCodes:
    def test_one_code_per_rate(self, api_client, tenant):
        ScaleTaxCodeFactory(tax_rate=Decimal("7.00"), code=1)

        resp = api_client.post(
            reverse("scale_tax_codes-list"),
            {"tax_rate": "7.00", "code": 3},
            format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_code_plus_sell_under_cannot_be_deleted(self, api_client, tenant):
        code = MarketArticleFactory().scale_tax_code

        resp = api_client.delete(reverse("scale_tax_codes-detail", args=[code.pk]))

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data["code"] == "scale_tax_code.in_use"

    def test_an_unused_code_is_deleted(self, api_client, tenant):
        code = ScaleTaxCodeFactory()

        resp = api_client.delete(reverse("scale_tax_codes-detail", args=[code.pk]))

        assert resp.status_code == status.HTTP_204_NO_CONTENT
