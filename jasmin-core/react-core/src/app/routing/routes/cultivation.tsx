import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

const DashboardCultivation = lazy(
  () => import("@features/cultivation/pages/DashboardCultivation"),
);
const ListPlantFamilies = lazy(
  () => import("@features/cultivation/pages/ListPlantFamilies"),
);
const ListVegetableFamilies = lazy(
  () => import("@features/cultivation/pages/ListVegetableFamilies"),
);
const PlantingList = lazy(() => import("@features/cultivation/pages/PlantingList"));
const SowingList = lazy(() => import("@features/cultivation/pages/SowingList"));
const OrderSeedlings = lazy(
  () => import("@features/cultivation/pages/OrderSeedlings"),
);
const OrderSeeds = lazy(() => import("@features/cultivation/pages/OrderSeeds"));
const PlantingSchemeOutdoors = lazy(
  () => import("@features/cultivation/pages/PlantingSchemeOutdoors"),
);
const ListSellersSeedlings = lazy(
  () => import("@features/cultivation/pages/ListSellersSeedlings"),
);
const ListSellersSeeds = lazy(
  () => import("@features/cultivation/pages/ListSellersSeeds"),
);
const SetsIndoors = lazy(() => import("@features/cultivation/pages/SetsIndoors"));
const SetsOutdoors = lazy(() => import("@features/cultivation/pages/SetsOutdoors"));
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

export const cultivationRoutes: AppRoute[] = [
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
    path: "/cultivation/list-plant-families",
    element: (
      <RequireRole flag="canEditCultivation">
        <ListPlantFamilies />
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
        <ListVegetableFamilies />
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
    path: "/cultivation/planting-scheme-outdoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <PlantingSchemeOutdoors />
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
        <SetsIndoors />
      </RequireRole>
    ),
  },
  {
    path: "/cultivation/sets-outdoors",
    element: (
      <RequireRole flag="canEditCultivation">
        <SetsOutdoors />
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
