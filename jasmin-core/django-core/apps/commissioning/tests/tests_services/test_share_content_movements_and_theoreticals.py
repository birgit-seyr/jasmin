"""Integration tests: verify that create/update/delete of ShareContent
correctly creates, recreates, or cascade-deletes MovementShareArticle and
theoretical objects (TheoreticalHarvest, TheoreticalPurchase,
TheoreticalWashAmount, TheoreticalCleanAmount).

Unlike test_share_content_service.py these tests do NOT mock out
create_all_theoretical_objects / create_movements.

The subscription-based ``batch_get_physical_variation_totals_for_week``
is patched to return a known total quantity so the tests focus on the
movement / theoretical-object pipeline rather than subscription counting.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commissioning.models import (
    MovementShareArticle,
    ShareContent,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
)
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)

# ── Helpers ──────────────────────────────────────────

TOTALS_PATCH_PATH = (
    "apps.commissioning.services.share_content_service"
    ".batch_get_physical_variation_totals_for_weeks"
)


def _patch_totals(totals):
    """Patch the multi-week totals batch with a fake returning ``totals``
    (the single-week shape the tests build) for every requested week."""
    return patch(
        TOTALS_PATCH_PATH,
        side_effect=lambda physical_variations, year, weeks: {
            week: totals for week in weeks
        },
    )


def _make_totals(share_contents, quantity=3):
    """Build the dict structure that batch_get_physical_variation_totals_for_week returns."""
    basic: dict[tuple, Decimal] = {}
    station: dict[tuple, Decimal] = {}
    for sc in share_contents:
        key_basic = (sc.share.delivery_day_id, sc.share.share_type_variation_id)
        key_station = (
            sc.share.delivery_day_id,
            sc.share.share_type_variation_id,
            sc.delivery_station_id,
        )
        basic[key_basic] = Decimal(str(quantity))
        station[key_station] = Decimal(str(quantity))
    return {"basic": basic, "tour": {}, "station": station}


def _setup_share_content(tenant, *, article=None, forecast=False, **sc_overrides):
    """Create a single ShareContent with required related objects."""
    storage = StorageFactory(is_short_term_harvest_storage=True)
    if article is None:
        article = ShareArticleFactory()
    sdd = SharesDeliveryDayFactory(day_number=2)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=2026, delivery_week=15, delivery_day=sdd, share_type_variation=stv
    )
    station = DeliveryStationFactory()
    DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

    sc_kwargs = dict(
        share=share,
        share_article=article,
        delivery_station=station,
        amount=Decimal("5"),
        unit="KG",
        size="M",
    )
    sc_kwargs.update(sc_overrides)

    if forecast:
        fc = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size=sc_kwargs.get("size", "M"),
            storage=storage,
        )
        sc_kwargs["forecast"] = fc

    sc = ShareContentFactory(**sc_kwargs)
    # Re-fetch with select_related (as the service does)
    sc = ShareContent.objects.select_related(
        "share__share_type_variation",
        "share__delivery_day",
        "share_article",
        "forecast",
        "seller",
    ).get(pk=sc.pk)
    return sc, storage


# ═══════════════════════════════════════════════════════
# CREATE – movements
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentCreateMovements:
    """create_movements should create SHARECONTENT movements."""

    def test_creates_sharecontent_movement(self, tenant):
        sc, storage = _setup_share_content(tenant)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_movements([sc])

        movements = MovementShareArticle.objects.filter(
            share_content=sc, is_theoretical=False
        )
        assert movements.exists(), "Expected at least one non-theoretical movement"
        assert all(m.movement_type == "SHARECONTENT" for m in movements)
        # total amount = 5 * 3 = 15, movement should be -15
        total = sum(m.amount for m in movements)
        assert total == Decimal("-15")

    def test_movement_uses_short_term_storage_when_no_stock(self, tenant):
        sc, storage = _setup_share_content(tenant)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_movements([sc])

        mv = MovementShareArticle.objects.get(share_content=sc, is_theoretical=False)
        assert mv.storage == storage


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalHarvest
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentCreateTheoreticalHarvest:
    def test_creates_theoretical_harvest_when_forecast_exists(self, tenant):
        sc, storage = _setup_share_content(tenant, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        th = TheoreticalHarvest.objects.filter(share_content=sc)
        assert th.exists(), "TheoreticalHarvest should be created when Forecast exists"
        # amount = 5 * 3 = 15 (total_amount_for_shares)
        assert th.first().amount == Decimal("15")
        assert th.first().share_article == sc.share_article

    def test_creates_theoretical_harvest_movement(self, tenant):
        sc, storage = _setup_share_content(tenant, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        th = TheoreticalHarvest.objects.get(share_content=sc)
        mv = MovementShareArticle.objects.filter(
            theoretical_harvest=th, is_theoretical=True
        )
        assert mv.exists(), "Theoretical HARVEST movement should be created"
        assert mv.first().amount == Decimal("10")  # 5 * 2
        assert mv.first().movement_type == "HARVEST"

    def test_no_theoretical_harvest_without_forecast(self, tenant):
        sc, _storage = _setup_share_content(tenant, forecast=False)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert not TheoreticalHarvest.objects.exists()


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalPurchase
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentCreateTheoreticalPurchase:
    def test_creates_theoretical_purchase_for_purchased_article(self, tenant):
        article = ShareArticleFactory(is_purchased=True)
        sc, _storage = _setup_share_content(tenant, article=article)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=4)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        tp = TheoreticalPurchase.objects.filter(share_content=sc)
        assert (
            tp.exists()
        ), "TheoreticalPurchase should be created for purchased article"
        assert tp.first().amount == Decimal("20")  # 5 * 4

    def test_creates_theoretical_purchase_movement(self, tenant):
        article = ShareArticleFactory(is_purchased=True)
        sc, _storage = _setup_share_content(tenant, article=article)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        tp = TheoreticalPurchase.objects.first()
        mv = MovementShareArticle.objects.filter(
            theoretical_purchase=tp, is_theoretical=True
        )
        assert mv.exists(), "Theoretical PURCHASE movement should be created"
        assert mv.first().movement_type == "PURCHASE"
        assert mv.first().amount == Decimal("10")  # 5 * 2

    def test_no_theoretical_purchase_for_non_purchased_article(self, tenant):
        article = ShareArticleFactory(is_purchased=False)
        sc, _storage = _setup_share_content(tenant, article=article)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert not TheoreticalPurchase.objects.exists()


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalWashAmount
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentCreateTheoreticalWashAmount:
    def test_creates_theoretical_wash_when_washing_enabled(self, tenant):
        sc, _storage = _setup_share_content(tenant, washing=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        tw = TheoreticalWashAmount.objects.filter(share_content=sc)
        assert tw.exists(), "TheoreticalWashAmount should be created when washing=True"
        assert tw.first().amount == Decimal("15")  # 5 * 3

    def test_no_theoretical_wash_when_washing_disabled(self, tenant):
        sc, _storage = _setup_share_content(tenant, washing=False)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert not TheoreticalWashAmount.objects.exists()


# ═══════════════════════════════════════════════════════
# CREATE – TheoreticalCleanAmount
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentCreateTheoreticalCleanAmount:
    def test_creates_theoretical_clean_when_cleaning_enabled(self, tenant):
        sc, _storage = _setup_share_content(tenant, cleaning=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        tc = TheoreticalCleanAmount.objects.filter(share_content=sc)
        assert (
            tc.exists()
        ), "TheoreticalCleanAmount should be created when cleaning=True"
        assert tc.first().amount == Decimal("15")  # 5 * 3

    def test_no_theoretical_clean_when_cleaning_disabled(self, tenant):
        sc, _storage = _setup_share_content(tenant, cleaning=False)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert not TheoreticalCleanAmount.objects.exists()


# ═══════════════════════════════════════════════════════
# DELETE – cascade-deletes movements & theoretical objects
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentDeleteCascadesRelatedObjects:
    def test_delete_removes_movements(self, tenant):
        sc, _storage = _setup_share_content(tenant)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_movements([sc])

        assert MovementShareArticle.objects.filter(share_content=sc).exists()

        sc.delete()

        assert not MovementShareArticle.objects.filter(share_content_id=sc.pk).exists()

    def test_delete_removes_theoretical_harvest(self, tenant):
        sc, _storage = _setup_share_content(tenant, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert TheoreticalHarvest.objects.filter(share_content=sc).exists()

        sc.delete()

        assert not TheoreticalHarvest.objects.filter(share_content_id=sc.pk).exists()

    def test_delete_removes_theoretical_purchase(self, tenant):
        article = ShareArticleFactory(is_purchased=True)
        sc, _storage = _setup_share_content(tenant, article=article)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert TheoreticalPurchase.objects.filter(share_content=sc).exists()

        sc.delete()

        assert not TheoreticalPurchase.objects.filter(share_content_id=sc.pk).exists()

    def test_delete_removes_theoretical_wash(self, tenant):
        sc, _storage = _setup_share_content(tenant, washing=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert TheoreticalWashAmount.objects.filter(share_content=sc).exists()

        sc.delete()

        assert not TheoreticalWashAmount.objects.filter(share_content_id=sc.pk).exists()

    def test_delete_removes_theoretical_clean(self, tenant):
        sc, _storage = _setup_share_content(tenant, cleaning=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert TheoreticalCleanAmount.objects.filter(share_content=sc).exists()

        sc.delete()

        assert not TheoreticalCleanAmount.objects.filter(
            share_content_id=sc.pk
        ).exists()

    def test_delete_removes_all_related_at_once(self, tenant):
        """Purchased article with forecast → both harvest and purchase theoreticals."""
        article = ShareArticleFactory(is_purchased=True)
        sc, _storage = _setup_share_content(tenant, article=article, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])
            svc.create_movements([sc])

        assert TheoreticalHarvest.objects.filter(share_content=sc).exists()
        assert TheoreticalPurchase.objects.filter(share_content=sc).exists()
        assert MovementShareArticle.objects.filter(share_content=sc).exists()

        sc.delete()

        assert not TheoreticalHarvest.objects.filter(share_content_id=sc.pk).exists()
        assert not TheoreticalPurchase.objects.filter(share_content_id=sc.pk).exists()
        assert not MovementShareArticle.objects.filter(share_content_id=sc.pk).exists()


# ═══════════════════════════════════════════════════════
# UPDATE (delete-and-recreate) – old objects gone, new ones exist
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestShareContentUpdateRecreatesRelatedObjects:
    """The update flow is delete-old + process_share_planning_data.
    Here we simulate the pattern: create objects, delete ShareContent
    (cascade), create fresh ones and verify new objects exist."""

    def test_recreate_replaces_movements(self, tenant):
        sc, storage = _setup_share_content(tenant)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_movements([sc])

        old_mv_ids = set(
            MovementShareArticle.objects.filter(share_content=sc).values_list(
                "id", flat=True
            )
        )
        assert old_mv_ids

        # Simulate update: delete old ShareContent (cascades), create new
        share = sc.share
        station = sc.delivery_station
        sc.delete()
        assert not MovementShareArticle.objects.filter(id__in=old_mv_ids).exists()

        # Re-create reusing existing share/station to avoid overlapping period errors
        sc2 = ShareContentFactory(
            share=share,
            share_article=ShareArticleFactory(),
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
        )
        sc2 = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
            "seller",
        ).get(pk=sc2.pk)
        totals2 = _make_totals([sc2], quantity=4)
        with _patch_totals(totals2):
            svc.create_movements([sc2])

        new_mvs = MovementShareArticle.objects.filter(
            share_content=sc2, is_theoretical=False
        )
        assert new_mvs.exists()
        total = sum(m.amount for m in new_mvs)
        assert total == Decimal("-20")  # 5 * 4

    def test_recreate_replaces_theoretical_harvest(self, tenant):
        sc, storage = _setup_share_content(tenant, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=2)

        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        old_th_ids = set(
            TheoreticalHarvest.objects.filter(share_content=sc).values_list(
                "id", flat=True
            )
        )
        assert old_th_ids

        # Simulate update: delete old, create new reusing same share/station
        share = sc.share
        station = sc.delivery_station
        sc.delete()
        assert not TheoreticalHarvest.objects.filter(id__in=old_th_ids).exists()

        # Re-create with different quantity, reusing existing objects
        article = ShareArticleFactory()
        fc = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        sc2 = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=fc,
        )
        sc2 = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
            "seller",
        ).get(pk=sc2.pk)
        totals2 = _make_totals([sc2], quantity=5)
        with _patch_totals(totals2):
            svc.create_all_theoretical_objects([sc2])

        new_ths = TheoreticalHarvest.objects.filter(share_content=sc2)
        assert new_ths.exists()
        assert new_ths.first().amount == Decimal("25")  # 5 * 5


# ═══════════════════════════════════════════════════════
# Recompute – single-pass snapshot cascade (advisory-lock ordering)
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestRecomputeSinglePassCascade:
    """The wipe-and-rebuild recompute must run exactly ONE
    ``SnapshotService.cascade_for_movements`` call per transaction.

    The per-entity ``current_balance:*`` advisory locks are acquired inside the
    cascade and held to commit, so multiple cascade passes (theoretical → new
    SHARECONTENT → old) form a concatenation that is not globally sorted — two
    concurrent overlapping recomputes (or a recompute vs. a bulk stock write)
    could then take the shared locks in opposite orders and AB/BA-deadlock.
    ``collect_movements`` defers every intermediate cascade into one sorted
    union pass at the end; this test pins that single-pass property.
    """

    def test_recompute_for_shares_cascades_exactly_once(self, tenant):
        from apps.commissioning.services.snapshot_service import SnapshotService

        sc, storage = _setup_share_content(tenant, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)

        # First rebuild materialises theoreticals + SHARECONTENT movements so
        # the second run has a non-empty old_movements set — the shape that
        # historically produced three separate cascade passes.
        with _patch_totals(totals):
            svc.recompute_for_shares([sc.share_id])
        assert MovementShareArticle.objects.filter(share_content=sc).exists()

        real_cascade = SnapshotService.cascade_for_movements
        with (
            _patch_totals(totals),
            patch.object(
                SnapshotService,
                "cascade_for_movements",
                side_effect=real_cascade,
            ) as cascade_spy,
        ):
            svc.recompute_for_shares([sc.share_id])

        assert cascade_spy.call_count == 1
        # The single union pass must cover BOTH halves: the old (wiped)
        # movements and the newly rebuilt ones.
        cascaded = cascade_spy.call_args.args[0]
        assert len(cascaded) >= 2

    def test_replace_share_planning_empty_payload_cascades_exactly_once(self, tenant):
        from apps.commissioning.services.snapshot_service import SnapshotService

        sc, storage = _setup_share_content(tenant, forecast=True)
        svc = ShareContentService()
        totals = _make_totals([sc], quantity=3)
        with _patch_totals(totals):
            svc.recompute_for_shares([sc.share_id])

        real_cascade = SnapshotService.cascade_for_movements
        with (
            _patch_totals(totals),
            patch.object(
                SnapshotService,
                "cascade_for_movements",
                side_effect=real_cascade,
            ) as cascade_spy,
        ):
            # Empty payload → clear-all branch: nested recompute_shares +
            # old-movement handling must still collapse to one cascade.
            svc.replace_share_planning(
                year=sc.share.year,
                delivery_week=sc.share.delivery_week,
                share_article_id=str(sc.share_article_id),
                unit=sc.unit,
                size=sc.size,
                data={},
            )

        assert cascade_spy.call_count == 1
