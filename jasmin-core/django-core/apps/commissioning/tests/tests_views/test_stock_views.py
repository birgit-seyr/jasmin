"""Tests for stock_views.py — CurrentStockComparisonView, StorageLoggingView, bulk ops."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import MovementShareArticle
from apps.commissioning.models.choices_text import MovementTypeOptions
from apps.commissioning.services.snapshot_service import SnapshotService
from apps.commissioning.tests.factories import (
    HarvestFactory,
    MovementShareArticleFactory,
    ShareArticleFactory,
    StorageFactory,
)
from apps.commissioning.utils import build_composite_id

URL_STOCK = reverse("current_stock_comparison")
URL_BULK_FINALIZE = reverse("bulk_finalize_current_stock")
URL_BULK_EXPECTED = reverse("bulk_set_as_expected_current_stock")
URL_BULK_ZERO = reverse("bulk_set_to_zero_current_stock")
URL_STORAGE_LOGGING = reverse("storage_logging")


def _make_composite_id(article, unit, size, storage, year=2026, week=15, day_number=1):
    return build_composite_id(
        str(article.id), unit, size, str(storage.id), year, week, day_number
    )


def _seed_theoretical_stock(article, storage, amount):
    """A real HARVEST movement dated well before the queried week, so the entity
    has a theoretical_current_stock of ``amount`` for the bulk actions to act on."""
    harvest = HarvestFactory(share_article=article, storage=storage)
    return MovementShareArticleFactory(
        share_article=article,
        storage=storage,
        harvest=harvest,
        unit="KG",
        size="M",
        movement_type=MovementTypeOptions.HARVEST,
        amount=Decimal(str(amount)),
        date=datetime.datetime(2026, 1, 5, 12, tzinfo=datetime.UTC),
    )


def _inventory_for(article, storage):
    return MovementShareArticle.objects.get(
        movement_type=MovementTypeOptions.INVENTORY,
        share_article=article,
        storage=storage,
        unit="KG",
        size="M",
    )


def _balance(article, storage):
    """Projected running balance after a bulk action (well after the inventory)."""
    return SnapshotService.compute_balance(
        str(article.id),
        "KG",
        "M",
        str(storage.id),
        up_to=datetime.datetime(2026, 12, 31, tzinfo=datetime.UTC),
    )


# ---------------------------------------------------------------------------
# CurrentStockComparisonView — GET
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCurrentStockComparisonGet:
    def test_returns_stock_data(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        harvest = HarvestFactory(share_article=article, storage=storage)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            harvest=harvest,
            unit="KG",
            size="M",
            amount=Decimal("50"),
        )

        resp = api_client.get(
            URL_STOCK, {"year": 2026, "delivery_week": 15, "day_number": 1}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)

    def test_empty_for_no_movements(self, api_client, tenant):
        resp = api_client.get(
            URL_STOCK, {"year": 2026, "delivery_week": 15, "day_number": 1}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_missing_params_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_STOCK, {"year": 2026})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_filters_by_storage(self, api_client, tenant):
        article = ShareArticleFactory()
        s1 = StorageFactory()
        s2 = StorageFactory()
        h1 = HarvestFactory(share_article=article, storage=s1)
        h2 = HarvestFactory(share_article=article, storage=s2)
        MovementShareArticleFactory(
            share_article=article,
            storage=s1,
            harvest=h1,
            unit="KG",
            size="M",
            amount=Decimal("30"),
        )
        MovementShareArticleFactory(
            share_article=article,
            storage=s2,
            harvest=h2,
            unit="KG",
            size="M",
            amount=Decimal("20"),
        )

        resp = api_client.get(
            URL_STOCK,
            {"year": 2026, "delivery_week": 15, "day_number": 1, "storage": str(s1.id)},
        )
        assert resp.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# CurrentStockComparisonView — PATCH (create/update inventory)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCurrentStockComparisonPatch:
    def test_creates_inventory(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        resp = api_client.patch(url, {"amount": 100}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["amount"] == 100

    def test_updates_existing_inventory(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        # Create first
        resp1 = api_client.patch(url, {"amount": 50}, format="json")
        assert resp1.status_code == status.HTTP_201_CREATED

        # Update
        resp2 = api_client.patch(url, {"amount": 75}, format="json")
        assert resp2.status_code == status.HTTP_200_OK
        assert resp2.data["amount"] == 75

    def test_lost_inventory_race_converges_to_update(
        self, api_client, tenant, monkeypatch
    ):
        """TXN-4: when the existing-lookup misses but the INSERT then loses the
        one-inventory-per-entity-day race (a concurrent writer created the row
        first), the PATCH converges to an update of the winner (200 + our count)
        instead of returning a bare 409 that discards the office's count."""
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        # The "concurrent winner": a real INVENTORY row that already committed.
        assert (
            api_client.patch(url, {"amount": 40}, format="json").status_code
            == status.HTTP_201_CREATED
        )

        # Force the NEXT existing-lookup to miss (as if our SELECT ran before the
        # concurrent INSERT committed), so the view retries via the create branch
        # and hits the REAL unique constraint — exercising the lost-race path.
        real_select_for_update = MovementShareArticle.objects.select_for_update
        state = {"miss_next": True}

        class _MissOnce:
            def __init__(self, queryset):
                self._queryset = queryset

            def filter(self, *args, **kwargs):
                return _MissOnce(self._queryset.filter(*args, **kwargs))

            def order_by(self, *args, **kwargs):
                return _MissOnce(self._queryset.order_by(*args, **kwargs))

            def first(self):
                if state["miss_next"]:
                    state["miss_next"] = False
                    return None
                return self._queryset.first()

        monkeypatch.setattr(
            MovementShareArticle.objects,
            "select_for_update",
            lambda *args, **kwargs: _MissOnce(real_select_for_update(*args, **kwargs)),
        )

        resp = api_client.patch(url, {"amount": 100}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["amount"] == 100
        # Exactly one INVENTORY row survives — the winner, converged to our count.
        assert _inventory_for(article, storage).counted_amount == Decimal("100.000")

    def test_invalid_composite_id_returns_400(self, api_client, tenant):
        url = reverse("current_stock_comparison_detail", args=["bad_id"])
        resp = api_client.patch(url, {"amount": 1}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_negative_amount_returns_400(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        resp = api_client.patch(url, {"amount": -5}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_metadata_only_patch_preserves_theoretical_stock(self, api_client, tenant):
        """goods-flow audit #2: a PATCH with only a flag (no ``amount``) on an
        entity that has theoretical stock and no prior count must NOT zero it.
        Before the fix it wrote a ``0 − theoretical`` correction → stock read 0.
        Now it records a metadata-only row (counted_amount=None, zero delta)."""
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        resp = api_client.patch(url, {"washed": True}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["amount"] is None  # no phantom count in the response
        assert resp.data["washed"] is True

        inv = _inventory_for(article, storage)
        assert inv.counted_amount is None  # "not counted yet"
        assert inv.amount == Decimal("0")  # zero delta — theoretical intact
        assert inv.washed is True
        # The theoretical stock is preserved (50), not zeroed.
        assert _balance(article, storage) == Decimal("50")

    def test_amount_patch_still_corrects_stock(self, api_client, tenant):
        """Regression: a PATCH WITH an amount still nets counted − theoretical."""
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        resp = api_client.patch(url, {"amount": 30}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["amount"] == 30

        inv = _inventory_for(article, storage)
        assert inv.counted_amount == Decimal("30.000")
        assert inv.amount == Decimal("-20.000")  # 30 − 50
        assert _balance(article, storage) == Decimal("30")

    def test_metadata_only_patch_keeps_existing_count(self, api_client, tenant):
        """A flag-only PATCH on an already-counted entity toggles the flag but
        leaves the count and balance untouched."""
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        assert (
            api_client.patch(url, {"amount": 40}, format="json").status_code
            == status.HTTP_201_CREATED
        )
        resp = api_client.patch(url, {"washed": True}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["amount"] == 40  # existing count still reported
        assert resp.data["washed"] is True

        inv = _inventory_for(article, storage)
        assert inv.counted_amount == Decimal("40.000")  # count preserved
        assert inv.washed is True
        assert _balance(article, storage) == Decimal("40")


# ---------------------------------------------------------------------------
# CurrentStockComparisonView — DELETE
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCurrentStockComparisonDelete:
    def test_deletes_inventory(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        # Create first
        api_client.patch(url, {"amount": 50}, format="json")
        # Delete
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_nonexistent_returns_404(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)
        url = reverse("current_stock_comparison_detail", args=[cid])

        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Bulk stock operations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkFinalizeCurrentStock:
    def test_no_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_BULK_FINALIZE, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_finalizes_stock(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        # Seed theoretical stock so finalize actually succeeds (empty errors): an
        # all-success bulk stays HTTP 200 (only partial failure escalates to 207).
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)

        resp = api_client.post(URL_BULK_FINALIZE, {"ids": [cid]}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["errors"] == []
        assert "updated" in resp.data or "created" in resp.data


@pytest.mark.django_db
class TestBulkSetAsExpectedCurrentStock:
    def test_no_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_BULK_EXPECTED, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_creates_inventory_at_theoretical_and_balance_holds(
        self, api_client, tenant
    ):
        # The office confirms the theoretical stock (50) is the real count: an
        # INVENTORY of 50 is recorded with a zero correction, balance unchanged.
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)

        resp = api_client.post(URL_BULK_EXPECTED, {"ids": [cid]}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {"updated": 0, "created": 1, "errors": []}
        inv = _inventory_for(article, storage)
        assert inv.counted_amount == Decimal("50.000")
        assert inv.amount == Decimal("0.000")  # counted == theoretical -> no delta
        assert _balance(article, storage) == Decimal("50")

    def test_missing_theoretical_stock_is_per_item_error(self, api_client, tenant):
        # Unlike set-to-zero, set-as-expected needs a theoretical value; an item
        # with no movements isn't in the theoretical map -> a per-item error.
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)

        resp = api_client.post(URL_BULK_EXPECTED, {"ids": [cid]}, format="json")

        # REF-1: a per-item error escalates the bulk response to 207.
        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert resp.data["created"] == 0
        assert resp.data["updated"] == 0
        assert len(resp.data["errors"]) == 1
        assert "not found" in resp.data["errors"][0]["error"].lower()
        assert not MovementShareArticle.objects.filter(
            movement_type=MovementTypeOptions.INVENTORY, share_article=article
        ).exists()

    def test_existing_real_inventory_is_left_untouched(self, api_client, tenant):
        # set-as-expected only fills entries with a null amount; a real prior
        # count (70) must survive unchanged.
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)
        detail_url = reverse("current_stock_comparison_detail", args=[cid])
        api_client.patch(detail_url, {"amount": 70}, format="json")  # real count

        resp = api_client.post(URL_BULK_EXPECTED, {"ids": [cid]}, format="json")

        assert resp.data == {"updated": 0, "created": 0, "errors": []}
        assert _inventory_for(article, storage).counted_amount == Decimal("70.000")
        assert _balance(article, storage) == Decimal("70")

    def test_multiple_entities_each_set_to_its_own_theoretical(
        self, api_client, tenant
    ):
        storage = StorageFactory()
        art1 = ShareArticleFactory()
        art2 = ShareArticleFactory()
        _seed_theoretical_stock(art1, storage, 12)
        _seed_theoretical_stock(art2, storage, 8)
        ids = [
            _make_composite_id(art1, "KG", "M", storage),
            _make_composite_id(art2, "KG", "M", storage),
        ]

        resp = api_client.post(URL_BULK_EXPECTED, {"ids": ids}, format="json")

        assert resp.data["created"] == 2
        assert resp.data["errors"] == []
        assert _inventory_for(art1, storage).counted_amount == Decimal("12.000")
        assert _inventory_for(art2, storage).counted_amount == Decimal("8.000")
        assert _balance(art1, storage) == Decimal("12")
        assert _balance(art2, storage) == Decimal("8")


@pytest.mark.django_db
class TestBulkSetToZeroCurrentStock:
    def test_no_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_BULK_ZERO, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_creates_zero_inventory_and_balance_drops_to_zero(self, api_client, tenant):
        # The office found nothing on hand for an item that theoretically has 50.
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 50)
        cid = _make_composite_id(article, "KG", "M", storage)

        resp = api_client.post(URL_BULK_ZERO, {"ids": [cid]}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {"updated": 0, "created": 1, "errors": []}
        inv = _inventory_for(article, storage)
        assert inv.counted_amount == Decimal("0")
        assert inv.amount == Decimal("-50.000")  # correction delta: 0 - 50
        assert _balance(article, storage) == Decimal("0")

    def test_works_without_theoretical_stock(self, api_client, tenant):
        # set-to-zero does NOT need a theoretical value (unlike set-as-expected):
        # an item with no movements just gets a 0-count inventory.
        article = ShareArticleFactory()
        storage = StorageFactory()
        cid = _make_composite_id(article, "KG", "M", storage)

        resp = api_client.post(URL_BULK_ZERO, {"ids": [cid]}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == 1
        assert _inventory_for(article, storage).counted_amount == Decimal("0")
        assert _balance(article, storage) == Decimal("0")

    def test_multiple_entities_all_zeroed(self, api_client, tenant):
        storage = StorageFactory()
        art1 = ShareArticleFactory()
        art2 = ShareArticleFactory()
        _seed_theoretical_stock(art1, storage, 30)
        _seed_theoretical_stock(art2, storage, 20)
        ids = [
            _make_composite_id(art1, "KG", "M", storage),
            _make_composite_id(art2, "KG", "M", storage),
        ]

        resp = api_client.post(URL_BULK_ZERO, {"ids": ids}, format="json")

        assert resp.data["created"] == 2
        assert resp.data["errors"] == []
        assert _balance(art1, storage) == Decimal("0")
        assert _balance(art2, storage) == Decimal("0")

    def test_rerun_is_a_noop_no_duplicate_inventory(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 40)
        cid = _make_composite_id(article, "KG", "M", storage)

        first = api_client.post(URL_BULK_ZERO, {"ids": [cid]}, format="json")
        assert first.data["created"] == 1
        second = api_client.post(URL_BULK_ZERO, {"ids": [cid]}, format="json")

        # The day's inventory already exists with a real (non-null) amount, so the
        # second call neither creates nor updates — and there's still just one row.
        assert second.data == {"updated": 0, "created": 0, "errors": []}
        assert (
            MovementShareArticle.objects.filter(
                movement_type=MovementTypeOptions.INVENTORY, share_article=article
            ).count()
            == 1
        )
        assert _balance(article, storage) == Decimal("0")

    def test_invalid_id_collected_in_errors_others_succeed(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        _seed_theoretical_stock(article, storage, 10)
        good = _make_composite_id(article, "KG", "M", storage)

        resp = api_client.post(
            URL_BULK_ZERO, {"ids": [good, "not-a-valid-id"]}, format="json"
        )

        # REF-1: one valid + one invalid → partial failure → 207.
        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert resp.data["created"] == 1  # the good one still went through
        assert len(resp.data["errors"]) == 1
        assert resp.data["errors"][0]["id"] == "not-a-valid-id"


# ---------------------------------------------------------------------------
# StorageLoggingView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStorageLoggingView:
    def test_returns_events(self, api_client, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        harvest = HarvestFactory(share_article=article, storage=storage)
        MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            harvest=harvest,
            unit="KG",
            size="M",
            amount=Decimal("10"),
        )

        resp = api_client.get(URL_STORAGE_LOGGING, {"storage": str(storage.id)})
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)
        assert len(resp.data) >= 1

    def test_missing_storage_returns_error(self, api_client, tenant):
        resp = api_client.get(URL_STORAGE_LOGGING)
        # Storage param is required — the view returns 404 for missing storage
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
        )

    def test_filters_by_share_article(self, api_client, tenant):
        a1 = ShareArticleFactory()
        a2 = ShareArticleFactory()
        storage = StorageFactory()
        h1 = HarvestFactory(share_article=a1, storage=storage)
        h2 = HarvestFactory(share_article=a2, storage=storage)
        MovementShareArticleFactory(
            share_article=a1,
            storage=storage,
            harvest=h1,
            unit="KG",
            size="M",
            amount=Decimal("10"),
        )
        MovementShareArticleFactory(
            share_article=a2,
            storage=storage,
            harvest=h2,
            unit="KG",
            size="M",
            amount=Decimal("20"),
        )

        resp = api_client.get(
            URL_STORAGE_LOGGING,
            {"storage": str(storage.id), "share_article": str(a1.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        article_ids = {item["share_article"] for item in resp.data}
        assert str(a2.id) not in article_ids

    def test_filters_by_date_range(self, api_client, tenant):
        storage = StorageFactory()
        resp = api_client.get(
            URL_STORAGE_LOGGING,
            {
                "storage": str(storage.id),
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
            },
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_invalid_date_returns_400(self, api_client, tenant):
        storage = StorageFactory()
        resp = api_client.get(
            URL_STORAGE_LOGGING,
            {"storage": str(storage.id), "start_date": "bad-date"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_storage_returns_404(self, api_client, tenant):
        resp = api_client.get(
            URL_STORAGE_LOGGING,
            {"storage": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_running_balance_accumulates_exactly(self, api_client, tenant):
        # The running balance must accumulate in Decimal end-to-end (amounts are
        # DecimalField); float() only at the per-row wire boundary. This locks
        # the cumulative math for a multi-movement ledger (the other tests assert
        # only status/shape, never the running_balance value).
        article = ShareArticleFactory()
        storage = StorageFactory()
        harvest = HarvestFactory(share_article=article, storage=storage)
        movements = [
            (datetime.datetime(2026, 3, 2, 12, tzinfo=datetime.UTC), Decimal("10.500")),
            (datetime.datetime(2026, 3, 3, 12, tzinfo=datetime.UTC), Decimal("0.200")),
            (datetime.datetime(2026, 3, 4, 12, tzinfo=datetime.UTC), Decimal("0.300")),
        ]
        for when, amount in movements:
            MovementShareArticleFactory(
                share_article=article,
                storage=storage,
                harvest=harvest,
                unit="KG",
                size="M",
                movement_type=MovementTypeOptions.HARVEST,
                amount=amount,
                date=when,
            )

        resp = api_client.get(
            URL_STORAGE_LOGGING,
            {
                "storage": str(storage.id),
                "share_article": str(article.id),
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        # Newest-first; ascending running balance was 10.5 -> 10.7 -> 11.0.
        assert [row["running_balance"] for row in resp.data] == [11.0, 10.7, 10.5]
        # amount stays a JSON number on the wire (floated only at the boundary).
        assert [row["amount"] for row in resp.data] == [0.3, 0.2, 10.5]
