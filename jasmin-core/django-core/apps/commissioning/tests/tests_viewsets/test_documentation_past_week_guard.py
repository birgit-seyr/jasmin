"""The forecast, harvest and purchase documentation refuse a week the pages show
read-only.

A week turns read-only once it lies more than one week behind the current ISO
week; the week right after it is still the grace in which late entries go in.
The clock stands on Monday of ISO week 41 of 2026, so week 39 is read-only and
week 40 is the writable grace week.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import Forecast, Harvest, Purchase
from apps.commissioning.tests.factories import (
    ForecastFactory,
    HarvestFactory,
    PurchaseFactory,
    ShareArticleFactory,
    StorageFactory,
)

YEAR = 2026
READ_ONLY_WEEK = 39
GRACE_WEEK = 40

URL_ADD_ADDITIONAL = reverse("documentation_summary-add-additional-theoretical-amount")


@pytest.fixture(autouse=True)
def _monday_of_week_41():
    with time_machine.travel(datetime.datetime(2026, 10, 5, 12, 0), tick=False):
        yield


def _assert_refused(resp) -> None:
    assert resp.status_code == status.HTTP_409_CONFLICT, resp.data
    assert resp.data["code"] == "commissioning.past_week"


def _harvest_payload(article, storage, week: int) -> dict:
    return {
        "year": YEAR,
        "delivery_week": week,
        "day_number": 1,
        "share_article": str(article.id),
        "unit": "KG",
        "size": "M",
        "amount": "5",
        "storage": str(storage.id),
    }


def _purchase_payload(article, storage, week: int) -> dict:
    return {
        "year": YEAR,
        "delivery_week": week,
        "share_article": str(article.id),
        "unit": "KG",
        "size": "M",
        "amount": "5",
        "storage": str(storage.id),
    }


@pytest.mark.django_db
class TestHarvestPastWeek:
    URL = reverse("harvest-list")

    def test_create_in_a_read_only_week_is_refused(self, api_client, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        payload = _harvest_payload(ShareArticleFactory(), storage, READ_ONLY_WEEK)

        _assert_refused(api_client.post(self.URL, payload, format="json"))
        assert not Harvest.objects.filter(delivery_week=READ_ONLY_WEEK).exists()

    def test_create_in_the_grace_week_is_accepted(self, api_client, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        payload = _harvest_payload(ShareArticleFactory(), storage, GRACE_WEEK)

        resp = api_client.post(self.URL, payload, format="json")

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_update_of_a_read_only_week_row_is_refused(self, api_client, tenant):
        harvest = HarvestFactory(year=YEAR, delivery_week=READ_ONLY_WEEK, amount=3)
        url = reverse("harvest-detail", kwargs={"pk": harvest.pk})

        _assert_refused(api_client.patch(url, {"amount": "7"}, format="json"))
        harvest.refresh_from_db()
        assert harvest.amount == 3

    def test_moving_a_row_into_a_read_only_week_is_refused(self, api_client, tenant):
        harvest = HarvestFactory(year=YEAR, delivery_week=GRACE_WEEK, amount=3)
        url = reverse("harvest-detail", kwargs={"pk": harvest.pk})

        resp = api_client.patch(url, {"delivery_week": READ_ONLY_WEEK}, format="json")

        _assert_refused(resp)

    def test_update_in_the_grace_week_is_accepted(self, api_client, tenant):
        harvest = HarvestFactory(year=YEAR, delivery_week=GRACE_WEEK, amount=3)
        url = reverse("harvest-detail", kwargs={"pk": harvest.pk})

        resp = api_client.patch(url, {"amount": "7"}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.data

    def test_delete_of_a_read_only_week_row_is_refused(self, api_client, tenant):
        harvest = HarvestFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)
        url = reverse("harvest-detail", kwargs={"pk": harvest.pk})

        _assert_refused(api_client.delete(url))
        assert Harvest.objects.filter(pk=harvest.pk).exists()

    def test_bulk_set_as_expected_in_a_read_only_week_is_refused(
        self, api_client, tenant
    ):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        item = {
            "id": str(article.id),
            "year": YEAR,
            "delivery_week": READ_ONLY_WEEK,
            "day_number": 1,
            "theoretical_harvest_amount": "4",
            "theoretical_harvest_unit": "KG",
            "theoretical_harvest_size": "M",
            "storage": str(storage.id),
        }

        resp = api_client.post(
            reverse("harvest-bulk-set-as-expected"),
            {"selectedData": [item]},
            format="json",
        )

        _assert_refused(resp)
        assert not Harvest.objects.filter(share_article=article).exists()


@pytest.mark.django_db
class TestPurchasePastWeek:
    URL = reverse("purchase-list")

    def test_create_in_a_read_only_week_is_refused(self, api_client, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory(is_purchased=True)

        resp = api_client.post(
            self.URL,
            _purchase_payload(article, storage, READ_ONLY_WEEK),
            format="json",
        )

        _assert_refused(resp)
        assert not Purchase.objects.filter(share_article=article).exists()

    def test_create_in_the_grace_week_is_accepted(self, api_client, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory(is_purchased=True)

        resp = api_client.post(
            self.URL, _purchase_payload(article, storage, GRACE_WEEK), format="json"
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_update_of_a_read_only_week_row_is_refused(self, api_client, tenant):
        purchase = PurchaseFactory(year=YEAR, delivery_week=READ_ONLY_WEEK, amount=3)
        url = reverse("purchase-detail", kwargs={"pk": purchase.pk})

        _assert_refused(api_client.patch(url, {"amount": "7"}, format="json"))
        purchase.refresh_from_db()
        assert purchase.amount == 3

    def test_delete_of_a_read_only_week_row_is_refused(self, api_client, tenant):
        purchase = PurchaseFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)
        url = reverse("purchase-detail", kwargs={"pk": purchase.pk})

        _assert_refused(api_client.delete(url))
        assert Purchase.objects.filter(pk=purchase.pk).exists()

    def test_bulk_set_as_expected_in_a_read_only_week_is_refused(
        self, api_client, tenant
    ):
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)
        item = {
            "id": str(article.id),
            "year": YEAR,
            "delivery_week": READ_ONLY_WEEK,
            "theoretical_purchase_amount": "4",
            "theoretical_purchase_unit": "KG",
            "theoretical_purchase_size": "M",
            "storage": str(storage.id),
        }

        resp = api_client.post(
            reverse("purchase-bulk-set-as-expected"),
            {"selectedData": [item]},
            format="json",
        )

        _assert_refused(resp)
        assert not Purchase.objects.filter(share_article=article).exists()


@pytest.mark.django_db
class TestAdditionalTheoreticalPastWeek:
    def _add(self, api_client, article, week: int):
        StorageFactory(is_short_term_harvest_storage=True)
        return api_client.post(
            URL_ADD_ADDITIONAL,
            {
                "model": "purchase",
                "year": YEAR,
                "delivery_week": week,
                "share_article": str(article.id),
                "unit": "KG",
                "size": "M",
                "amount": "2.00",
            },
            format="json",
        )

    def test_add_in_a_read_only_week_is_refused(self, api_client, tenant):
        article = ShareArticleFactory(is_purchased=True)

        _assert_refused(self._add(api_client, article, READ_ONLY_WEEK))
        assert not Purchase.objects.filter(share_article=article).exists()

    def test_add_in_the_grace_week_is_accepted(self, api_client, tenant):
        resp = self._add(api_client, ShareArticleFactory(is_purchased=True), GRACE_WEEK)

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_update_of_a_read_only_week_entry_is_refused(self, api_client, tenant):
        purchase = PurchaseFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)
        url = reverse(
            "documentation_summary-update-additional-theoretical-amount",
            kwargs={"pk": purchase.pk},
        )

        resp = api_client.patch(
            url, {"model": "purchase", "amount": "4.00"}, format="json"
        )

        _assert_refused(resp)


def _forecast_payload(article, week: int) -> dict:
    return {
        "year": YEAR,
        "delivery_week": week,
        "share_article": str(article.id),
        "unit": "KG",
        "size": "M",
        "amount": "5",
        "for_all_harvest_shares": False,
        "for_all_harvest_shares_fruit": False,
    }


@pytest.mark.django_db
class TestForecastPastWeek:
    URL = reverse("forecast-list")

    def test_create_in_a_read_only_week_is_refused(self, api_client, tenant):
        article = ShareArticleFactory()

        resp = api_client.post(
            self.URL, _forecast_payload(article, READ_ONLY_WEEK), format="json"
        )

        _assert_refused(resp)
        assert not Forecast.objects.filter(share_article=article).exists()

    def test_create_in_the_grace_week_is_accepted(self, api_client, tenant):
        resp = api_client.post(
            self.URL,
            _forecast_payload(ShareArticleFactory(), GRACE_WEEK),
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_update_of_a_read_only_week_row_is_refused(self, api_client, tenant):
        forecast = ForecastFactory(year=YEAR, delivery_week=READ_ONLY_WEEK, amount=3)
        url = reverse("forecast-detail", kwargs={"pk": forecast.pk})

        _assert_refused(api_client.patch(url, {"amount": "7"}, format="json"))
        forecast.refresh_from_db()
        assert forecast.amount == 3

    def test_moving_a_row_into_a_read_only_week_is_refused(self, api_client, tenant):
        forecast = ForecastFactory(year=YEAR, delivery_week=GRACE_WEEK)
        url = reverse("forecast-detail", kwargs={"pk": forecast.pk})

        resp = api_client.patch(url, {"delivery_week": READ_ONLY_WEEK}, format="json")

        _assert_refused(resp)
        forecast.refresh_from_db()
        assert forecast.delivery_week == GRACE_WEEK

    def test_update_in_the_grace_week_is_accepted(self, api_client, tenant):
        forecast = ForecastFactory(year=YEAR, delivery_week=GRACE_WEEK, amount=3)
        url = reverse("forecast-detail", kwargs={"pk": forecast.pk})

        # The forecast service rebuilds the variation rows from the body's week,
        # so the body names it as the page's row save does.
        resp = api_client.patch(
            url,
            {"year": YEAR, "delivery_week": GRACE_WEEK, "amount": "7"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data

    def test_delete_of_a_read_only_week_row_is_refused(self, api_client, tenant):
        forecast = ForecastFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)
        url = reverse("forecast-detail", kwargs={"pk": forecast.pk})

        _assert_refused(api_client.delete(url))
        assert Forecast.objects.filter(pk=forecast.pk).exists()

    def test_delete_in_the_grace_week_is_accepted(self, api_client, tenant):
        forecast = ForecastFactory(year=YEAR, delivery_week=GRACE_WEEK)
        url = reverse("forecast-detail", kwargs={"pk": forecast.pk})

        resp = api_client.delete(url)

        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not Forecast.objects.filter(pk=forecast.pk).exists()


@pytest.mark.django_db
class TestForecastBulkPastWeek:
    def test_copy_into_a_read_only_week_is_a_per_item_error(self, api_client, tenant):
        """The copy writes the next week, so a forecast whose next week is
        read-only is named in ``errors`` while one whose next week is writable is
        still copied."""
        into_read_only = ForecastFactory(year=YEAR, delivery_week=READ_ONLY_WEEK - 1)
        into_grace = ForecastFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)

        resp = api_client.post(
            reverse("forecast-bulk-copy-to-next-week"),
            {"ids": [str(into_read_only.id), str(into_grace.id)]},
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        [error] = resp.data["errors"]
        assert error["id"] == str(into_read_only.id)
        assert error["code"] == "commissioning.past_week"
        assert not Forecast.objects.filter(
            share_article=into_read_only.share_article, delivery_week=READ_ONLY_WEEK
        ).exists()
        assert Forecast.objects.filter(
            share_article=into_grace.share_article, delivery_week=GRACE_WEEK
        ).exists()

    def test_finalize_in_a_read_only_week_is_a_per_item_error(self, api_client, tenant):
        read_only = ForecastFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)
        grace = ForecastFactory(year=YEAR, delivery_week=GRACE_WEEK)

        resp = api_client.post(
            reverse("bulk_finalize"),
            {
                "model": "forecast",
                "app_label": "commissioning",
                "ids": [str(read_only.id), str(grace.id)],
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_207_MULTI_STATUS, resp.data
        assert resp.data["finalized_count"] == 1
        [error] = resp.data["errors"]
        assert error["id"] == str(read_only.id)
        assert error["code"] == "commissioning.past_week"
        read_only.refresh_from_db()
        grace.refresh_from_db()
        assert read_only.is_finalized is False
        assert grace.is_finalized is True

    def test_unfinalize_in_a_read_only_week_is_refused(self, api_client, tenant):
        read_only = ForecastFactory(
            year=YEAR, delivery_week=READ_ONLY_WEEK, is_finalized=True
        )
        grace = ForecastFactory(year=YEAR, delivery_week=GRACE_WEEK, is_finalized=True)

        resp = api_client.post(
            reverse("bulk_unfinalize"),
            {
                "model": "forecast",
                "app_label": "commissioning",
                "ids": [str(read_only.id), str(grace.id)],
            },
            format="json",
        )

        _assert_refused(resp)
        read_only.refresh_from_db()
        grace.refresh_from_db()
        assert read_only.is_finalized is True
        assert grace.is_finalized is True

    def test_unfinalize_in_the_grace_week_is_accepted(self, api_client, tenant):
        grace = ForecastFactory(year=YEAR, delivery_week=GRACE_WEEK, is_finalized=True)

        resp = api_client.post(
            reverse("bulk_unfinalize"),
            {"model": "forecast", "app_label": "commissioning", "ids": [str(grace.id)]},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        grace.refresh_from_db()
        assert grace.is_finalized is False


@pytest.mark.django_db
class TestHarvestBulkFinalizePastWeek:
    @staticmethod
    def _post(api_client, url_name: str, *harvests):
        return api_client.post(
            reverse(url_name),
            {
                "model": "harvest",
                "app_label": "commissioning",
                "ids": [str(harvest.id) for harvest in harvests],
            },
            format="json",
        )

    def test_finalize_in_a_read_only_week_is_a_per_item_error(self, api_client, tenant):
        read_only = HarvestFactory(year=YEAR, delivery_week=READ_ONLY_WEEK)
        grace = HarvestFactory(year=YEAR, delivery_week=GRACE_WEEK)

        resp = self._post(api_client, "bulk_finalize", read_only, grace)

        assert resp.status_code == status.HTTP_207_MULTI_STATUS, resp.data
        assert resp.data["finalized_count"] == 1
        [error] = resp.data["errors"]
        assert error["id"] == str(read_only.id)
        assert error["code"] == "commissioning.past_week"
        read_only.refresh_from_db()
        grace.refresh_from_db()
        assert read_only.is_finalized is False
        assert grace.is_finalized is True

    def test_unfinalize_in_a_read_only_week_is_refused(self, api_client, tenant):
        read_only = HarvestFactory(
            year=YEAR, delivery_week=READ_ONLY_WEEK, is_finalized=True
        )
        grace = HarvestFactory(year=YEAR, delivery_week=GRACE_WEEK, is_finalized=True)

        resp = self._post(api_client, "bulk_unfinalize", read_only, grace)

        _assert_refused(resp)
        read_only.refresh_from_db()
        grace.refresh_from_db()
        assert read_only.is_finalized is True
        assert grace.is_finalized is True

    def test_unfinalize_in_the_grace_week_is_accepted(self, api_client, tenant):
        grace = HarvestFactory(year=YEAR, delivery_week=GRACE_WEEK, is_finalized=True)

        resp = self._post(api_client, "bulk_unfinalize", grace)

        assert resp.status_code == status.HTTP_200_OK, resp.data
        grace.refresh_from_db()
        assert grace.is_finalized is False
