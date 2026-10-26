import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

const DashboardCultivation = lazy(
  () => import("@features/cultivation/pages/DashboardCultivation"),
);

const ListVegetables = lazy(
  () => import("@/features/cultivation/pages/ListVegetables"),
);
const PlantingList = lazy(
  () => import("@features/cultivation/pages/PlantingList"),
);
const SowingList = lazy(() => import("@features/cultivation/pages/SowingList"));
const OrderSeedlings = lazy(
  () => import("@features/cultivation/pages/OrderSeedlings"),
);
const OrderSeeds = lazy(() => import("@features/cultivation/pages/OrderSeeds"));

const ListSellersSeedlings = lazy(
  () => import("@features/cultivation/pages/ListSellersSeedlings"),
);
const ListSellersSeeds = lazy(
  () => import("@features/cultivation/pages/ListSellersSeeds"),
);
const CultivationBatchIndoors = lazy(
  () => import("@features/cultivation/pages/CultivationBatchIndoors"),
);
const CultivationBatchOutdoors = lazy(
  () => import("@features/cultivation/pages/CultivationBatchOutdoors"),
);
const SortsSeedlingsIndoors = lazy(
  () => import("@features/cultivation/pages/SortsSeedlingsIndoors"),
);
const SortsSeedlingsOutdoors = lazy(
  () => import("@features/cultivation/pages/SortsSeedlingsOutdoors"),
);
const SortsSeedsIndoors = lazy(
  () => import("@features/cultivation/pages/SortsSeedsIndoors"),
);
const SortsSeedsOutdoors = lazy(
  () => import("@features/cultivation/pages/SortsSeedsOutdoors"),
);
const AmountsForCultivation = lazy(
  () => import("@features/cultivation/pages/AmountsForCultivation"),
);
const DocumentationFertilizers = lazy(
  () => import("@features/cultivation/pages/DocumentationFertilizers"),
);
const DocumentationPesticides = lazy(
  () => import("@features/cultivation/pages/DocumentationPesticides"),
);
const ListPlots = lazy(() => import("@features/cultivation/pages/ListPlots"));
const CultivationPlanner = lazy(
  () => import("@features/cultivation/pages/CultivationPlanner"),
);
const ConfigurationSolver = lazy(
  () => import("@features/cultivation/pages/ConfigurationSolver"),
);
const ListBedTypes = lazy(
  () => import("@features/cultivation/pages/ListBedTypes"),
);
const ListCultivationBreakFamilies = lazy(
  () => import("@features/cultivation/pages/ListCultivationBreakFamilies"),
);
const ListVegetableAggregations = lazy(
  () => import("@features/cultivation/pages/ListVegetableAggregations"),
);
const ListSeedlingsVendors = lazy(
  () => import("@features/cultivation/pages/ListSeedlingsVendors"),
);
const ListSeedsVendors = lazy(
  () => import("@features/cultivation/pages/ListSeedsVendors"),
);

export const cultivationRoutes: AppRoute[] = [
  {
    path: "/cultivation/planner",
    element: (
      <RequireRole flag="canEditCultivation">
        <CultivationPlanner />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/solver-settings",
    element: (
      <RequireRole flag="canEditCultivation">
        <ConfigurationSolver />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/plots",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListPlots />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/bed-types",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListBedTypes />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/break-families",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListCultivationBreakFamilies />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/vegetable-aggregations",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListVegetableAggregations />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/seedlings-vendors",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListSeedlingsVendors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/seeds-vendors",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListSeedsVendors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/dashboard",
    element: (
      <RequireRole flag="canEditCultivation">
        <DashboardCultivation />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/documentation-pesticides",
    element: (
      <RequireRole flag="canEditCultivation">
        <DocumentationPesticides />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/documentation-fertilizers",
    element: (
      <RequireRole flag="canEditCultivation">
        <DocumentationFertilizers />
      </RequireRole>
    ),
  },

  {
    path: "/cultivation/amounts-for-cultivation",
    element: (
      <RequireRole flag="canEditCultivation">
        <AmountsForCultivation />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/list-vegetable-families",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListVegetables />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/planting-list",
    element: (
      <RequireRole flag="canEditCultivation">
        <PlantingList />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sowing-list",
    element: (
      <RequireRole flag="canEditCultivation">
        <SowingList />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/order-seedlings",
    element: (
      <RequireRole flag="canEditCultivation">
        <OrderSeedlings />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/order-seeds",
    element: (
      <RequireRole flag="canEditCultivation">
        <OrderSeeds />
      </RequireRole>
    ),
  },

  {
    path: "/cultivation/list-sellers-seedlings",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListSellersSeedlings />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/list-sellers-seeds",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListSellersSeeds />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sets-indoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <CultivationBatchIndoors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sets-outdoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <CultivationBatchOutdoors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sorts-seedlings-outdoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <SortsSeedlingsOutdoors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sorts-seeds-outdoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <SortsSeedsOutdoors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sorts-seedlings-indoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <SortsSeedlingsIndoors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sorts-seeds-indoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <SortsSeedsIndoors />
      </RequireRole>
    ),
  },
];
