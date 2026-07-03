import { lazy } from "react";

const DashboardWarehouse = lazy(() =>
  import("@features/warehouse/pages/DashboardWarehouse")
);

export const warehouseRoutes = [
  {
    path: "/warehouse/dashboard",
    element: <DashboardWarehouse />,
    meta: {
      title: "app.routes.warehouse_dashboard",
      // requiredRole: [],
      // requiredPermission: []
    },
  },
];
