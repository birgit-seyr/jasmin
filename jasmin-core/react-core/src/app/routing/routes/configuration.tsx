import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

const DashboardConfiguration = lazy(
  () => import("@features/configuration/pages/DashboardConfiguration"),
);
const ConfigurationGeneral = lazy(
  () => import("@features/configuration/pages/ConfigurationGeneral"),
);
const ConfigurationMembers = lazy(
  () => import("@features/configuration/pages/ConfigurationMembers"),
);
const ConfigurationCommissioning = lazy(
  () => import("@features/configuration/pages/ConfigurationCommissioning"),
);
const ConfigurationSubscriptions = lazy(
  () => import("@features/configuration/pages/ConfigurationSubscriptions"),
);
const ConfigurationTimeManagement = lazy(
  () => import("@features/configuration/pages/ConfigurationTimeManagement"),
);
const ConfigurationApp = lazy(
  () => import("@features/configuration/pages/ConfigurationApp"),
);
const ConfigurationResellerDocuments = lazy(
  () => import("@features/configuration/pages/ConfigurationResellerDocuments"),
);
const ConfigurationEmail = lazy(
  () => import("@features/configuration/pages/ConfigurationEmail"),
);
const ConfigurationEmailTemplates = lazy(
  () => import("@features/configuration/pages/ConfigurationEmailTemplates"),
);
const ConfigurationEmailLog = lazy(
  () => import("@features/configuration/pages/ConfigurationEmailLog"),
);
const ConfigurationGDPR = lazy(
  () => import("@features/configuration/pages/ConfigurationGDPR"),
);
const ConfigurationConsents = lazy(
  () => import("@features/configuration/pages/ConfigurationConsents"),
);
const ConfigurationPayments = lazy(
  () => import("@features/configuration/pages/ConfigurationPayments"),
);
const ConfigurationUsers = lazy(
  () => import("@features/configuration/pages/ConfigurationUsers"),
);

export const configurationRoutes: AppRoute[] = [
  {
    path: "/configuration/general",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationGeneral />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/app",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationApp />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/time-management",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationTimeManagement />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/dashboard",
    element: (
      <RequireRole flag="isAdmin">
        <DashboardConfiguration />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/reseller-documents",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationResellerDocuments />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/members",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationMembers />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/commissioning",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationCommissioning />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/subscriptions",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationSubscriptions />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/email",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationEmail />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/email-templates",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationEmailTemplates />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/email-log",
    element: (
      <RequireRole flag="isOffice">
        <ConfigurationEmailLog />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/gdpr",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationGDPR />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/consents",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationConsents />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/payments",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationPayments />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/users",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationUsers />
      </RequireRole>
    ),
  },
];
