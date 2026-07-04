import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

const DashboardMembers = lazy(
  () => import("@features/members/pages/DashboardMembers"),
);
const Members = lazy(() => import("@features/members/pages/Members"));
const MemberDetail = lazy(() => import("@features/members/pages/MemberDetail"));
const DebitsMembers = lazy(
  () => import("@features/members/pages/DebitsMembers"),
);
const OverviewMembers = lazy(
  () => import("@features/members/pages/OverviewMembers"),
);

const MemberLoans = lazy(() => import("@features/members/pages/MemberLoans"));
const StaffDetail = lazy(() => import("@features/members/pages/StaffDetail"));
const SepaMandates = lazy(() => import("@features/members/pages/SepaMandates"));
const StatisticsPage = lazy(
  () => import("@features/members/pages/StatisticsPage"),
);

export const membersRoutes: AppRoute[] = [
  {
    path: "/members/dashboard",
    element: (
      <RequireRole flag="isOffice">
        <DashboardMembers />
      </RequireRole>
    ),
  },

  {
    path: "/members/staff-detail",
    element: (
      <RequireRole flag="isOffice">
        <StaffDetail />
      </RequireRole>
    ),
  },
  {
    path: "/members/members",
    element: (
      <RequireRole flag="isOffice">
        <Members />
      </RequireRole>
    ),
  },
  {
    path: "/members/members/:id",
    element: (
      <RequireRole flag="isOffice">
        <MemberDetail />
      </RequireRole>
    ),
  },

  {
    path: "/members/debits-members",
    element: (
      <RequireRole flag="isOffice">
        <DebitsMembers />
      </RequireRole>
    ),
  },
  {
    path: "/members/loans",
    element: (
      <RequireRole flag="isOffice">
        <MemberLoans />
      </RequireRole>
    ),
  },
  {
    path: "/members/overview-members",
    element: (
      <RequireRole flag="isOffice">
        <OverviewMembers />
      </RequireRole>
    ),
  },
  {
    path: "/members/sepa-mandates",
    element: (
      <RequireRole flag="isOffice">
        <SepaMandates />
      </RequireRole>
    ),
  },
  {
    path: "/members/statistics",
    element: (
      <RequireRole flag="isOffice">
        <StatisticsPage />
      </RequireRole>
    ),
  },
];
