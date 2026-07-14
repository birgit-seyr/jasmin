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
const ConfigurationShareTypeVariations = lazy(
  () => import("@features/configuration/pages/ConfigurationShareTypeVariations"),
);
const ConfigurationDeliveryDays = lazy(
  () => import("@/features/configuration/pages/ConfigurationDeliveryDays"),
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
const ConfigurationDeliveryExceptions = lazy(
  () =>
    import("@/features/configuration/pages/ConfigurationDeliveryExceptions"),
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
        <ConfigurationDeliveryDays />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/delivery-exceptions",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationDeliveryExceptions />
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
    path: "/configuration/share-type-variations",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationShareTypeVariations />
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
    // Legacy full view (every category) — kept for bookmarked URLs. The sidebar
    // now links to the three category-scoped views below.
    path: "/configuration/email-templates",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationEmailTemplates />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/email-templates/general",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationEmailTemplates
          categories={["users"]}
          titleKey="email_templates.page_title_general"
        />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/email-templates/resellers",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationEmailTemplates
          categories={["resellers"]}
          titleKey="email_templates.page_title_resellers"
        />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/email-templates/members",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationEmailTemplates
          categories={["members", "office"]}
          titleKey="email_templates.page_title_members"
        />
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
