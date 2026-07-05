import { lazy } from "react";
import { RequireRole } from "@shared/auth";
import type { AppRoute } from "../types";

// Lazy load all abos components - only loaded when the specific route is accessed
const DashboardAbos = lazy(() => import("@features/abos/pages/DashboardAbos"));
const AbosEmails = lazy(() => import("@features/abos/pages/AbosEmails"));
const Abos = lazy(() => import("@features/abos/pages/Abos"));
const DebitsAbos = lazy(() => import("@features/abos/pages/DebitsAbos"));
const ChargesAbos = lazy(() => import("@features/abos/pages/ChargesAbos"));
const Jokers = lazy(() => import("@features/abos/pages/Jokers"));

const WaitingListAbos = lazy(
  () => import("@features/abos/pages/WaitingListAbos"),
);
const ShareDeliveries = lazy(
  () => import("@features/abos/pages/ShareDeliveries"),
);
const PledgeRound = lazy(() => import("@features/abos/pages/PledgeRound"));

export const abosRoutes: AppRoute[] = [
  {
    path: "/abos/dashboard",
    element: (
      <RequireRole flag="isOffice">
        <DashboardAbos />
      </RequireRole>
    ),
  },
  {
    path: "/abos/abos-emails",
    element: (
      <RequireRole flag="isOffice">
        <AbosEmails />
      </RequireRole>
    ),
  },
  {
    path: "/abos/share-deliveries",
    element: (
      <RequireRole flag="isOffice">
        <ShareDeliveries />
      </RequireRole>
    ),
  },
  {
    path: "/abos/abos",
    element: (
      <RequireRole flag="isOffice">
        <Abos />
      </RequireRole>
    ),
  },

  {
    path: "/abos/debits-abos",
    element: (
      <RequireRole flag="isOffice">
        <DebitsAbos />
      </RequireRole>
    ),
  },
  {
    path: "/abos/charges",
    element: (
      <RequireRole flag="isOffice">
        <ChargesAbos />
      </RequireRole>
    ),
  },
  {
    path: "/abos/jokers",
    element: (
      <RequireRole flag="isOffice">
        <Jokers />
      </RequireRole>
    ),
  },

  {
    path: "/abos/waiting-list-abos",
    element: (
      <RequireRole flag="isOffice">
        <WaitingListAbos />
      </RequireRole>
    ),
  },

  {
    path: "/abos/pledge-round",
    element: (
      <RequireRole flag="isOffice">
        <PledgeRound />
      </RequireRole>
    ),
  },
];
