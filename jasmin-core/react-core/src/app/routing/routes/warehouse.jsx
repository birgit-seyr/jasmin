import { lazy } from "react";
import { RequireRole } from "@shared/auth";

const DashboardWarehouse = lazy(() =>
  import("@features/warehouse/pages/DashboardWarehouse")
);

export const warehouseRoutes = [
  {
    path: "/warehouse/dashboard",
    element: (
      <RequireRole flag="isStaff">
        <DashboardWarehouse />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.warehouse_dashboard",
    },
  },
];
