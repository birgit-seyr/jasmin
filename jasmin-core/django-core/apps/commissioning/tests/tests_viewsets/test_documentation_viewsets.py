"""Tests for documentation_viewsets.py — Plot, Forecast, Waste, Purchase, Harvest."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import Harvest, Purchase
from apps.commissioning.tests.factories import (
    ForecastFactory,
    HarvestFactory,
    MovementShareArticleFactory,
    PlotFactory,
    PurchaseFactory,
    ShareArticleFactory,
    StorageFactory,
    WasteFactory,
)


# ---------------------------------------------------------------------------
# PlotViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPlotViewSet:
    URL = reverse("plots-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_plots(self, api_client, tenant):
        PlotFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1

    def test_filter_is_active(self, api_client, tenant):
        PlotFactory(is_active=True)
        PlotFactory(is_active=False)
        resp = api_client.get(self.URL, {"is_active": "true"})
        for p in resp.data:
            assert p["is_active"] is True

    def test_create_plot(self, api_client, tenant):
        resp = api_client.post(
            self.URL, {"name": "Field A", "is_active": True}, format="json"
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def test_retrieve_plot(self, api_client, tenant):
        plot = PlotFactory()
        url = reverse("plots-detail", kwargs={"pk": plot.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK

    def test_delete_plot(self, api_client, tenant):
        plot = PlotFactory()
        url = reverse("plots-detail", kwargs={"pk": plot.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT


# ---------------------------------------------------------------------------
# WasteViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestWasteViewSet:
    URL = reverse("waste-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_waste(self, api_client, tenant):
        WasteFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# HarvestViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHarvestViewSet:
    URL = reverse("harvest-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_harvests(self, api_client, tenant):
        HarvestFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# PurchaseViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPurchaseViewSet:
    URL = reverse("purchase-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK

    def test_list_returns_purchases(self, api_client, tenant):
        PurchaseFactory()
        resp = api_client.get(self.URL)
        assert len(resp.data) >= 1


# ---------------------------------------------------------------------------
# ForecastViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestForecastViewSet:
    URL = reverse("forecast-list")

    def test_list_requires_year_and_week(self, api_client, tenant):
        # year + delivery_week are required query params (matches the schema);
        # omitting them no longer falls through to an unprefetched list of all
        # forecasts.
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_empty_for_week_without_forecasts(self, api_client, tenant):
        resp = api_client.get(self.URL, {"year": 2099, "delivery_week": 1})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_forecasts(self, api_client, tenant):
        ForecastFactory(year=2026, delivery_week=15)
        resp = api_client.get(self.URL, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) >= 1

    def test_filter_by_year_and_week(self, api_client, tenant):
        _fc = ForecastFactory(year=2026, delivery_week=15)
        resp = api_client.get(self.URL, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# ForecastViewSet — bad variation_<id> key → 404 (not a 500)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestForecastInvalidVariation:
    """A non-existent ``variation_<id>`` key must surface as a stable 404
    (``share_type_variation.not_found``), not an opaque 500. The service used
    to raise a bare ValueError mid-transaction, which the global handler
    rendered as a generic internal error."""

    URL = reverse("forecast-list")

    def test_create_with_unknown_variation_returns_404(self, api_client, tenant):
        article = ShareArticleFactory()
        resp = api_client.post(
            self.URL,
            {
                "year": 2026,
                "delivery_week": 15,
                "share_article": str(article.id),
                "unit": "KG",
                "size": "M",
                # explicit-id path, not the "for all" bulk-add branch
                "for_all_harvest_shares": False,
                "for_all_harvest_shares_fruit": False,
                "variation_nonexistent-id": True,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "share_type_variation.not_found"

    def test_update_with_unknown_variation_returns_404(self, api_client, tenant):
        forecast = ForecastFactory(year=2026, delivery_week=15)
        url = reverse("forecast-detail", kwargs={"pk": forecast.pk})
        resp = api_client.patch(
            url,
            {
                "for_all_harvest_shares": False,
                "for_all_harvest_shares_fruit": False,
                "variation_nonexistent-id": True,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "share_type_variation.not_found"


# ---------------------------------------------------------------------------
# ForecastViewSet — bulk_copy_to_next_week @action
# ---------------------------------------------------------------------------
URL_FORECAST_BULK_COPY = reverse("forecast-bulk-copy-to-next-week")


@pytest.mark.django_db
class TestForecastBulkCopyToNextWeek:
    def test_empty_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_FORECAST_BULK_COPY, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_ids_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_FORECAST_BULK_COPY,
            {"ids": ["nonexistent-id"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_copies_existing_forecast(self, api_client, tenant):
        fc = ForecastFactory(year=2026, delivery_week=15)
        resp = api_client.post(
            URL_FORECAST_BULK_COPY,
            {"ids": [str(fc.id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data == {"success": True}


# ---------------------------------------------------------------------------
# PurchaseViewSet / HarvestViewSet — bulk_set_as_expected + export_csv @actions
# ---------------------------------------------------------------------------
URL_PURCHASE_BULK_SET_EXPECTED = reverse("purchase-bulk-set-as-expected")
URL_PURCHASE_EXPORT_CSV = reverse("purchase-export-csv")
URL_HARVEST_BULK_SET_EXPECTED = reverse("harvest-bulk-set-as-expected")
URL_HARVEST_EXPORT_CSV = reverse("harvest-export-csv")


@pytest.mark.django_db
class TestPurchaseExportCsv:
    def test_missing_dates_returns_400(self, api_client, tenant):
        """``_csv_export_response`` validates date_from / date_to params."""
        resp = api_client.get(URL_PURCHASE_EXPORT_CSV)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_range_returns_csv(self, api_client, tenant):
        resp = api_client.get(
            URL_PURCHASE_EXPORT_CSV,
            {"date_from": "2099-01-01", "date_to": "2099-01-31"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "text/csv" in resp["Content-Type"]


@pytest.mark.django_db
class TestHarvestExportCsv:
    def test_empty_range_returns_csv(self, api_client, tenant):
        resp = api_client.get(
            URL_HARVEST_EXPORT_CSV,
            {"date_from": "2099-01-01", "date_to": "2099-01-31"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "text/csv" in resp["Content-Type"]


@pytest.mark.django_db
class TestBulkSetAsExpected:
    def test_purchase_empty_body_does_not_500(self, api_client, tenant):
        """Service tolerates empty payload (no theoretical rows to flip)."""
        resp = api_client.post(
            URL_PURCHASE_BULK_SET_EXPECTED, {"ids": []}, format="json"
        )
        # Service may return 204 (no content) or 200, but not 500.
        assert resp.status_code < 500

    def test_harvest_empty_body_does_not_500(self, api_client, tenant):
        resp = api_client.post(
            URL_HARVEST_BULK_SET_EXPECTED, {"ids": []}, format="json"
        )
        assert resp.status_code < 500

    def test_harvest_valid_payload_creates_harvest(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        payload = {
            "selectedData": [
                {
                    "id": str(article.id),
                    "year": 2026,
                    "delivery_week": 15,
                    "day_number": 1,
                    "theoretical_harvest_amount": 12.5,
                    "theoretical_harvest_unit": "KG",
                    "theoretical_harvest_size": "M",
                    "storage": str(storage.id),
                }
            ],
        }
        resp = api_client.post(URL_HARVEST_BULK_SET_EXPECTED, payload, format="json")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        harvest = Harvest.objects.get(
            year=2026,
            delivery_week=15,
            day_number=1,
            share_article_id=article.id,
            unit="KG",
            size="M",
            storage=storage,
        )
        assert float(harvest.amount) == 12.5

    def test_purchase_valid_payload_creates_purchase(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        payload = {
            "selectedData": [
                {
                    "id": str(article.id),
                    "year": 2026,
                    "delivery_week": 15,
                    "theoretical_purchase_amount": 8.0,
                    "theoretical_purchase_unit": "KG",
                    "theoretical_purchase_size": "M",
                    "storage": str(storage.id),
                }
            ],
        }
        resp = api_client.post(URL_PURCHASE_BULK_SET_EXPECTED, payload, format="json")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        purchase = Purchase.objects.get(
            year=2026,
            delivery_week=15,
            share_article_id=article.id,
            unit="KG",
            size="M",
            storage=storage,
        )
        assert float(purchase.amount) == 8.0

    def test_harvest_malformed_item_returns_400(self, api_client, tenant):
        # Non-numeric amount → the now-wired serializer.is_valid rejects the
        # request before the service runs.
        bad = {
            "selectedData": [
                {
                    "id": "x",
                    "year": 2026,
                    "delivery_week": 15,
                    "day_number": 1,
                    "theoretical_harvest_amount": "not-a-number",
                    "theoretical_harvest_unit": "KG",
                    "theoretical_harvest_size": "M",
                    "storage": "y",
                }
            ],
        }
        resp = api_client.post(URL_HARVEST_BULK_SET_EXPECTED, bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_purchase_malformed_item_returns_400(self, api_client, tenant):
        bad = {
            "selectedData": [
                {
                    "id": "x",
                    "year": 2026,
                    "delivery_week": 15,
                    "theoretical_purchase_amount": "abc",
                    "theoretical_purchase_unit": "KG",
                    "theoretical_purchase_size": "M",
                    "storage": "y",
                }
            ],
        }
        resp = api_client.post(URL_PURCHASE_BULK_SET_EXPECTED, bad, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# DocumentationSummaryViewSet — summary / add_additional / update_additional
# ---------------------------------------------------------------------------
URL_DS_SUMMARY = reverse("documentation_summary-summary")
URL_DS_ADD_ADDITIONAL = reverse(
    "documentation_summary-add-additional-theoretical-amount"
)


@pytest.mark.django_db
class TestDocumentationSummaryAction:
    def test_returns_empty_for_unused_week(self, api_client, tenant):
        resp = api_client.get(
            URL_DS_SUMMARY,
            {"year": 2099, "delivery_week": 1, "model": "harvest"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []


@pytest.mark.django_db
class TestAddAdditionalTheoreticalAmount:
    def test_invalid_model_returns_400(self, api_client, tenant):
        """``model`` must be one of harvest/purchase/washamount/cleanamount."""
        resp = api_client.post(
            URL_DS_ADD_ADDITIONAL,
            {"model": "not-a-real-model"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUpdateAdditionalTheoreticalAmount:
    def test_invalid_model_returns_400(self, api_client, tenant):
        url = reverse(
            "documentation_summary-update-additional-theoretical-amount",
            kwargs={"pk": "anything"},
        )
        resp = api_client.patch(url, {"model": "not-real"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


_CASCADE = (
    "apps.commissioning.services.snapshot_service.SnapshotService.cascade_for_movements"
)


@pytest.mark.django_db
class TestMovementSourceDeleteRecascades:
    """MOV-5: deleting a Harvest/Purchase/Waste cascade-deletes its movement, so
    perform_destroy must re-cascade stock snapshots for the affected entity (the
    plain DRF destroy never recomputes)."""

    @pytest.mark.parametrize(
        "factory,viewset_name,fk",
        [
            (HarvestFactory, "HarvestViewSet", "harvest"),
            (PurchaseFactory, "PurchaseViewSet", "purchase"),
            (WasteFactory, "WasteViewSet", "waste"),
        ],
    )
    def test_delete_recascades_snapshots(self, tenant, factory, viewset_name, fk):
        from apps.commissioning.viewsets import documentation_viewsets

        instance = factory()
        movement = MovementShareArticleFactory(
            share_article=instance.share_article, **{fk: instance}
        )
        viewset_cls = getattr(documentation_viewsets, viewset_name)

        with patch(_CASCADE) as cascade:
            viewset_cls().perform_destroy(instance)

        cascade.assert_called_once()
        captured = list(cascade.call_args[0][0])
        assert any(m.id == movement.id for m in captured)
