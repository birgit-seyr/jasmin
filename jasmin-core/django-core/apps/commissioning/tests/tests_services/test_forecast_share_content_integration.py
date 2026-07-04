"""Integration tests: verify the Forecast ↔ ShareContent FK relationship.

Tested flows:
- Creating a Forecast → ShareContents are created with ``forecast`` FK linked.
- ShareContent with forecast + amount > 0 → TheoreticalHarvest created.
- ShareContent without forecast + amount > 0 → NO TheoreticalHarvest.
- Updating a Forecast → ShareContents keep/re-link the forecast FK.
- Deleting a Forecast → cascade-deletes linked ShareContents.
- Deleting a ShareContent → Forecast is NOT deleted.

``batch_get_physical_variation_totals_for_week`` is patched so tests don't
need full subscription infrastructure.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.models import (
    DefaultShareArticleInShare,
    Forecast,
    MovementShareArticle,
    ShareContent,
    TheoreticalHarvest,
)
from apps.commissioning.services.forecast_service import ForecastService
from apps.commissioning.services.recompute import recompute_shares
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DefaultShareContentFactory,
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    ForecastShareTypeVariationFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
)

# ── Helpers ──────────────────────────────────────────

TOTALS_PATCH = (
    "apps.commissioning.services.share_content_service"
    ".batch_get_physical_variation_totals_for_weeks"
)


def _patch_totals(totals):
    """Patch the multi-week totals batch with a fake returning ``totals``
    (the single-week shape the tests build) for every requested week."""
    return patch(
        TOTALS_PATCH,
        side_effect=lambda physical_variations, year, weeks: {
            week: totals for week in weeks
        },
    )


def _make_totals_for_all(day_ids, stv_ids, station_ids, quantity=3):
    """Build totals dict covering all combinations of day × variation × station."""
    basic = {}
    station = {}
    for did in day_ids:
        for vid in stv_ids:
            basic[(did, vid)] = Decimal(str(quantity))
            for sid in station_ids:
                station[(did, vid, sid)] = Decimal(str(quantity))
    return {"basic": basic, "tour": {}, "station": station}


def _forecast_data(article, stv, *, year=2026, delivery_week=15, size="M", unit="KG"):
    """Build validated_data dict suitable for ForecastService.create_forecast_with_related_objects."""
    return {
        "year": year,
        "delivery_week": delivery_week,
        "share_article": article,
        "unit": unit,
        "size": size,
        "amount": 100,
        f"variation_{stv.pk}": True,
    }


def _setup_base(tenant):
    """Create the common objects needed for forecast tests."""
    storage = StorageFactory(is_short_term_harvest_storage=True)
    article = ShareArticleFactory()
    stv = ShareTypeVariationFactory()
    sdd = SharesDeliveryDayFactory(day_number=2)
    station = DeliveryStationFactory()
    DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)
    return storage, article, stv, sdd, station


# ═══════════════════════════════════════════════════════
# CREATE Forecast → ShareContents with forecast FK
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestCreateForecastLinkage:
    def test_creating_forecast_creates_share_contents_with_forecast_linked(
        self, tenant
    ):
        storage, article, stv, sdd, station = _setup_base(tenant)
        data = _forecast_data(article, stv)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        scs = ShareContent.objects.filter(forecast=forecast)
        assert scs.exists(), "ShareContents should be created and linked to Forecast"
        assert all(sc.share_article == article for sc in scs)
        assert all(sc.forecast_id == forecast.pk for sc in scs)

    def test_share_contents_have_correct_share_article_and_size(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        data = _forecast_data(article, stv, size="L")
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        sc = ShareContent.objects.filter(forecast=forecast).first()
        assert sc is not None
        assert sc.share_article == article
        assert sc.size == "L"
        assert sc.unit == "KG"


# ═══════════════════════════════════════════════════════
# Forecast FK drives TheoreticalHarvest creation
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestForecastDrivesTheoreticalHarvest:
    """When ShareContent has amount > 0, the forecast FK determines
    whether a TheoreticalHarvest is created."""

    def test_share_content_with_forecast_creates_theoretical_harvest(self, tenant):
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2)
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

        # Create forecast + ShareContent with amount > 0
        from apps.commissioning.tests.factories import ForecastFactory

        forecast = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=sdd,
            share_type_variation=stv,
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=forecast,
        )
        sc = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
            "seller",
        ).get(pk=sc.pk)

        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk], quantity=3)

        svc = ShareContentService()
        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        ths = TheoreticalHarvest.objects.filter(share_content=sc)
        assert (
            ths.exists()
        ), "TheoreticalHarvest should be created when ShareContent has forecast + amount > 0"
        assert ths.first().share_article == article
        # amount = 5 * 3 (quantity) = 15
        assert ths.first().amount == Decimal("15")

    def test_share_content_without_forecast_no_theoretical_harvest(self, tenant):
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2)
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=sdd,
            share_type_variation=stv,
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=None,
        )
        sc = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
            "seller",
        ).get(pk=sc.pk)

        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk], quantity=3)

        svc = ShareContentService()
        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        assert not TheoreticalHarvest.objects.filter(
            share_content=sc
        ).exists(), "No TheoreticalHarvest without forecast, even with amount > 0"

    def test_share_content_must_match_linked_forecast_dimensions(self, tenant):
        """A ShareContent tied to a Forecast must share its share_article, unit
        and size. A linked Forecast IS this content's harvest-planning source,
        so they describe the same produce — if size diverged, the theoretical
        harvest (forecast size) and the actual-harvest correction (content size)
        would sit on different ledger dimensions and double-count. The mismatch
        is rejected at save time."""
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2)
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

        # Forecast size "L" ≠ ShareContent size "M" → rejected.
        forecast = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="L",
            storage=storage,
        )
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=sdd,
            share_type_variation=stv,
        )
        with pytest.raises(ValidationError):
            ShareContentFactory(
                share=share,
                share_article=article,
                delivery_station=station,
                amount=Decimal("5"),
                unit="KG",
                size="M",
                forecast=forecast,
            )


# ═══════════════════════════════════════════════════════
# UPDATE Forecast → ShareContents re-linked
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestUpdateForecastRelinkage:
    def test_update_keeps_share_contents_linked_to_forecast(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        data = _forecast_data(article, stv)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        sc_count_before = ShareContent.objects.filter(forecast=forecast).count()
        assert sc_count_before > 0

        update_data = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": article,
            "unit": "KG",
            "size": "M",
            "amount": 200,
            f"variation_{stv.pk}": True,
        }

        with _patch_totals(totals):
            svc.update_forecast_with_related_objects(forecast, update_data)

        scs_after = ShareContent.objects.filter(forecast=forecast)
        assert scs_after.exists(), "ShareContents should still be linked after update"
        assert all(sc.forecast_id == forecast.pk for sc in scs_after)


# ═══════════════════════════════════════════════════════
# DELETE Forecast → cascade-deletes ShareContents
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestDeleteForecastCascades:
    def test_deleting_forecast_cascade_deletes_share_contents(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        data = _forecast_data(article, stv)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        sc_ids = list(
            ShareContent.objects.filter(forecast=forecast).values_list("id", flat=True)
        )
        assert sc_ids, "ShareContents should exist before delete"

        forecast.delete()

        assert not ShareContent.objects.filter(
            id__in=sc_ids
        ).exists(), "ShareContents should be cascade-deleted with Forecast"

    def test_deleting_forecast_cascade_deletes_theoretical_harvests(self, tenant):
        """TheoreticalHarvests linked via ShareContent → Forecast cascade."""
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2)
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)

        from apps.commissioning.tests.factories import ForecastFactory

        forecast = ForecastFactory(
            share_article=article,
            year=2026,
            delivery_week=15,
            size="M",
            storage=storage,
        )
        share = ShareFactory(
            year=2026,
            delivery_week=15,
            delivery_day=sdd,
            share_type_variation=stv,
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=forecast,
        )
        sc = ShareContent.objects.select_related(
            "share__share_type_variation",
            "share__delivery_day",
            "share_article",
            "forecast",
            "seller",
        ).get(pk=sc.pk)

        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk], quantity=2)
        svc = ShareContentService()
        with _patch_totals(totals):
            svc.create_all_theoretical_objects([sc])

        th_ids = list(
            TheoreticalHarvest.objects.filter(share_content=sc).values_list(
                "id", flat=True
            )
        )
        assert th_ids, "TheoreticalHarvests should exist before delete"

        forecast.delete()

        assert not TheoreticalHarvest.objects.filter(
            id__in=th_ids
        ).exists(), "TheoreticalHarvests should be cascade-deleted with Forecast"


# ═══════════════════════════════════════════════════════
# DELETE ShareContent → Forecast is NOT deleted
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestDeleteShareContentKeepsForecast:
    def test_deleting_share_content_does_not_delete_forecast(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        data = _forecast_data(article, stv)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        forecast_id = forecast.pk
        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs, "Should have ShareContents"

        # Delete all share contents
        for sc in scs:
            sc.delete()

        # Forecast must still exist
        assert Forecast.objects.filter(
            pk=forecast_id
        ).exists(), "Forecast should NOT be deleted when ShareContents are deleted"

    def test_deleting_one_share_content_keeps_others_and_forecast(self, tenant):
        """Deleting one ShareContent linked to a Forecast keeps the rest intact."""
        _storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        # Two delivery days → two ShareContents
        sdd1 = SharesDeliveryDayFactory(day_number=2)
        sdd2 = SharesDeliveryDayFactory(day_number=3)
        station = DeliveryStationFactory()
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd1)
        DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd2)

        data = _forecast_data(article, stv)
        totals = _make_totals_for_all([sdd1.pk, sdd2.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert len(scs) >= 2, "Should have at least 2 ShareContents"

        # Delete one
        scs[0].delete()

        # Forecast still exists
        assert Forecast.objects.filter(pk=forecast.pk).exists()
        # Other ShareContent still linked
        remaining = ShareContent.objects.filter(forecast=forecast)
        assert remaining.count() == len(scs) - 1


# ═══════════════════════════════════════════════════════
# Regression: duplicate ShareContent when station has multiple DSDs
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestForecastNoDuplicateShareContents:
    """A station may legitimately have several DeliveryStationDay rows for the
    same share-delivery day (e.g. multiple tours, or stale/overlapping rows).
    The forecast service must still produce exactly one ShareContent per
    (share, share_article, delivery_station, unit, size).
    """

    def test_multiple_tours_on_same_station_does_not_duplicate(self, tenant):
        StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2, number_of_tours=2)
        station = DeliveryStationFactory()
        # Two DSD rows for the same (station, day) — different tours.
        # The TimeBoundMixin overlap rule covers (station, day), so we use
        # disjoint validity windows to allow both to coexist.
        import datetime as _dt

        DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=sdd,
            tour_number=1,
            valid_from=_dt.date(2026, 1, 5),
            valid_until=_dt.date(2026, 3, 29),
        )
        DeliveryStationDayFactory(
            delivery_station=station,
            delivery_day=sdd,
            tour_number=2,
            valid_from=_dt.date(2026, 3, 30),
            valid_until=None,
        )

        # Forecast week 18/2026 falls inside the second DSD's window only,
        # so the bug only fires if the service ignores active_at_date and
        # picks up both rows. Use a week where ONLY the second DSD is active
        # to confirm the active_at_date filter works first…
        data = _forecast_data(article, stv, year=2026, delivery_week=18)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(data)

        scs = ShareContent.objects.filter(forecast=forecast)
        unique_keys = {
            (sc.share_id, sc.share_article_id, sc.delivery_station_id, sc.unit, sc.size)
            for sc in scs
        }
        assert scs.count() == len(unique_keys), (
            f"Got {scs.count()} ShareContents but only {len(unique_keys)} "
            f"unique (share, article, station, unit, size) tuples — duplicates!"
        )

    def test_overlapping_active_dsds_does_not_duplicate(self, tenant):
        """Two active DeliveryStationDay rows for the same (station, day) are
        now forbidden at the DB level by
        ``deliverystationday_unique_active_per_station_day``. Confirm the
        constraint actually rejects such inserts so the forecast service can
        rely on the invariant.
        """
        StorageFactory(is_short_term_harvest_storage=True)
        ShareArticleFactory()
        ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2, number_of_tours=2)
        station = DeliveryStationFactory()

        import datetime as _dt

        from django.db import IntegrityError, transaction

        from apps.commissioning.models import DeliveryStationDay

        DeliveryStationDay.objects.bulk_create(
            [
                DeliveryStationDay(
                    delivery_station=station,
                    delivery_day=sdd,
                    tour_number=1,
                    valid_from=_dt.date(2026, 1, 5),
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DeliveryStationDay.objects.bulk_create(
                    [
                        DeliveryStationDay(
                            delivery_station=station,
                            delivery_day=sdd,
                            tour_number=2,
                            valid_from=_dt.date(2026, 1, 5),
                        ),
                    ]
                )


# ═══════════════════════════════════════════════════════
# DefaultShareArticleInShare → drives ShareContent.amount in the forecast
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestDefaultShareArticleInShareDrivesForecastAmount:
    """``ForecastService._create_or_update_share_contents`` resolves the
    amount used for each generated ``ShareContent`` from (in order):

    1. ``DefaultShareArticleInShare`` for ``(share_article, variation)``
       (when ``quantity`` is not None),
    2. else ``DefaultShareContent`` for ``(variation, share_article, year, week)``,
    3. else ``0``.
    """

    def _run(self, article, stv, sdd, station):
        data = _forecast_data(article, stv)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])
        svc = ForecastService()
        with _patch_totals(totals):
            return svc.create_forecast_with_related_objects(data)

    def test_default_share_article_in_share_sets_amount(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=stv,
            quantity=Decimal("4.250"),
            unit="KG",
        )

        forecast = self._run(article, stv, sdd, station)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs, "expected at least one ShareContent created from forecast"
        assert all(sc.amount == Decimal("4.250") for sc in scs)

    def test_default_share_article_in_share_takes_precedence_over_default_share_content(
        self, tenant
    ):
        storage, article, stv, sdd, station = _setup_base(tenant)
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=stv,
            quantity=Decimal("7.000"),
            unit="KG",
        )
        # A DefaultShareContent for the same combination — should be ignored
        # because DefaultShareArticleInShare wins.
        DefaultShareContentFactory(
            share_type_variation=stv,
            share_article=article,
            year=2026,
            delivery_week=15,
            amount=Decimal("2.000"),
            unit="KG",
            size="M",
        )

        forecast = self._run(article, stv, sdd, station)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs
        assert all(sc.amount == Decimal("7.000") for sc in scs)

    def test_falls_back_to_default_share_content_when_no_default_share_article_in_share(
        self, tenant
    ):
        storage, article, stv, sdd, station = _setup_base(tenant)
        DefaultShareContentFactory(
            share_type_variation=stv,
            share_article=article,
            year=2026,
            delivery_week=15,
            amount=Decimal("2.500"),
            unit="KG",
            size="M",
        )

        forecast = self._run(article, stv, sdd, station)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs
        assert all(sc.amount == Decimal("2.500") for sc in scs)

    def test_falls_back_to_zero_when_no_defaults_exist(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)

        forecast = self._run(article, stv, sdd, station)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs
        assert all(sc.amount == 0 for sc in scs)

    def test_default_only_applies_to_matching_variation(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        # Default for a *different* variation must not leak into our forecast.
        other_variation = ShareTypeVariationFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=article,
            share_type_variation=other_variation,
            quantity=Decimal("9.000"),
            unit="KG",
        )

        forecast = self._run(article, stv, sdd, station)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs
        assert all(sc.amount == 0 for sc in scs)

    def test_default_only_applies_to_matching_share_article(self, tenant):
        storage, article, stv, sdd, station = _setup_base(tenant)
        # Default keyed to a *different* share article — must not be picked up.
        other_article = ShareArticleFactory()
        DefaultShareArticleInShare.objects.create(
            share_article=other_article,
            share_type_variation=stv,
            quantity=Decimal("9.000"),
            unit="KG",
        )

        forecast = self._run(article, stv, sdd, station)

        scs = list(ShareContent.objects.filter(forecast=forecast))
        assert scs
        assert all(sc.amount == 0 for sc in scs)


# ═══════════════════════════════════════════════════════
# UPDATE recompute discipline (CORR-7)
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestUpdateRecomputesAffectedShares:
    """A heavy UPDATE must schedule a single recompute covering the SURVIVING
    ShareContents (re-pointed, not recreated) plus any new rows — otherwise the
    survivors' harvest theoreticals would never be rebuilt. The affected share
    ids are collected before the forecast is mutated. The recompute itself —
    NOT the update — owns deleting + rebuilding the harvest theoreticals and
    cascading their movements (see the ``does_not_predelete`` test below; the
    update pre-deleting them was SHR-1)."""

    def test_heavy_update_schedules_recompute_for_surviving_shares(
        self, tenant, django_capture_on_commit_callbacks
    ):
        storage, article, stv, sdd, station = _setup_base(tenant)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])
        svc = ForecastService()

        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(
                _forecast_data(article, stv)
            )

        surviving_share_ids = {
            str(share_id)
            for share_id in ShareContent.objects.filter(forecast=forecast).values_list(
                "share_id", flat=True
            )
        }
        assert surviving_share_ids, "expected the create to materialise ShareContents"

        # A heavy edit (``amount`` is a ``_FORECAST_FIELDS`` key → full
        # path) that only RE-POINTS the existing ShareContents — no new
        # rows are created, the create-less branch the bug missed.
        update_data = _forecast_data(article, stv)
        update_data["amount"] = 200

        with patch(
            "apps.commissioning.services.forecast_service.recompute_shares"
        ) as mock_recompute:
            with _patch_totals(totals):
                with django_capture_on_commit_callbacks(execute=True):
                    svc.update_forecast_with_related_objects(forecast, update_data)

            assert mock_recompute.called, (
                "heavy update scheduled no recompute — the surviving shares' "
                "wiped harvest theoreticals would never be rebuilt (CORR-7)"
            )
            scheduled_ids: set[str] = set()
            for call in mock_recompute.call_args_list:
                scheduled_ids.update(call.args[0])
            assert surviving_share_ids <= scheduled_ids

    def test_heavy_update_does_not_predelete_harvest_theoreticals(
        self, tenant, django_capture_on_commit_callbacks
    ):
        """SHR-1: the update must NOT delete the harvest theoreticals up front.
        The (deferred) recompute captures each share's ``MovementShareArticle``
        rows as ``old_movements`` and cascades them through the stock snapshots
        before rebuilding — so they must still exist when it runs. Pre-deleting
        them in the update strands those snapshots, leaving
        ``theoretical_current_stock`` permanently too high."""
        storage, article, stv, sdd, station = _setup_base(tenant)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])
        svc = ForecastService()

        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(
                _forecast_data(article, stv)
            )

        # Give the materialised ShareContents a billable amount and build their
        # harvest theoreticals (ShareContent + forecast + amount > 0 → harvest).
        ShareContent.objects.filter(forecast=forecast).update(amount=Decimal("5"))
        scs = [
            ShareContent.objects.select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
                "forecast",
                "seller",
            ).get(pk=pk)
            for pk in ShareContent.objects.filter(forecast=forecast).values_list(
                "pk", flat=True
            )
        ]
        assert scs, "expected the create to materialise ShareContents"
        with _patch_totals(totals):
            ShareContentService().create_all_theoretical_objects(scs)

        harvests_before = TheoreticalHarvest.objects.filter(forecast=forecast).count()
        assert (
            harvests_before > 0
        ), "expected harvest theoreticals to be materialised for the setup"

        # Heavy update with the recompute SUPPRESSED — observe the state the
        # recompute WOULD see: the harvest theoreticals (and their cascaded
        # movements) must still be present, NOT pre-deleted by the update.
        update_data = _forecast_data(article, stv)
        update_data["amount"] = 200
        with patch("apps.commissioning.services.forecast_service.recompute_shares"):
            with _patch_totals(totals):
                with django_capture_on_commit_callbacks(execute=True):
                    svc.update_forecast_with_related_objects(forecast, update_data)

        assert (
            TheoreticalHarvest.objects.filter(forecast=forecast).count()
            == harvests_before
        ), (
            "the update pre-deleted harvest theoreticals — recompute can no "
            "longer cascade their movements (SHR-1)"
        )

    def test_light_update_schedules_no_recompute(
        self, tenant, django_capture_on_commit_callbacks
    ):
        """A note-only edit takes the light path and must NOT enqueue a
        recompute (the cost-saving short-circuit the perf suite guards)."""
        storage, article, stv, sdd, station = _setup_base(tenant)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])
        svc = ForecastService()

        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(
                _forecast_data(article, stv)
            )

        with patch(
            "apps.commissioning.services.forecast_service.recompute_shares"
        ) as mock_recompute:
            with django_capture_on_commit_callbacks(execute=True):
                svc.update_forecast_with_related_objects(
                    forecast, {"note": "just a note"}
                )

            assert not mock_recompute.called


# ═══════════════════════════════════════════════════════
# CREATE/UPDATE recompute adopted forecastless shares
# ═══════════════════════════════════════════════════════


@pytest.mark.django_db
class TestAdoptedForecastlessSharesAreRecomputed:
    """A Forecast that ADOPTS a pre-existing forecastless ShareContent (same
    share_article/unit/size, matched by share+station) must schedule a recompute
    for that share on BOTH create and update. The adopted row had
    ``forecast=None`` so it has NO harvest theoretical on disk; only a recompute
    CREATES its TheoreticalHarvest + HARVEST movement — the bare forecast-FK
    relink inside ``_create_or_update_share_contents`` can only re-point rows
    that already have theoreticals, never create missing ones.

    Regression: both paths used to schedule a recompute only for the
    genuinely-new (``created``) rows and silently drop the adopted (``updated``)
    ones, so adopted produce never entered harvest planning until an unrelated
    later recompute (e.g. a ShareDelivery edit) happened to rebuild the share.
    """

    @staticmethod
    def _scheduled_ids(mock_recompute) -> set[str]:
        scheduled: set[str] = set()
        for call in mock_recompute.call_args_list:
            scheduled.update(call.args[0])
        return scheduled

    def test_create_recomputes_adopted_forecastless_share(
        self, tenant, django_capture_on_commit_callbacks
    ):
        storage, article, stv, sdd, station = _setup_base(tenant)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        # A ShareContent that exists BEFORE any forecast, on the exact
        # (share_article, unit, size) the forecast will describe and the
        # (share, station) it fans out to. forecast=None → no harvest theoretical.
        share = ShareFactory(
            year=2026, delivery_week=15, delivery_day=sdd, share_type_variation=stv
        )
        sc = ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=None,
        )
        assert not TheoreticalHarvest.objects.filter(share_content=sc).exists()

        svc = ForecastService()
        with patch(
            "apps.commissioning.services.forecast_service.recompute_shares"
        ) as mock_recompute:
            with _patch_totals(totals):
                with django_capture_on_commit_callbacks(execute=True):
                    forecast = svc.create_forecast_with_related_objects(
                        _forecast_data(article, stv)
                    )

            sc.refresh_from_db()
            assert (
                sc.forecast_id == forecast.pk
            ), "the create should adopt the matching forecastless ShareContent"
            assert mock_recompute.called, (
                "create scheduled no recompute — the adopted forecastless "
                "ShareContent's harvest theoretical would never be created"
            )
            assert str(share.pk) in self._scheduled_ids(mock_recompute)

    def test_update_recomputes_newly_adopted_forecastless_share(
        self, tenant, django_capture_on_commit_callbacks
    ):
        # Forecast created for variation ``stv`` → materialises a ShareContent on
        # ``share`` (its share is captured as ``affected_share_ids`` on update).
        storage, article, stv, sdd, station = _setup_base(tenant)
        stv2 = ShareTypeVariationFactory()
        totals = _make_totals_for_all([sdd.pk], [stv.pk, stv2.pk], [station.pk])
        svc = ForecastService()
        with _patch_totals(totals):
            forecast = svc.create_forecast_with_related_objects(
                _forecast_data(article, stv)
            )

        # A DIFFERENT share (variation ``stv2``) with a forecastless ShareContent
        # the forecast does not cover yet. Its share is NOT among
        # ``affected_share_ids`` — so only unioning ``updated`` schedules it.
        share2 = ShareFactory(
            year=2026, delivery_week=15, delivery_day=sdd, share_type_variation=stv2
        )
        sc2 = ShareContentFactory(
            share=share2,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=None,
        )

        # Heavy update that ADDS variation ``stv2`` → the forecast now fans out
        # to ``share2`` and adopts the pre-existing forecastless ``sc2``.
        update_data = _forecast_data(article, stv)
        update_data[f"variation_{stv2.pk}"] = True
        with patch(
            "apps.commissioning.services.forecast_service.recompute_shares"
        ) as mock_recompute:
            with _patch_totals(totals):
                with django_capture_on_commit_callbacks(execute=True):
                    svc.update_forecast_with_related_objects(forecast, update_data)

            sc2.refresh_from_db()
            assert (
                sc2.forecast_id == forecast.pk
            ), "the update should adopt the matching forecastless ShareContent"
            assert str(share2.pk) in self._scheduled_ids(
                mock_recompute
            ), "update dropped the newly-adopted share from the recompute set"

    def test_recompute_actually_builds_harvest_for_adopted_share(self, tenant):
        """After a Forecast adopts a forecastless ShareContent, running the
        recompute must actually CREATE that share's TheoreticalHarvest +
        HARVEST movement — not merely schedule it. Guards the full
        adoption → recompute → harvest chain end-to-end."""
        storage, article, stv, sdd, station = _setup_base(tenant)
        totals = _make_totals_for_all([sdd.pk], [stv.pk], [station.pk])

        share = ShareFactory(
            year=2026, delivery_week=15, delivery_day=sdd, share_type_variation=stv
        )
        ShareContentFactory(
            share=share,
            share_article=article,
            delivery_station=station,
            amount=Decimal("5"),
            unit="KG",
            size="M",
            forecast=None,
        )

        svc = ForecastService()
        # The create defers its recompute; suppress the deferred task so we can
        # drive the recompute deterministically below.
        with patch("apps.commissioning.services.forecast_service.recompute_shares"):
            with _patch_totals(totals):
                forecast = svc.create_forecast_with_related_objects(
                    _forecast_data(article, stv)
                )

        share_content = ShareContent.objects.get(share=share, forecast=forecast)
        with _patch_totals(totals):
            recompute_shares([str(share.pk)])

        assert TheoreticalHarvest.objects.filter(
            share_content=share_content
        ).exists(), (
            "recompute did not create a TheoreticalHarvest for the adopted share"
        )
        assert MovementShareArticle.objects.filter(
            theoretical_harvest__share_content=share_content
        ).exists(), "recompute did not create a HARVEST movement for the adopted share"


@pytest.mark.django_db
class TestCreateOrUpdateShareContentsQueryCount:
    """The (share × station) existence check must be ONE batched query, not a
    ``ShareContent.filter().exists()`` per (share, station) pair. The private
    ``_create_or_update_share_contents`` issues no recompute, so its
    ShareContent SELECT count isolates the existence lookup cleanly."""

    @staticmethod
    def _sharecontent_selects(ctx: CaptureQueriesContext) -> int:
        return sum(
            1
            for q in ctx.captured_queries
            if '"commissioning_sharecontent"' in q["sql"].lower()
            and q["sql"].lstrip().lower().startswith("select")
        )

    def test_existence_check_is_one_batched_query(self, tenant):
        # One delivery day fanning out to many stations → many (share, station)
        # pairs. (A single measurement: ``_create_or_update_share_contents``
        # reads ALL active SharesDeliveryDay, so a second fan-out in the same
        # test would leak its day into this one's count.)
        n_stations = 6
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        stv = ShareTypeVariationFactory()
        sdd = SharesDeliveryDayFactory(day_number=2)
        for _ in range(n_stations):
            DeliveryStationDayFactory(
                delivery_station=DeliveryStationFactory(), delivery_day=sdd
            )
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )
        fstv = ForecastShareTypeVariationFactory(
            forecast=forecast, share_type_variation=stv
        )
        validated_data = {
            "year": 2026,
            "delivery_week": 15,
            "share_article": article,
            "unit": "KG",
            "size": "M",
        }

        svc = ForecastService()
        # First call fans out to one ShareContent per station.
        created, _updated = svc._create_or_update_share_contents(
            forecast, validated_data, [fstv]
        )
        # Non-vacuity guard: the fan-out really produced one row per station,
        # so the existence check on the re-run below has real work to do.
        assert len(created) == n_stations

        # Re-run: every (share, station) already exists → the existence check
        # must be ONE batched query, not one ``.exists()`` per pair.
        with CaptureQueriesContext(connection) as ctx:
            _created, updated = svc._create_or_update_share_contents(
                forecast, validated_data, [fstv]
            )
        assert len(updated) == n_stations  # all resolved from the batched map
        assert self._sharecontent_selects(ctx) == 1, (
            "ShareContent existence check is not batched — expected 1 SELECT "
            f"for {n_stations} stations (one .exists() per pair would be "
            f"{n_stations})."
        )
