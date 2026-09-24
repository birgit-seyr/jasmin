import { lazy } from "react";
import { RequireRole } from "@shared/auth";

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
    element: (
      <RequireRole flag="isStaff">
        <DashboardStaff />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.staff_dashboard",
    },
  },

  {
    path: "/staff/weekly-staff-plan",
    element: (
      <RequireRole flag="isStaff">
        <WeeklyStaffPlan />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.weekly_staff_plan",
    },
  },

  {
    path: "/staff/saturday-shifts",
    element: (
      <RequireRole flag="isStaff">
        <SaturdayShifts />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.saturday_shifts",
    },
  },
  {
    path: "/staff/weekly-plan-categories",
    element: (
      <RequireRole flag="isStaff">
        <ListWeeklyPlanCategories />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.weekly_plan_categories",
    },
  },
  {
    path: "/staff/employees",
    element: (
      <RequireRole flag="isStaff">
        <ListEmployees />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.employees",
    },
  },
  {
    path: "/staff/absence-categories",
    element: (
      <RequireRole flag="isStaff">
        <ListAbsenceCategory />
      </RequireRole>
    ),
    meta: {
      title: "app.routes.absence_categories",
    },
  },
];
