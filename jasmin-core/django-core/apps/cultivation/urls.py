from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import (
    BedTypeViewSet,
    CultivationBatchViewSet,
    CultivationBreakFamilyViewSet,
    HistoricalPlantingViewSet,
    PlotContentViewSet,
    PlotViewSet,
    SeedlingsVendorViewSet,
    SeedsVendorViewSet,
    VegetableAggregationViewSet,
    VegetableViewSet,
)

router = DefaultRouter()
router.register(r"plots", PlotViewSet, basename="plots")
router.register(r"bed_types", BedTypeViewSet, basename="bed_types")
router.register(r"plot_contents", PlotContentViewSet, basename="plot_contents")
router.register(r"vegetables", VegetableViewSet, basename="vegetables")
router.register(
    r"cultivation_break_families",
    CultivationBreakFamilyViewSet,
    basename="cultivation_break_families",
)
router.register(
    r"vegetable_aggregations",
    VegetableAggregationViewSet,
    basename="vegetable_aggregations",
)
router.register(
    r"cultivation_batches", CultivationBatchViewSet, basename="cultivation_batches"
)
router.register(
    r"seedlings_vendors", SeedlingsVendorViewSet, basename="seedlings_vendors"
)
router.register(r"seeds_vendors", SeedsVendorViewSet, basename="seeds_vendors")
router.register(
    r"historical_plantings", HistoricalPlantingViewSet, basename="historical_plantings"
)

urlpatterns = [
    path("", include(router.urls)),
]
