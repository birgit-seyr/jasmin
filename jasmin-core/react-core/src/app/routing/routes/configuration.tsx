import { lazy } from "react";
import {
  RequireCapability,
  RequireMembersAndSubscriptions,
  RequireRole,
} from "@shared/auth";
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
const ConfigurationLabels = lazy(
  () => import("@features/configuration/pages/ConfigurationLabels"),
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
const ListCrates = lazy(
  () => import("@features/commissioning/pages/ListCrates"),
);
const ListPlots = lazy(() => import("@features/commissioning/pages/ListPlots"));
const ListStorages = lazy(
  () => import("@features/commissioning/pages/ListStorages"),
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
      <RequireMembersAndSubscriptions>
        <RequireRole flag="isAdmin">
          <ConfigurationDeliveryExceptions />
        </RequireRole>
      </RequireMembersAndSubscriptions>
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
    path: "/configuration/labels",
    element: (
      <RequireRole flag="isAdmin">
        <ConfigurationLabels />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/members",
    element: (
      <RequireMembersAndSubscriptions>
        <RequireRole flag="isAdmin">
          <ConfigurationMembers />
        </RequireRole>
      </RequireMembersAndSubscriptions>
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
  // The menu links these three for admins only, but the staff who keep them
  // can still open them.
  {
    path: "/configuration/crates",
    element: (
      <RequireRole flag="isStaff">
        <ListCrates />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/storages",
    element: (
      <RequireRole flag="isStaff">
        <ListStorages />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/plots",
    element: (
      <RequireRole flag="isStaff">
        <ListPlots />
      </RequireRole>
    ),
  },
  {
    path: "/configuration/subscriptions",
    element: (
      <RequireMembersAndSubscriptions>
        <RequireRole flag="isAdmin">
          <ConfigurationSubscriptions />
        </RequireRole>
      </RequireMembersAndSubscriptions>
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
    // links to the three category-scoped views below.
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
      <RequireMembersAndSubscriptions>
        <RequireRole flag="isAdmin">
          <ConfigurationEmailTemplates
            categories={["members", "office"]}
            titleKey="email_templates.page_title_members"
          />
        </RequireRole>
      </RequireMembersAndSubscriptions>
    ),
  },
  {
    // The privacy policy every sign-in page links and the records of
    // processing cover every login, so the import-shares mode doesn't close it.
    path: "/configuration/gdpr",
    element: (
      <RequireCapability name="gdpr">
        <RequireRole flag="isAdmin">
          <ConfigurationGDPR />
        </RequireRole>
      </RequireCapability>
    ),
  },
  {
    path: "/configuration/consents",
    element: (
      <RequireMembersAndSubscriptions>
        <RequireRole flag="isAdmin">
          <ConfigurationConsents />
        </RequireRole>
      </RequireMembersAndSubscriptions>
    ),
  },
  {
    path: "/configuration/payments",
    element: (
      <RequireMembersAndSubscriptions>
        <RequireRole flag="isAdmin">
          <ConfigurationPayments />
        </RequireRole>
      </RequireMembersAndSubscriptions>
    ),
  },
  {
    path: "/configuration/users",
    element: (
      <RequireCapability name="user_accounts">
        <RequireRole flag="isAdmin">
          <ConfigurationUsers />
        </RequireRole>
      </RequireCapability>
    ),
  },
];
