import { lazy } from "react";

const DashboardStaff = lazy(
  () => import("@features/staff/pages/DashboardStaff"),
);

const WeeklyStaffPlan = lazy(
  () => import("@features/staff/pages/WeeklyStaffPlan"),
);

const ListWeeklyPlanCategories = lazy(
  () => import("@features/staff/pages/ListWeeklyPlanCategory"),
);
const ListEmployees = lazy(() => import("@features/staff/pages/ListEmployees"));
const ListAbsenceCategory = lazy(
  () => import("@features/staff/pages/ListAbsenceCategory"),
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
    path: "/staff/weekly-staff-plan",
    element: <WeeklyStaffPlan />,
    meta: {
      title: "app.routes.weekly_staff_plan",
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
  {
    path: "/staff/absence-categories",
    element: <ListAbsenceCategory />,
    meta: {
      title: "app.routes.absence_categories",
      // requiredRole: [],
      // requiredPermission: []
    },
  },
];
