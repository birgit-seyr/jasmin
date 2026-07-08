import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

const DashboardMembers = lazy(
  () => import("@/features/members/pages/DashboardMembers"),
);
const Members = lazy(() => import("@features/members/pages/Members"));
const MemberDetail = lazy(() => import("@features/members/pages/MemberDetail"));
const DebitsMembers = lazy(
  () => import("@features/members/pages/DebitsMembers"),
);

const MemberLoans = lazy(() => import("@features/members/pages/MemberLoans"));
const StaffDetail = lazy(() => import("@features/members/pages/StaffDetail"));
const SepaMandates = lazy(() => import("@features/members/pages/SepaMandates"));
// Member-lifecycle / communication views that live in the Members feature: the
// GDPR deletion-request queue and the email history are per-member operational
// tools, not tenant settings. (The GDPR *settings* — privacy policy + Art. 30
// VVT — stay on the Configuration GDPR page.)
const GdprDeletionRequests = lazy(
  () => import("@features/members/pages/GdprDeletionRequests"),
);
const EmailLog = lazy(() => import("@/features/members/pages/EmailLog"));

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
    path: "/members/sepa-mandates",
    element: (
      <RequireRole flag="isOffice">
        <SepaMandates />
      </RequireRole>
    ),
  },
  {
    path: "/members/email-log",
    element: (
      <RequireRole flag="isOffice">
        <EmailLog />
      </RequireRole>
    ),
  },
  {
    path: "/members/data-protection",
    element: (
      <RequireRole flag="isAdmin">
        <GdprDeletionRequests />
      </RequireRole>
    ),
  },
];
