"""Tests for DocumentationSummaryService."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commissioning.services.documentation_summary_service import (
    DocumentationSummaryService,
)
from apps.commissioning.tests.factories import (
    AdditionalTheoreticalPurchaseFactory,
    HarvestFactory,
    PurchaseFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareContentFactory,
    StorageFactory,
    TheoreticalHarvestFactory,
    TheoreticalPurchaseFactory,
)


# ---------------------------------------------------------------------------
# _build_base_filter  (pure — no DB side-effects)
# ---------------------------------------------------------------------------
class TestBuildBaseFilter:
    def test_basic_filter(self):
        q = DocumentationSummaryService._build_base_filter(2026, 15)
        # Q object should contain year and delivery_week
        assert "year" in str(q)
        assert "delivery_week" in str(q)

    def test_with_day_and_seller(self):
        q = DocumentationSummaryService._build_base_filter(
            2026, 15, day_number=2, seller=99
        )
        q_str = str(q)
        assert "day" in q_str
        assert "seller" in q_str


# ---------------------------------------------------------------------------
# _calculate_sums
# ---------------------------------------------------------------------------
class TestCalculateSums:
    def _mock_entry(
        self,
        amount,
        share_content=None,
        order_content=None,
        for_share=False,
        for_order=False,
    ):
        from unittest.mock import MagicMock

        entry = MagicMock()
        entry.amount = amount
        entry.share_content = share_content
        entry.order_content = order_content
        entry.for_share_content = for_share
        entry.for_order_content = for_order
        return entry

    def test_harvest_sums(self):
        theo = [
            self._mock_entry(10, share_content="sc1"),
            self._mock_entry(5, order_content="oc1"),
        ]
        addl = [
            self._mock_entry(3, for_share=True),
            self._mock_entry(2, for_order=True),
        ]

        result = DocumentationSummaryService._calculate_sums(theo, addl, "harvest")
        theoretical_sum, additional_sum, t_share, t_order, a_share, a_order = result
        assert theoretical_sum == 15
        assert additional_sum == 5
        assert t_share == 10
        assert t_order == 5
        assert a_share == 3
        assert a_order == 2

    def test_purchase_sums(self):
        theo = [self._mock_entry(20)]
        addl = [self._mock_entry(8)]

        result = DocumentationSummaryService._calculate_sums(theo, addl, "purchase")
        assert result == (20, 8, None, None, None, None)


# ---------------------------------------------------------------------------
# _get_forecast_info
# ---------------------------------------------------------------------------
class TestGetForecastInfo:
    def test_returns_none_for_empty(self):
        assert DocumentationSummaryService._get_forecast_info([]) == (None, None, None)

    def test_extracts_from_first_entry(self):
        from unittest.mock import MagicMock

        entry = MagicMock()
        entry.forecast.bed_number = "B1"
        entry.forecast.note = "test note"
        entry.forecast.plot.name = "Field A"
        result = DocumentationSummaryService._get_forecast_info([entry])
        assert result == ("B1", "test note", "Field A")


# ---------------------------------------------------------------------------
# _calculate_theoretical_stock
# ---------------------------------------------------------------------------
class TestCalculateTheoreticalStock:
    def test_empty_map_returns_zeros(self):
        (
            total,
            share_stock,
            order_stock,
        ) = DocumentationSummaryService._calculate_theoretical_stock(
            1, "KG", "M", None, {}
        )
        assert total == 0
        assert share_stock == 0.0
        assert order_stock == 0.0

    def test_share_only_entry(self):
        stock_map = {
            (1, "KG", "M", None): {
                "current_stock_amount": 50,
                "for_shares": True,
                "for_resellers": False,
            }
        }
        (
            total,
            share_stock,
            order_stock,
        ) = DocumentationSummaryService._calculate_theoretical_stock(
            1, "KG", "M", None, stock_map
        )
        assert total == 50
        assert share_stock == 50
        assert order_stock == 0

    def test_order_only_entry(self):
        stock_map = {
            (1, "KG", "M", None): {
                "current_stock_amount": 30,
                "for_shares": False,
                "for_resellers": True,
            }
        }
        (
            total,
            share_stock,
            order_stock,
        ) = DocumentationSummaryService._calculate_theoretical_stock(
            1, "KG", "M", None, stock_map
        )
        assert total == 30
        assert order_stock == 30
        assert share_stock == 0


# ---------------------------------------------------------------------------
# get_summary (integration-level)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetSummary:
    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_harvest_summary(self, _mock_stock, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        sc = ShareContentFactory(share_article=article)

        _theo = TheoreticalHarvestFactory(
            year=2026,
            delivery_week=15,
            day_number=1,
            share_article=article,
            amount=Decimal("50"),
            storage=storage,
            share_content=sc,
        )
        _harvest = HarvestFactory(
            year=2026,
            delivery_week=15,
            day_number=1,
            share_article=article,
            amount=Decimal("45"),
            storage=storage,
        )

        result = DocumentationSummaryService.get_summary(
            year=2026, delivery_week=15, model="harvest"
        )

        assert len(result) >= 1
        entry = result[0]
        assert entry["share_article"] == article.pk
        assert entry["harvest_amount"] == Decimal("45")

    def test_returns_empty_when_no_actual(self, tenant):
        result = DocumentationSummaryService.get_summary(
            year=2026, delivery_week=99, model="harvest"
        )
        assert result == []

    @patch.object(
        DocumentationSummaryService,
        "_get_theoretical_stock_map",
        return_value={},
    )
    def test_purchase_summary(self, _mock_stock, tenant):
        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)

        TheoreticalPurchaseFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            amount=Decimal("30"),
            storage=storage,
        )
        PurchaseFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            amount=Decimal("28"),
            storage=storage,
            organic_status="organic",
        )

        result = DocumentationSummaryService.get_summary(
            year=2026, delivery_week=15, model="purchase"
        )
        assert len(result) >= 1
        assert result[0]["purchase_amount"] == Decimal("28")
        # The organic status must round-trip through the summary row so the
        # DocumentationPurchase organic column reflects the saved value.
        assert result[0]["organic_status"] == "organic"


# ---------------------------------------------------------------------------
# _get_grouping_key — pure helper, deterministic
# ---------------------------------------------------------------------------
class TestGetGroupingKey:
    def test_key_includes_storage_id_when_present(self):
        from unittest.mock import MagicMock

        entry = MagicMock()
        entry.share_article.id = "art-1"
        entry.unit = "KG"
        entry.size = "M"
        entry.day_number = 1
        entry.storage_id = "stor-1"

        key = DocumentationSummaryService._get_grouping_key(entry)
        assert key == ("art-1", "KG", "M", 1, "stor-1")

    def test_key_falls_back_to_storage_object_when_id_missing(self):
        """Rare path: ``entry`` exposes ``storage`` but no ``storage_id``
        attribute (some annotated querysets). The grouping must still use
        the storage's primary key so rows don't collapse incorrectly."""
        from unittest.mock import MagicMock

        entry = MagicMock(
            spec=["share_article", "unit", "size", "day_number", "storage"]
        )
        entry.share_article.id = "art-2"
        entry.unit = "PCS"
        entry.size = "L"
        entry.day_number = None
        entry.storage.id = "stor-fallback"

        key = DocumentationSummaryService._get_grouping_key(entry)
        assert key[-1] == "stor-fallback"


# ---------------------------------------------------------------------------
# _group_entries — combines theoretical / additional / actual under same key
# ---------------------------------------------------------------------------
class TestGroupEntries:
    """``_group_entries`` is pure: it only reads attributes off each entry
    (``share_article.id`` / ``.name``, ``unit``, ``size``, ``day_number``,
    ``storage_id`` / ``storage.id``). MagicMocks are sufficient and avoid
    the factory-chain TimeBoundMixin overlap that bites real instances.
    """

    @staticmethod
    def _entry(
        *,
        share_article_id,
        share_article_name,
        unit,
        size,
        day_number,
        storage_id,
        **extra,
    ):
        from unittest.mock import MagicMock

        entry = MagicMock()
        entry.share_article.id = share_article_id
        entry.share_article.name = share_article_name
        entry.unit = unit
        entry.size = size
        entry.day_number = day_number
        entry.storage_id = storage_id
        for key, value in extra.items():
            setattr(entry, key, value)
        return entry

    def test_groups_by_share_article_unit_size_day_storage(self):
        """Entries with matching (share_article, unit, size, day, storage)
        end up in the same bucket; entries differing on any key get their
        own bucket."""
        # Bucket 1: one entry from each of the three input lists, all
        # sharing the same grouping key.
        theo_day1 = self._entry(
            share_article_id="art-1",
            share_article_name="Carrot",
            unit="KG",
            size="M",
            day_number=1,
            storage_id="stor-1",
        )
        addl_day1 = self._entry(
            share_article_id="art-1",
            share_article_name="Carrot",
            unit="KG",
            size="M",
            day_number=1,
            storage_id="stor-1",
        )
        actual_day1 = self._entry(
            share_article_id="art-1",
            share_article_name="Carrot",
            unit="KG",
            size="M",
            day_number=1,
            storage_id="stor-1",
        )
        # Bucket 2: same article + storage, different day → separate bucket.
        theo_day2 = self._entry(
            share_article_id="art-1",
            share_article_name="Carrot",
            unit="KG",
            size="M",
            day_number=2,
            storage_id="stor-1",
        )

        grouped = DocumentationSummaryService._group_entries(
            [theo_day1, theo_day2], [addl_day1], [actual_day1]
        )

        assert len(grouped) == 2

        day1_key = ("art-1", "KG", "M", 1, "stor-1")
        bucket = grouped[day1_key]
        assert len(bucket["theoretical_entries"]) == 1
        assert len(bucket["additional_entries"]) == 1
        assert len(bucket["actual_entries"]) == 1
        assert bucket["share_article_id"] == "art-1"
        assert bucket["share_article_name"] == "Carrot"
        assert bucket["unit"] == "KG"
        assert bucket["size"] == "M"

        day2_key = ("art-1", "KG", "M", 2, "stor-1")
        # The other-day bucket has only its theoretical entry — proves the
        # grouping really partitioned by ``day_number``.
        assert len(grouped[day2_key]["theoretical_entries"]) == 1
        assert grouped[day2_key]["additional_entries"] == []
        assert grouped[day2_key]["actual_entries"] == []


# ---------------------------------------------------------------------------
# bulk_set_as_expected / bulk_set_purchase_as_expected
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBulkSetAsExpectedNoOpPaths:
    def test_empty_selected_data_is_noop(self, tenant):
        """No items → service is a no-op returning None without touching the
        DB. The view owns the 204; the service must be safe to call with an
        empty payload."""
        from apps.commissioning.models import Harvest

        result = DocumentationSummaryService.bulk_set_as_expected({"selectedData": []})
        assert result is None
        assert not Harvest.objects.exists()

    def test_missing_key_treated_as_empty(self, tenant):
        """``data.get("selectedData", [])`` — missing key behaves the same
        as empty list; defensive against partial payloads."""
        from apps.commissioning.models import Harvest

        result = DocumentationSummaryService.bulk_set_as_expected({})
        assert result is None
        assert not Harvest.objects.exists()

    def test_purchase_empty_selected_data_is_noop(self, tenant):
        from apps.commissioning.models import Purchase

        result = DocumentationSummaryService.bulk_set_purchase_as_expected(
            {"selectedData": []}
        )
        assert result is None
        assert not Purchase.objects.exists()


@pytest.mark.django_db
class TestBulkSetPurchaseAsExpectedIdempotent:
    """Re-running bulk_set_purchase_as_expected for the same slot must not
    append a second PURCHASE movement (update_or_create returns the existing
    Purchase; there is no DB uniqueness guard on the movement, so a plain
    create would double-count stock). Mirrors the harvest twin's upsert."""

    def _item(self, share_article, storage) -> dict:
        return {
            "year": 2026,
            "delivery_week": 15,
            "id": str(share_article.pk),
            "theoretical_purchase_amount": Decimal("12"),
            "theoretical_purchase_unit": "KG",
            "theoretical_purchase_size": "M",
            "storage": storage.id,
        }

    def test_rerun_does_not_duplicate_purchase_movement(self, tenant):
        from apps.commissioning.models import MovementShareArticle, Purchase

        share_article = ShareArticleFactory()
        storage = StorageFactory()
        item = self._item(share_article, storage)

        DocumentationSummaryService.bulk_set_purchase_as_expected(
            {"selectedData": [item]}
        )
        DocumentationSummaryService.bulk_set_purchase_as_expected(
            {"selectedData": [item]}
        )

        purchase = Purchase.objects.get(
            year=2026,
            delivery_week=15,
            share_article=share_article,
            unit="KG",
            size="M",
            storage=storage,
        )
        assert MovementShareArticle.objects.filter(purchase=purchase).count() == 1


@pytest.mark.django_db
class TestBulkSetAsExpectedNoRelocation:
    """Theoretical objects are short-term-locked (RequiresShortTermStorageMixin)
    and the storage picker is UI-restricted to that storage, so setting
    harvest-as-expected must NOT relocate the TheoreticalHarvest or its movement
    — only upsert the actual Harvest. The old relocation was a
    no-op-or-illegal-write."""

    def _item(self, share_article, storage):
        return {
            "year": 2026,
            "delivery_week": 15,
            "day_number": 1,
            "id": str(share_article.pk),
            "theoretical_harvest_amount": Decimal("12"),
            "theoretical_harvest_unit": "KG",
            "theoretical_harvest_size": "M",
            "storage": storage.id,
        }

    def test_theoretical_and_movement_not_relocated(self, tenant):
        from apps.commissioning.tests.factories import MovementShareArticleFactory

        article = ShareArticleFactory()
        short_term = StorageFactory(is_short_term_harvest_storage=True)
        other = StorageFactory()
        th = TheoreticalHarvestFactory(
            share_article=article,
            delivery_week=15,
            unit="KG",
            size="M",
            storage=short_term,
            share_content=None,
        )
        movement = MovementShareArticleFactory(
            theoretical_harvest=th,
            share_article=article,
            unit="KG",
            size="M",
            is_theoretical=True,
            storage=short_term,
            movement_type="HARVEST",
        )

        # Even with a non-short-term storage in the payload, the theoretical +
        # its movement stay put (only the actual Harvest lands on `other`).
        DocumentationSummaryService.bulk_set_as_expected(
            {"selectedData": [self._item(article, other)]}
        )

        th.refresh_from_db()
        movement.refresh_from_db()
        assert th.storage_id == short_term.id  # NOT relocated
        assert movement.storage_id == short_term.id  # movement untouched


@pytest.mark.django_db
class TestBulkSetPurchaseAssignsPurchaseDay:
    """bulk_set_purchase_as_expected must stamp the actual Purchase with
    PURCHASE_DAY (matching the TheoreticalPurchase), not leave day_number NULL."""

    def test_actual_purchase_gets_purchase_day(self, tenant):
        from apps.commissioning.constants import PURCHASE_DAY
        from apps.commissioning.models import Purchase

        article = ShareArticleFactory()
        storage = StorageFactory()
        DocumentationSummaryService.bulk_set_purchase_as_expected(
            {
                "selectedData": [
                    {
                        "year": 2026,
                        "delivery_week": 15,
                        "id": str(article.pk),
                        "theoretical_purchase_amount": Decimal("12"),
                        "theoretical_purchase_unit": "KG",
                        "theoretical_purchase_size": "M",
                        "storage": storage.id,
                    }
                ]
            }
        )

        purchase = Purchase.objects.get(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )
        assert purchase.day_number == PURCHASE_DAY


# ---------------------------------------------------------------------------
# _get_or_create_actual_instance — used by add_additional_theoretical_amount
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetOrCreateActualInstance:
    def test_creates_when_no_matching_row(self, tenant):
        """No existing actual row with ``amount=None`` → create one."""
        from apps.commissioning.models import Harvest

        sa = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        common = {
            "year": 2026,
            "delivery_week": 15,
            "day_number": 1,
            "share_article": sa,
            "unit": "KG",
            "size": "M",
            "storage": storage,
        }

        before = Harvest.objects.filter(share_article=sa).count()
        instance = DocumentationSummaryService._get_or_create_actual_instance(
            Harvest, common
        )
        after = Harvest.objects.filter(share_article=sa).count()

        assert after == before + 1
        assert instance.amount is None  # placeholder marker
        assert instance.share_article_id == sa.id

    def test_returns_existing_row(self, tenant):
        """If a placeholder row (``amount=None``) already exists for the
        key, reuse it instead of creating a duplicate — caller relies on
        this for idempotent ``add_additional_theoretical_amount`` flows."""
        from apps.commissioning.models import Harvest

        sa = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        existing = HarvestFactory(
            share_article=sa,
            unit="KG",
            size="M",
            day_number=1,
            storage=storage,
            amount=None,
        )
        common = {
            "year": existing.year,
            "delivery_week": existing.delivery_week,
            "day_number": 1,
            "share_article": sa,
            "unit": "KG",
            "size": "M",
            "storage": storage,
        }

        instance = DocumentationSummaryService._get_or_create_actual_instance(
            Harvest, common
        )

        assert instance.pk == existing.pk
        assert Harvest.objects.filter(share_article=sa).count() == 1


# ---------------------------------------------------------------------------
# _update_model_specific_fields — pure-ish, just needs an instance + dict
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateModelSpecificFields:
    def test_harvest_sets_amount_per_pu_and_crate(self, tenant):
        from apps.commissioning.tests.factories import CrateFactory

        crate = CrateFactory()
        sa = ShareArticleFactory()
        harvest = HarvestFactory(share_article=sa)

        DocumentationSummaryService._update_model_specific_fields(
            harvest,
            {"amount_per_pu": 12, "harvesting_crate": str(crate.id)},
            "harvest",
        )

        assert harvest.amount_per_pu == 12
        assert harvest.harvesting_crate_id == crate.id

    def test_purchase_sets_amount_per_pu_no_crate(self, tenant):
        """Purchases have ``amount_per_pu`` but no harvesting_crate concept
        — the field setter must skip the crate branch silently."""
        sa = ShareArticleFactory(is_purchased=True)
        purchase = PurchaseFactory(share_article=sa)

        DocumentationSummaryService._update_model_specific_fields(
            purchase, {"amount_per_pu": 8}, "purchase"
        )

        assert purchase.amount_per_pu == 8
        # No ``harvesting_crate`` attr touched.

    def test_washamount_is_a_no_op(self, tenant):
        """The ``model in ["harvest", "purchase"]`` guard means
        washamount / cleanamount instances must not be mutated."""
        from unittest.mock import MagicMock

        instance = MagicMock()
        instance.amount_per_pu = "untouched"

        DocumentationSummaryService._update_model_specific_fields(
            instance, {"amount_per_pu": 99}, "washamount"
        )
        # Field was NOT set — the value remains whatever was there.
        assert instance.amount_per_pu == "untouched"


@pytest.mark.django_db
class TestUpdateAdditionalPurchaseSellerScoping:
    """MOV-7: update_additional_theoretical_amount must scope the
    AdditionalTheoreticalPurchase upsert by seller (matching the add path), else
    a seller-blind update mutates the wrong seller's row or raises
    MultipleObjectsReturned when several sellers share the other dimensions."""

    def test_update_touches_only_the_matching_seller(self, tenant):
        from apps.commissioning.constants import PURCHASE_DAY

        article = ShareArticleFactory(is_purchased=True)
        storage = StorageFactory(is_short_term_harvest_storage=True)
        seller_a = ResellerFactory()
        seller_b = ResellerFactory()
        common = dict(
            year=2026,
            delivery_week=15,
            day_number=PURCHASE_DAY,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )
        purchase = PurchaseFactory(seller=seller_a, amount=Decimal("5.00"), **common)
        add_a = AdditionalTheoreticalPurchaseFactory(
            seller=seller_a, amount=Decimal("1.00"), **common
        )
        add_b = AdditionalTheoreticalPurchaseFactory(
            seller=seller_b, amount=Decimal("2.00"), **common
        )

        # Must not raise MultipleObjectsReturned and must touch ONLY seller A.
        DocumentationSummaryService.update_additional_theoretical_amount(
            {"amount": "9.00"}, purchase.id, "purchase"
        )

        add_a.refresh_from_db()
        add_b.refresh_from_db()
        assert add_a.amount == Decimal("9.00")
        assert add_b.amount == Decimal("2.00")
