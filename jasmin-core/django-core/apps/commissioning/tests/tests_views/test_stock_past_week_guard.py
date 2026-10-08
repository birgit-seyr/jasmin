"""The stock count refuses a week the stock count page shows read-only.

The clock stands on Monday of ISO week 41 of 2026, so week 39 is read-only and
week 40 is the writable grace week.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import MovementShareArticle
from apps.commissioning.models.choices import MovementTypeOptions
from apps.commissioning.tests.factories import (
    HarvestFactory,
    MovementShareArticleFactory,
    ShareArticleFactory,
    StorageFactory,
)
from apps.commissioning.utils import build_composite_id

YEAR = 2026
READ_ONLY_WEEK = 39
GRACE_WEEK = 40


@pytest.fixture(autouse=True)
def _monday_of_week_41():
    with time_machine.travel(datetime.datetime(2026, 10, 5, 12, 0), tick=False):
        yield


def _composite_id(article, storage, week: int) -> str:
    return build_composite_id(
        str(article.id), "KG", "M", str(storage.id), YEAR, week, 1
    )


def _url(article, storage, week: int) -> str:
    return reverse(
        "current_stock_comparison_detail",
        kwargs={"composite_id": _composite_id(article, storage, week)},
    )


def _inventories(article):
    return MovementShareArticle.objects.filter(
        movement_type=MovementTypeOptions.INVENTORY, share_article=article
    )


@pytest.mark.django_db
class TestStockCountPastWeek:
    def test_count_in_a_read_only_week_is_refused(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()

        resp = api_client.patch(
            _url(article, storage, READ_ONLY_WEEK), {"amount": 5}, format="json"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "commissioning.past_week"
        assert not _inventories(article).exists()

    def test_count_in_the_grace_week_is_accepted(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()

        resp = api_client.patch(
            _url(article, storage, GRACE_WEEK), {"amount": 5}, format="json"
        )

        assert resp.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
        assert _inventories(article).exists()

    def test_delete_in_a_read_only_week_is_refused(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            unit="KG",
            size="M",
            movement_type=MovementTypeOptions.INVENTORY,
            amount=Decimal("2"),
            # Tuesday of week 39 — day_number 1 of the composite id.
            date=datetime.datetime(2026, 9, 22, 12, tzinfo=datetime.UTC),
        )

        resp = api_client.delete(_url(article, storage, READ_ONLY_WEEK))

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
        assert resp.data["code"] == "commissioning.past_week"
        assert _inventories(article).exists()


def _stocked_article(storage):
    """An article with a theoretical stock of 50 in *storage*, harvested well
    before both weeks, for the bulk actions to act on."""
    article = ShareArticleFactory()
    MovementShareArticleFactory(
        share_article=article,
        storage=storage,
        harvest=HarvestFactory(share_article=article, storage=storage),
        unit="KG",
        size="M",
        movement_type=MovementTypeOptions.HARVEST,
        amount=Decimal("50"),
        date=datetime.datetime(2026, 9, 1, 12, tzinfo=datetime.UTC),
    )
    return article


@pytest.mark.django_db
class TestStockBulkPastWeek:
    """An id in a read-only week is a per-item error carrying the past-week
    code, while an id in the grace week of the same request is still written."""

    @pytest.mark.parametrize(
        "url_name",
        [
            "bulk_finalize_current_stock",
            "bulk_set_as_expected_current_stock",
            "bulk_set_to_zero_current_stock",
        ],
    )
    def test_read_only_week_id_is_a_per_item_error(self, api_client, tenant, url_name):
        storage = StorageFactory()
        read_only_article = _stocked_article(storage)
        grace_article = _stocked_article(storage)
        read_only_id = _composite_id(read_only_article, storage, READ_ONLY_WEEK)

        resp = api_client.post(
            reverse(url_name),
            {"ids": [read_only_id, _composite_id(grace_article, storage, GRACE_WEEK)]},
            format="json",
        )

        assert resp.status_code == status.HTTP_207_MULTI_STATUS, resp.data
        assert resp.data["created"] == 1
        [error] = resp.data["errors"]
        assert error["id"] == read_only_id
        assert error["code"] == "commissioning.past_week"
        assert not _inventories(read_only_article).exists()
        assert _inventories(grace_article).exists()
