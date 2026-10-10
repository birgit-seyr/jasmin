/**
 * Offers page: a new offer is stamped with the picked offer group, so the
 * grid only lets the office add a row once a group is picked.
 *
 * The page's own hooks are real; the generated API client is the mocking
 * boundary. EditableTable is a stub that exposes its permissions, and the
 * week / offer-group selectors are stubs with plain buttons.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EditableTableProps } from "@shared/tables/BasicEditableTable/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: ["office"] } }),
}));

const IDLE_QUERY = { data: undefined, isFetching: false };
const OFFERS_QUERY = { data: [], isFetching: false };

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningOffersList: (
    _params: unknown,
    options?: { query?: { enabled?: boolean } },
  ) => (options?.query?.enabled === false ? IDLE_QUERY : OFFERS_QUERY),
  getCommissioningOffersListQueryKey: () => ["/api/commissioning/offers/"],
  useCommissioningOfferSendingStatusList: (
    _params: unknown,
    options?: { query?: { enabled?: boolean } },
  ) => (options?.query?.enabled === false ? IDLE_QUERY : OFFERS_QUERY),
  getCommissioningOfferSendingStatusListQueryKey: () => [
    "/api/commissioning/offer_sending_status/",
  ],
  useCommissioningOfferGroupsList: () => ({
    data: [{ id: "og-1", number: 1, name: "Restaurants" }],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCommissioningShareArticlesList: () => ({
    data: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCommissioningCratesList: () => ({
    data: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  commissioningCreateOffersCreate: vi.fn(),
  commissioningOffersCreate: vi.fn(),
  commissioningOffersPartialUpdate: vi.fn(),
  commissioningOffersDestroy: vi.fn(),
  commissioningBulkSendOffersViaEmailCreate: vi.fn(),
  commissioningBulkFinalizeCreate: vi.fn(),
  commissioningBulkCopyOffersToNextWeekCreate: vi.fn(),
  commissioningBulkCopyOffersToOfferGroupCreate: vi.fn(),
}));

vi.mock("@shared/api/generated/tenants/tenants", () => ({
  tenantsSettingsUpdateCurrentSettingsUpdate: vi.fn(),
}));

vi.mock("@shared/selectors", () => ({
  WeekSelector: () => null,
}));

vi.mock("@features/commissioning/selectors/OfferGroupSelector", () => ({
  default: ({
    setSelectedOfferGroup,
  }: {
    setSelectedOfferGroup: (id: string) => void;
  }) => (
    <button type="button" onClick={() => setSelectedOfferGroup("og-1")}>
      pick Restaurants
    </button>
  ),
}));

vi.mock("@features/commissioning/components/AddShareArticleEntry", () => ({
  default: () => null,
}));

vi.mock("@features/commissioning/components/OfferSendingStatusTable", () => ({
  default: () => null,
}));

vi.mock("@shared/ui/JobProgressDrawer", () => ({
  JobProgressDrawer: () => null,
}));

vi.mock("@features/commissioning/pdfs/forResellers/OfferPDFGenerator", () => ({
  default: () => null,
}));

vi.mock("@shared/tables", async () => {
  const { gatedByPermission, READ_ONLY_PERMISSION } = await import(
    "@shared/tables/tablePermissions"
  );
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  return {
    gatedByPermission,
    READ_ONLY_PERMISSION,
    wrapApiFunctions,
    EditableTable: (props: EditableTableProps) => (
      <table
        data-testid="offers-grid"
        data-can-add={String(Boolean(props.permissions?.canAdd))}
        data-can-edit={String(Boolean(props.permissions?.canEdit))}
      />
    ),
  };
});

import Offers from "../Offers";

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Offers />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Offers add gate", () => {
  it("lets the office add no offer while no offer group is picked", () => {
    renderPage();

    const offersGrid = screen.getByTestId("offers-grid");
    expect(offersGrid).toHaveAttribute("data-can-add", "false");
    expect(offersGrid).toHaveAttribute("data-can-edit", "true");
  });

  it("lets the office add an offer once an offer group is picked", async () => {
    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "pick Restaurants" }));

    expect(screen.getByTestId("offers-grid")).toHaveAttribute("data-can-add", "true");
  });
});
