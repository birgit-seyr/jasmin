import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

const DashboardEconomics = lazy(
  () => import("@features/economics/pages/DashboardEconomics"),
);
const KeyData = lazy(() => import("@features/economics/pages/KeyData"));
const BusinessPlan = lazy(
  () => import("@features/economics/pages/BusinessPlan"),
);
const Budgets = lazy(() => import("@features/economics/pages/Budgets"));

export const economicsRoutes: AppRoute[] = [
  {
    path: "/economics/dashboard",
    element: (
      <RequireRole flag="isManagement">
        <DashboardEconomics />
      </RequireRole>
    ),
  },

  {
    path: "/economics/key_data",
    element: (
      <RequireRole flag="isManagement">
        <KeyData />
      </RequireRole>
    ),
  },
  {
    path: "/economics/businessplan",
    element: (
      <RequireRole flag="isManagement">
        <BusinessPlan />
      </RequireRole>
    ),
  },
  {
    path: "/economics/budgets",
    element: (
      <RequireRole flag="isManagement">
        <Budgets />
      </RequireRole>
    ),
  },
];
