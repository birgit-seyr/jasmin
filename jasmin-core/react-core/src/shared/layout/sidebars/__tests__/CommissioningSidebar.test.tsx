/**
 * CommissioningSidebar — the entries that depend on a tenant setting or on what
 * the host offers rather than on the viewer's role: the share import (the
 * import-shares mode, unless a host imports the amounts itself), the
 * resellers' commissioning list (a farm that sells to resellers), the
 * delivery-station pages (unless a host keeps its pickup locations itself),
 * among them the station-fee billing (a station that charges a fee), the bulk
 * packing list (bulk packing, or mixed packing with a variation that is packed
 * in bulk), the weight statistics (box packing, or mixed packing with a
 * variation that is packed in boxes, as only boxes are weighed) and the market
 * pages (a farm with markets).
 *
 * Each route is asserted on both sides of its condition: "no link with this
 * href" only proves something once the same href is proven to exist.
 */

import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROLES } from "@shared/auth/roles";
import type { RoleFlags } from "@shared/auth/useRoles";
import { NavigationProvider } from "@shared/contexts/NavigationContext";

import CommissioningSidebar from "../CommissioningSidebar";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Read lazily inside ``getSetting``, so one tenant object answers differently
// per test; a key left out falls through to the caller's default.
const settings = vi.hoisted(() => ({}) as Record<string, unknown>);

// What the deployment offers; a name left out is offered.
const capabilities = vi.hoisted(() => ({}) as Record<string, boolean>);

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in settings ? settings[key] : defaultValue,
  });
  return {
    useTenant: () => tenant,
    useCapability: (name: string) => capabilities[name] ?? true,
    useShareTypes: () => ({ shareTypes: [] }),
    useWashingCleaningVisibility: () => ({
      showsWashing: settings.show_washing !== false,
      showsCleaning: settings.show_cleaning !== false,
    }),
  };
});

// The current and upcoming physical variations; fetched in mixed packing only.
const physical = vi.hoisted(() => ({ variations: [] as unknown[] }));

// The delivery stations, fetched for the station-fee gate.
const stations = vi.hoisted(() => ({ list: [] as unknown[] }));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDeliveryStationsList: (
    _params: unknown,
    options?: { query?: { enabled?: boolean } },
  ) => ({
    data: options?.query?.enabled === false ? undefined : stations.list,
  }),
  useCommissioningShareTypeVariationsList: (
    _params: unknown,
    options?: { query?: { enabled?: boolean } },
  ) => ({
    data: options?.query?.enabled === false ? undefined : physical.variations,
  }),
}));

const officeFlags: RoleFlags = {
  gardener: false,
  office: true,
  staff: true,
  management: false,
  admin: false,
  hasMemberRole: false,
  hasCustomerRole: false,
  canEdit: true,
  isOffice: true,
  canEditCultivation: true,
  isManagement: false,
  isAdmin: false,
  isStaff: true,
  isMemberOnly: false,
  roles: [ROLES.OFFICE],
};

vi.mock("@shared/auth", async () => {
  const { filterByRole } = await import("@shared/auth/filterByRole");
  return { filterByRole, useRoles: () => officeFlags };
});

// Every section open, so its links are in the document.
const sections = [
  "commissioning-amounts",
  "commissioning-planning-share-content",
  "commissioning-resellers",
  "commissioning-harvesting-packing",
  "commissioning-delivery-stations",
  "commissioning-markets",
  "commissioning-data",
];

const shareImport = "/commissioning/import-shares";
const bulkPackingList = "/commissioning/packing-list-bulk";
const resellersCommissioningList = "/commissioning/commissioning-list-resellers";
const deliveryStationPages = [
  "/commissioning/delivery-stations-overview",
  "/commissioning/delivery-stations-details",
  "/commissioning/list-delivery-stations",
  "/commissioning/delivery-tours",
];

function linkedRoutes(): Set<string> {
  const { container } = render(
    <MemoryRouter initialEntries={["/commissioning/forecast"]}>
      <NavigationProvider>
        <CommissioningSidebar openKeys={sections} />
      </NavigationProvider>
    </MemoryRouter>,
  );
  const routes = new Set(
    Array.from(container.querySelectorAll("a[href]"), (link) =>
      link.getAttribute("href") ?? "",
    ),
  );
  container.remove();
  return routes;
}

beforeEach(() => {
  for (const key of Object.keys(settings)) delete settings[key];
  for (const key of Object.keys(capabilities)) delete capabilities[key];
  physical.variations = [];
  stations.list = [];
});

const marketPages = [
  "/commissioning/market-prices",
  "/commissioning/list-market-articles",
  "/commissioning/list-market-product-groups",
  "/commissioning/list-scale-tax-codes",
];
const stationFees = "/commissioning/delivery-station-fees";
const weightStatistics = "/commissioning/statistics-share-weights";
const packedInBulk = { id: "v-bulk", is_packed_bulk: true };
const packedInBoxes = { id: "v-box", is_packed_bulk: false };
const chargingStation = {
  fee_per_box_net: "1.50",
  fee_per_month_net: "0.00",
  fee_per_year_net: "0.00",
};

describe("CommissioningSidebar", () => {
  it("links the resellers' commissioning list and the delivery-station pages, but no share import, by default", () => {
    const routes = linkedRoutes();

    expect(routes.has(resellersCommissioningList)).toBe(true);
    for (const route of deliveryStationPages) {
      expect(routes.has(route), route).toBe(true);
    }
    expect(routes.has(shareImport)).toBe(false);
  });

  it("drops the resellers' commissioning list on a farm that doesn't sell to resellers", () => {
    settings.sells_to_resellers = false;

    const routes = linkedRoutes();

    expect(routes.has(resellersCommissioningList)).toBe(false);
    expect(routes.has("/commissioning/commissioning-list-packing")).toBe(true);
  });

  it("drops the washing and cleaning lists on a farm that hides them", () => {
    settings.show_washing = false;
    settings.show_cleaning = false;

    const routes = linkedRoutes();

    expect(routes.has("/commissioning/washing-list")).toBe(false);
    expect(routes.has("/commissioning/cleaning-list")).toBe(false);
    expect(routes.has("/commissioning/harvesting-list")).toBe(true);
  });

  it("links the market prices and the market data on a farm with markets", () => {
    const routes = linkedRoutes();

    for (const route of marketPages) {
      expect(routes.has(route), route).toBe(true);
    }
  });

  it("drops every market page on a farm without markets", () => {
    settings.has_markets = false;

    const routes = linkedRoutes();

    for (const route of marketPages) {
      expect(routes.has(route), route).toBe(false);
    }
    expect(routes.has("/commissioning/list-storages")).toBe(true);
  });

  it("offers the share import in the import-shares mode", () => {
    settings.uploads_weekly_share_amount = true;

    expect(linkedRoutes().has(shareImport)).toBe(true);
  });

  it("drops the share import where a host imports the amounts itself", () => {
    settings.uploads_weekly_share_amount = true;
    capabilities.manual_share_import = false;

    expect(linkedRoutes().has(shareImport)).toBe(false);
  });

  it("keeps only the members' notices where a host keeps its pickup locations", () => {
    capabilities.delivery_stations = false;

    const routes = linkedRoutes();

    for (const route of deliveryStationPages) {
      expect(routes.has(route), route).toBe(false);
    }
    expect(routes.has("/commissioning/station-notices")).toBe(true);
    expect(routes.has("/commissioning/list-storages")).toBe(true);
  });

  it("gives the members' notices a page of their own where the farm imports its share amounts", () => {
    settings.uploads_weekly_share_amount = true;

    const routes = linkedRoutes();

    expect(routes.has("/commissioning/delivery-stations-details")).toBe(true);
    expect(routes.has("/commissioning/station-notices")).toBe(true);
  });

  it("offers the members' notices on the pickup lists, not on a page of their own", () => {
    const routes = linkedRoutes();

    expect(routes.has("/commissioning/delivery-stations-details")).toBe(true);
    expect(routes.has("/commissioning/station-notices")).toBe(false);
  });

  it("links the bulk packing list in bulk packing", () => {
    settings.packing_mode = "BULK";

    expect(linkedRoutes().has(bulkPackingList)).toBe(true);
  });

  it("drops the tour lists where every share is packed loose", () => {
    settings.packing_mode = "BULK";
    expect(linkedRoutes().has("/commissioning/delivery-stations-overview")).toBe(false);

    settings.packing_mode = "MIXED";
    expect(linkedRoutes().has("/commissioning/delivery-stations-overview")).toBe(true);
  });

  it("links the bulk packing list in mixed packing while a variation is packed in bulk", () => {
    settings.packing_mode = "MIXED";
    physical.variations = [packedInBoxes, packedInBulk];

    expect(linkedRoutes().has(bulkPackingList)).toBe(true);
  });

  it("drops the bulk packing list in mixed packing when no variation is packed in bulk", () => {
    settings.packing_mode = "MIXED";
    physical.variations = [packedInBoxes];

    const routes = linkedRoutes();

    expect(routes.has(bulkPackingList)).toBe(false);
    expect(routes.has("/commissioning/packing-list-boxes")).toBe(true);
  });

  it("links the station-fee billing once a station charges a fee", () => {
    expect(linkedRoutes().has(stationFees)).toBe(false);

    stations.list = [chargingStation];

    expect(linkedRoutes().has(stationFees)).toBe(true);
  });

  it("drops the station-fee billing where a host keeps its pickup locations", () => {
    stations.list = [chargingStation];
    capabilities.delivery_stations = false;

    expect(linkedRoutes().has(stationFees)).toBe(false);
  });

  it("links the weight statistics where shares are packed in boxes", () => {
    settings.packing_mode = "BOXES";
    expect(linkedRoutes().has(weightStatistics)).toBe(true);

    settings.packing_mode = "MIXED";
    physical.variations = [packedInBoxes, packedInBulk];
    expect(linkedRoutes().has(weightStatistics)).toBe(true);
  });

  it("drops the weight statistics where every share is packed in bulk", () => {
    settings.packing_mode = "BULK";
    const routes = linkedRoutes();
    expect(routes.has(weightStatistics)).toBe(false);
    expect(routes.has("/commissioning/statistics-purchase")).toBe(true);

    settings.packing_mode = "MIXED";
    physical.variations = [packedInBulk];
    expect(linkedRoutes().has(weightStatistics)).toBe(false);
  });

  it("lists the commissioning lists before the packing lists", () => {
    settings.packing_mode = "BULK";
    const order = [...linkedRoutes()];
    const bulkOrder = [
      "/commissioning/harvesting-list",
      "/commissioning/commissioning-list-resellers",
      "/commissioning/packing-list-bulk",
    ];
    expect(order.filter((route) => bulkOrder.includes(route))).toEqual(bulkOrder);

    settings.packing_mode = "BOXES";
    const boxesOrder = [
      "/commissioning/harvesting-list",
      "/commissioning/commissioning-list-packing",
      "/commissioning/commissioning-list-resellers",
      "/commissioning/packing-list-boxes",
    ];
    expect([...linkedRoutes()].filter((route) => boxesOrder.includes(route))).toEqual(
      boxesOrder,
    );
  });
});
