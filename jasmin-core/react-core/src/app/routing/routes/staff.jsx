import { lazy } from "react";

const DashboardStaff = lazy(
  () => import("@features/staff/pages/DashboardStaff"),
);

const ListWeeklyPlanCategories = lazy(
  () => import("@features/staff/pages/ListWeeklyPlanCategory.jsx"),
);
const ListEmployees = lazy(
  () => import("@features/staff/pages/ListEmployees.jsx"),
);
const SaturdayShifts = lazy(
  () => import("@features/staff/pages/SaturdayShifts.jsx"),
);

export const staffRoutes = [
  {
    path: "/staff/dashboard",
    element: <DashboardStaff />,
    meta: {
      title: "app.routes.staff_dashboard",
      // requiredRole: [],
      // requiredPermission: []
    },
  },

  {
    path: "/staff/saturday-shifts",
    element: <SaturdayShifts />,
    meta: {
      title: "app.routes.saturday_shifts",
      // requiredRole: [],
      // requiredPermission: []
    },
  },
  {
    path: "/staff/weekly-plan-categories",
    element: <ListWeeklyPlanCategories />,
    meta: {
      title: "app.routes.weekly_plan_categories",
      // requiredRole: [],
      // requiredPermission: []
    },
  },
  {
    path: "/staff/employees",
    element: <ListEmployees />,
    meta: {
      title: "app.routes.employees",
      // requiredRole: [],
      // requiredPermission: []
    },
  },
];
