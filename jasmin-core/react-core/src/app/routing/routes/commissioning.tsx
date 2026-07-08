import { RequireRole } from "@shared/auth";
import { lazy } from "react";
import type { AppRoute } from "../types";

// Lazy load all commissioning components - only loaded when the specific route is accessed
const CustomerOrderPage = lazy(
  () => import("@features/customer/pages/CustomerOrderPage"),
);
const CommissioningListResellers = lazy(
  () => import("@features/commissioning/pages/CommissioningListResellers"),
);
const CommissioningListPacking = lazy(
  () => import("@features/commissioning/pages/CommissioningListPacking"),
);
const DashboardCommissioning = lazy(
  () => import("@features/commissioning/pages/DashboardCommissioning"),
);
const DeliveryNotes = lazy(
  () => import("@features/commissioning/pages/DeliveryNotes"),
);
const DeliveryStationsOverview = lazy(
  () => import("@features/commissioning/pages/DeliveryStationsOverview"),
);
const DeliveryStationsDetails = lazy(
  () => import("@features/commissioning/pages/DeliveryStationsDetails"),
);
const DeliveryTours = lazy(
  () => import("@features/commissioning/pages/DeliveryTours"),
);
const DocumentationCurrentStock = lazy(
  () => import("@features/commissioning/pages/DocumentationCurrentStock"),
);
const DocumentationHarvest = lazy(
  () => import("@features/commissioning/pages/DocumentationHarvest"),
);
const DocumentationPurchase = lazy(
  () => import("@features/commissioning/pages/DocumentationPurchase"),
);
const DocumentationWaste = lazy(
  () => import("@features/commissioning/pages/DocumentationWaste"),
);
const Forecast = lazy(() => import("@features/commissioning/pages/Forecast"));
const HarvestingList = lazy(
  () => import("@features/commissioning/pages/HarvestingList"),
);
const PlanningShareContentPage = lazy(
  () => import("@features/commissioning/pages/PlanningShareContentPage"),
);
const Invoices = lazy(() => import("@features/commissioning/pages/Invoices"));

const Labels = lazy(() => import("@features/commissioning/pages/Labels"));
const ListCrates = lazy(
  () => import("@features/commissioning/pages/ListCrates"),
);
const ListDeliveryStations = lazy(
  () => import("@features/commissioning/pages/ListDeliveryStations"),
);
const DeliveryExceptionPeriods = lazy(
  () => import("@features/commissioning/pages/DeliveryExceptionPeriods"),
);
const DeliveryStationFees = lazy(
  () => import("@/features/commissioning/pages/DeliveryStationFees"),
);
const ListExtraArticles = lazy(
  () => import("@features/commissioning/pages/ListExtraArticles"),
);
const ListShareArticles = lazy(
  () => import("@features/commissioning/pages/ListShareArticles"),
);
const DefaultShareArticlesInShare = lazy(
  () => import("@features/commissioning/pages/DefaultShareArticlesInShare"),
);
const ListMarkets = lazy(
  () => import("@features/commissioning/pages/ListMarkets"),
);
const ListOfferGroups = lazy(
  () => import("@features/commissioning/pages/ListOfferGroups"),
);
const ListPlots = lazy(() => import("@features/commissioning/pages/ListPlots"));
const ListResellers = lazy(
  () => import("@features/commissioning/pages/ListResellers"),
);
const ListSellers = lazy(
  () => import("@features/commissioning/pages/ListSellers"),
);
const ListStorages = lazy(
  () => import("@features/commissioning/pages/ListStorages"),
);
const Offers = lazy(() => import("@features/commissioning/pages/Offers"));
const PaymentsResellers = lazy(
  () => import("@features/commissioning/pages/PaymentsResellers"),
);
const Orders = lazy(() => import("@features/commissioning/pages/Orders"));
const OverviewResellers = lazy(
  () => import("@features/commissioning/pages/OverviewResellers"),
);
const PackingListBulk = lazy(
  () => import("@features/commissioning/pages/PackingListBulk"),
);
const PackingListBoxes = lazy(
  () => import("@/features/commissioning/pages/PackingListBoxes"),
);

const WashingList = lazy(
  () => import("@features/commissioning/pages/WashingList"),
);
const CleaningList = lazy(
  () => import("@features/commissioning/pages/CleaningList"),
);
const AmountShares = lazy(
  () => import("@features/commissioning/pages/AmountShares"),
);
const ShareDays = lazy(() => import("@features/commissioning/pages/ShareDays"));
const PurchaseList = lazy(
  () => import("@features/commissioning/pages/PurchaseList"),
);
const StatisticsPurchase = lazy(
  () => import("@features/commissioning/pages/StatisticsPurchase"),
);
const DocumentationOverview = lazy(
  () => import("@features/commissioning/pages/DocumentationOverview"),
);
const LoggingStorage = lazy(
  () => import("@features/commissioning/pages/LoggingStorage"),
);
const ShareWeights = lazy(
  () => import("@features/commissioning/pages/ShareWeights"),
);
const ImportShares = lazy(
  () => import("@features/commissioning/pages/ImportShares"),
);

export const commissioningRoutes: AppRoute[] = [
  {
    path: "/commissioning/dashboard",
    element: (
      <RequireRole flag="isStaff">
        <DashboardCommissioning />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/purchase-list",
    element: (
      <RequireRole flag="isOffice">
        <PurchaseList />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/statistics-purchase",
    element: (
      <RequireRole flag="isOffice">
        <StatisticsPurchase />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/logging-storage",
    element: (
      <RequireRole flag="isStaff">
        <LoggingStorage />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/share-weights",
    element: (
      <RequireRole flag="isStaff">
        <ShareWeights />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/documentation-overview",
    element: (
      <RequireRole flag="isStaff">
        <DocumentationOverview />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-extra-articles",
    element: (
      <RequireRole flag="isStaff">
        <ListExtraArticles />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-plots",
    element: (
      <RequireRole flag="isStaff">
        <ListPlots />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/list-storages",
    element: (
      <RequireRole flag="isStaff">
        <ListStorages />
      </RequireRole>
    ),
  },
  {
    // One data-driven planning route per view. ``:slug`` selects the share
    // option (see @shared/planning/planningShareOptions); the page derives
    // complex-vs-long-term from the option's active ShareType.
    path: "/commissioning/planning/:slug",
    element: (
      <RequireRole flag="isOffice">
        <PlanningShareContentPage mode="complex" />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/planning/:slug/long-term",
    element: (
      <RequireRole flag="isOffice">
        <PlanningShareContentPage mode="long-term" />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/delivery-tours",
    element: (
      <RequireRole flag="isStaff">
        <DeliveryTours />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/share-days",
    element: (
      <RequireRole flag="isOffice">
        <ShareDays />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-offer-groups",
    element: (
      <RequireRole flag="isOffice">
        <ListOfferGroups />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/amount-shares",
    element: (
      <RequireRole flag="isStaff">
        <AmountShares />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/cleaning-list",
    element: (
      <RequireRole flag="isStaff">
        <CleaningList />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/forecast",
    element: (
      <RequireRole flag="isStaff">
        <Forecast />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/commissioning-list-resellers",
    element: (
      <RequireRole flag="isStaff">
        <CommissioningListResellers />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/commissioning-list-packing",
    element: (
      <RequireRole flag="isStaff">
        <CommissioningListPacking />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/harvesting-list",
    element: (
      <RequireRole flag="isStaff">
        <HarvestingList />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/washing-list",
    element: (
      <RequireRole flag="isStaff">
        <WashingList />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/packing-list-boxes",
    element: (
      <RequireRole flag="isStaff">
        <PackingListBoxes />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/packing-list-bulk",
    element: (
      <RequireRole flag="isStaff">
        <PackingListBulk />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/orders",
    element: (
      <RequireRole flag="isOffice">
        <Orders />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/offers",
    element: (
      <RequireRole flag="isOffice">
        <Offers />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/invoices",
    element: (
      <RequireRole flag="isOffice">
        <Invoices />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/payments-resellers",
    element: (
      <RequireRole flag="isOffice">
        <PaymentsResellers />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/delivery-notes",
    element: (
      <RequireRole flag="isOffice">
        <DeliveryNotes />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/labels",
    element: (
      <RequireRole flag="isOffice">
        <Labels />
      </RequireRole>
    ),
  },

  {
    path: "/commissioning/list-harvest-share-articles",
    element: (
      <RequireRole flag="isStaff">
        <ListShareArticles />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/default-share-articles-in-share",
    element: (
      <RequireRole flag="isOffice">
        <DefaultShareArticlesInShare />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-crates",
    element: (
      <RequireRole flag="isStaff">
        <ListCrates />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-delivery-stations",
    element: (
      <RequireRole flag="isStaff">
        <ListDeliveryStations />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/delivery-exceptions",
    element: (
      <RequireRole flag="isStaff">
        <DeliveryExceptionPeriods />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/delivery-station-fees",
    element: (
      <RequireRole flag="isOffice">
        <DeliveryStationFees />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/delivery-stations-overview",
    element: (
      <RequireRole flag="isStaff">
        <DeliveryStationsOverview />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/delivery-stations-details",
    element: (
      <RequireRole flag="isStaff">
        <DeliveryStationsDetails />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-markets",
    element: (
      <RequireRole flag="isStaff">
        <ListMarkets />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-resellers",
    element: (
      <RequireRole flag="isOffice">
        <ListResellers />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/list-sellers",
    element: (
      <RequireRole flag="isOffice">
        <ListSellers />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/customer-orders/:resellerId",
    element: (
      <RequireRole flag="isStaff">
        <CustomerOrderPage />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/overview-resellers",
    element: (
      <RequireRole flag="isOffice">
        <OverviewResellers />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/documentation-harvest",
    element: (
      <RequireRole flag="isStaff">
        <DocumentationHarvest />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/documentation-purchase",
    element: (
      <RequireRole flag="isStaff">
        <DocumentationPurchase />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/documentation-waste",
    element: (
      <RequireRole flag="isStaff">
        <DocumentationWaste />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/documentation-current-stock",
    element: (
      <RequireRole flag="isStaff">
        <DocumentationCurrentStock />
      </RequireRole>
    ),
  },
  {
    path: "/commissioning/import-shares",
    element: (
      <RequireRole flag="isOffice">
        <ImportShares />
      </RequireRole>
    ),
  },
];
