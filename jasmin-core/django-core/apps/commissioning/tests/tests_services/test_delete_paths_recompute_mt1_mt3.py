"""Movement-recompute invariant: any path that cascade-removes theoretical
HARVEST/PURCHASE/WASH/CLEAN movements must re-cascade snapshots + re-derive
actual corrections, capturing BOTH the content movements AND the theoretical
half — else the stock projection is left permanently stale. Locks the service
delete (MT-1/MT-3 delete_share_planning), the Forecast-delete viewset, the
wipe-and-rebuild replace_share_planning (MOV-2), the ShareContent DELETE
endpoint (MOV-3), and the theoretical-object DELETE endpoints (MOV-4).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.commissioning.models import (
    MovementShareArticle,
    ShareContent,
    TheoreticalHarvest,
)
from apps.commissioning.models.choices import MovementTypeOptions
from apps.commissioning.services.recompute import recompute_shares
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    ForecastFactory,
    MemberFactory,
    PaymentCycleFactory,
    ShareArticleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)

YEAR, WEEK = 2026, 15

_RECALC = (
    "apps.commissioning.services.theoretical_objects.recalculate_actual_corrections"
)
_CASCADE = (
    "apps.commissioning.services.snapshot_service."
    "SnapshotService.cascade_for_movements"
)


def _build_harvest_share_content():
    """A ShareContent with a forecast + real demand → after recompute it owns a
    theoretical HARVEST movement (is_theoretical) that cascades on delete."""
    storage = StorageFactory(is_short_term_harvest_storage=True)
    sdd = SharesDeliveryDayFactory(day_number=2)
    stv = ShareTypeVariationFactory()
    share = ShareFactory(
        year=YEAR, delivery_week=WEEK, delivery_day=sdd, share_type_variation=stv
    )
    station = DeliveryStationFactory()
    dsd = DeliveryStationDayFactory(delivery_station=station, delivery_day=sdd)
    article = ShareArticleFactory()
    forecast = ForecastFactory(
        share_article=article,
        year=YEAR,
        delivery_week=WEEK,
        size="M",
        storage=storage,
    )
    sc = ShareContent.objects.create(
        share=share,
        share_article=article,
        delivery_station=station,
        amount=Decimal("5"),
        unit="KG",
        size="M",
        forecast=forecast,
    )
    member = MemberFactory()
    subscription = SubscriptionFactory(
        member=member,
        share_type_variation=stv,
        payment_cycle=PaymentCycleFactory(),
        default_delivery_station_day=dsd,
        quantity=1,
    )
    delivery = ShareDeliveryFactory(
        share=share, delivery_station_day=dsd, joker_taken=False
    )
    delivery.subscription = subscription
    delivery.save()

    recompute_shares([share.id])
    return article, forecast, sc


def _has_theoretical_harvest_movement():
    return MovementShareArticle.objects.filter(
        movement_type=MovementTypeOptions.HARVEST, is_theoretical=True
    ).exists()


def _captured_includes_theoretical_harvest(recalc_mock):
    captured = list(recalc_mock.call_args[0][0])
    return any(
        m.movement_type == MovementTypeOptions.HARVEST and m.is_theoretical
        for m in captured
    )


@pytest.mark.django_db
class TestDeletePathsRecompute:
    def test_delete_share_planning_recalcs_with_theoretical_movement(self, tenant):
        article, _forecast, _sc = _build_harvest_share_content()
        assert _has_theoretical_harvest_movement()  # precondition

        with patch(_RECALC) as recalc, patch(_CASCADE) as cascade:
            ShareContentService().delete_share_planning(
                year=YEAR,
                delivery_week=WEEK,
                share_article_id=str(article.id),
                unit="KG",
                size="M",
            )

        cascade.assert_called_once()
        recalc.assert_called_once()
        assert _captured_includes_theoretical_harvest(recalc), (
            "delete_share_planning must capture the cascaded theoretical HARVEST "
            "movement (not just the SHARECONTENT half) and re-derive corrections"
        )

    def test_delete_share_planning_defers_cascade_after_theoretical(self, tenant):
        # Lock-order guard: the theoretical_sum pass
        # (recalculate_actual_corrections) must run BEFORE the single
        # current_balance cascade (cascade_for_movements), and the cascade must
        # be DEFERRED (collect_movements passed) so it runs exactly once — else
        # delete_share_planning inverts the global theoretical_sum ->
        # current_balance order and can AB/BA-deadlock a concurrent count/recompute.
        from unittest.mock import Mock

        article, _forecast, _sc = _build_harvest_share_content()
        assert _has_theoretical_harvest_movement()

        manager = Mock()
        with patch(_RECALC, manager.recalc), patch(_CASCADE, manager.cascade):
            ShareContentService().delete_share_planning(
                year=YEAR,
                delivery_week=WEEK,
                share_article_id=str(article.id),
                unit="KG",
                size="M",
            )

        called = [c[0] for c in manager.mock_calls]
        assert "recalc" in called and "cascade" in called
        assert called.index("recalc") < called.index(
            "cascade"
        ), "theoretical_sum pass must precede the current_balance cascade"
        # Deferred into a single current_balance pass.
        assert manager.recalc.call_args.kwargs.get("collect_movements") is not None
        manager.cascade.assert_called_once()

    def test_forecast_delete_recalcs_with_theoretical_movement(
        self, api_client, tenant
    ):
        _article, forecast, sc = _build_harvest_share_content()
        assert _has_theoretical_harvest_movement()

        with patch(_RECALC) as recalc, patch(_CASCADE) as cascade:
            resp = api_client.delete(reverse("forecast-detail", args=[forecast.id]))

        assert resp.status_code in (200, 204), resp.content
        assert not ShareContent.objects.filter(id=sc.id).exists()  # cascaded away
        cascade.assert_called_once()
        recalc.assert_called_once()
        assert _captured_includes_theoretical_harvest(recalc)

    def test_replace_share_planning_nonempty_recalcs_with_theoretical_movement(
        self, tenant
    ):
        # MOV-2: the wipe-and-rebuild (non-empty) branch of replace_share_planning
        # must capture the theoretical half + re-derive corrections, like
        # delete_share_planning. The rebuild also recalcs internally, so our
        # capture-driven call is the LAST one (read via call_args).
        article, _forecast, sc = _build_harvest_share_content()
        assert _has_theoretical_harvest_movement()
        data = {
            "year": YEAR,
            "delivery_week": WEEK,
            f"day_{sc.share.delivery_day_id}_variation_"
            f"{sc.share.share_type_variation_id}": "3",
        }

        with patch(_RECALC) as recalc, patch(_CASCADE) as cascade:
            ShareContentService().replace_share_planning(
                year=YEAR,
                delivery_week=WEEK,
                share_article_id=str(article.id),
                unit="KG",
                size="M",
                data=data,
            )

        cascade.assert_called()
        recalc.assert_called()
        assert _captured_includes_theoretical_harvest(recalc), (
            "replace_share_planning (non-empty) must capture the cascaded "
            "theoretical HARVEST movement and re-derive corrections"
        )

    def test_replace_share_planning_empty_clear_recalcs_with_theoretical_movement(
        self, tenant
    ):
        # MOV-2 (empty-clear branch): clearing every cell rebuilds/drops rows and
        # cascades their theoretical movements; the dropped/cleared dimensions'
        # actual corrections must still be re-derived (not just snapshots).
        article, _forecast, _sc = _build_harvest_share_content()
        assert _has_theoretical_harvest_movement()
        # Empty payload (no day-variation cells) → the empty-clear branch.
        data = {"year": YEAR, "delivery_week": WEEK}

        with patch(_RECALC) as recalc, patch(_CASCADE) as cascade:
            ShareContentService().replace_share_planning(
                year=YEAR,
                delivery_week=WEEK,
                share_article_id=str(article.id),
                unit="KG",
                size="M",
                data=data,
            )

        cascade.assert_called()
        recalc.assert_called()
        assert _captured_includes_theoretical_harvest(recalc)

    def test_share_content_perform_destroy_recalcs_with_theoretical_movement(
        self, tenant
    ):
        # MOV-3: ShareContentViewSet.perform_destroy must capture both halves +
        # recalc. The endpoint's queryset is is_finalized-only, so the override is
        # exercised directly (route wiring verified separately via reverse()).
        from apps.commissioning.viewsets.shares_viewsets import ShareContentViewSet

        _article, _forecast, sc = _build_harvest_share_content()
        assert _has_theoretical_harvest_movement()

        with patch(_RECALC) as recalc, patch(_CASCADE) as cascade:
            ShareContentViewSet().perform_destroy(sc)

        assert not ShareContent.objects.filter(id=sc.id).exists()
        cascade.assert_called()
        recalc.assert_called()
        assert _captured_includes_theoretical_harvest(recalc)

    def test_theoretical_harvest_perform_destroy_recalcs(self, tenant):
        # MOV-4: the theoretical viewset's perform_destroy (newly added) must
        # re-cascade + re-derive — else the cascaded is_theoretical movement
        # strands a stale actual correction (amount = counted - Σtheoretical).
        # The list queryset windows to recent weeks, so call the override directly.
        from apps.commissioning.viewsets.logs_viewsets import (
            TheoreticalHarvestViewSet,
        )

        _article, _forecast, _sc = _build_harvest_share_content()
        movement = MovementShareArticle.objects.filter(
            movement_type=MovementTypeOptions.HARVEST, is_theoretical=True
        ).first()
        assert movement is not None
        th = movement.theoretical_harvest

        with patch(_RECALC) as recalc, patch(_CASCADE) as cascade:
            TheoreticalHarvestViewSet().perform_destroy(th)

        assert not TheoreticalHarvest.objects.filter(id=th.id).exists()
        cascade.assert_called()
        recalc.assert_called()
        assert _captured_includes_theoretical_harvest(recalc)
