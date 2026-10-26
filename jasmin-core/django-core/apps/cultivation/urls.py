from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import (
    BedTypeViewSet,
    CultivationBatchViewSet,
    CultivationBreakFamilyViewSet,
    CultivationPlanSolutionViewSet,
    HistoricalPlantingViewSet,
    PlotContentViewSet,
    PlotViewSet,
    SeedlingsVendorViewSet,
    SeedsVendorViewSet,
    SolverSettingsViewSet,
    VegetableAggregationViewSet,
    VegetableViewSet,
)

router = DefaultRouter()
# basename is disambiguated from the commissioning "Plot" documentation viewset
# (a different entity) so reverse("plots-list") stays unambiguous — the URL path
# (/api/cultivation/plots/) and the OpenAPI schema are unaffected.
router.register(r"plots", PlotViewSet, basename="cultivation_plots")
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
router.register(
    r"plan_solutions", CultivationPlanSolutionViewSet, basename="plan_solutions"
)
router.register(r"solver_settings", SolverSettingsViewSet, basename="solver_settings")

urlpatterns = [
    path("", include(router.urls)),
]
