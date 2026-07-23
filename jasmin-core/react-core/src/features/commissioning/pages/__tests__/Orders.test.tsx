/**
 * Render-loop SMOKE test for the resellers ``Orders`` page.
 *
 * ``Orders`` is a heavy page: it composes ``useOrdersData`` (4 mount
 * queries + a pile of derived useMemo/useState) and ``useOrderColumns``
 * (more queries for offers / articles / crates), renders three eagerly-
 * mounted AntD ``Tabs`` each carrying an ``EditableTable``, plus the
 * week/day/reseller selectors, the OrderInfoPanel and two modals.
 *
 * Per CLAUDE.md heavy pages carry a Profiler-based render-loop smoke
 * test. Rather than wiring every underlying generated hook + PDF helper,
 * we mock the two orchestration hooks (``useOrdersData`` +
 * ``useOrderColumns``) wholesale and stub every heavy child — the test
 * stays focused on "does the page mount and settle without a
 * setState-in-render loop", which is all a smoke test owns.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { profileRenders, flushMicrotasks } from "@/test/profileRenders";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@shared/auth", () => ({
  useRoles: () => ({ isOffice: true, isMember: false, isAdmin: false }),
}));

// ``useTenant().getSetting`` gates the crates tab; return the caller's fallback
// so ``crates_should_be_on_documents`` defaults to true (crates tab shown).
vi.mock("@hooks/index", () => ({
  useTenant: () => ({
    getSetting: (_key: string, fallback?: unknown) => fallback,
  }),
}));

// ── Orchestration hooks (mocked wholesale) ──────────────────────────────────
//
// ``useOrdersData`` owns the page's 4 mount queries + all derived state;
// ``useOrderColumns`` owns the offers/articles/crates column queries.
// Mocking both wholesale keeps the generated API + @react-pdf helpers out
// of the picture entirely — the page just reads the returned fields.

vi.mock("@features/commissioning/hooks/useOrdersData", () => ({
  useOrdersData: () => ({
    // Selection state
    selectedYear: 2026,
    setSelectedYear: vi.fn(),
    selectedWeek: 24,
    setSelectedWeek: vi.fn(),
    selectedDay: 0,
    setSelectedDay: vi.fn(),
    selectedReseller: null,
    setSelectedReseller: vi.fn(),
    activeTab: "offers",
    setActiveTab: vi.fn(),
    showOnlyOrderedOffers: false,
    setShowOnlyOrderedOffers: vi.fn(),

    // Data
    data: [],
    filteredDataOffers: [],
    filteredDataArticles: [],
    filteredDataArticlesCount: 0,
    filteredDataOffersCount: 0,
    dataCrates: [],
    dataCratesCount: 0,
    daysWithOrders: [],
    loading: false,

    // Order state
    orderState: {
      orderId: null,
      orderNumber: null,
      usedOrderNumberPrefix: null,
      isOrderFinalized: false,
      deliveryNoteId: null,
      deliveryNoteNumber: null,
      deliveryNotePrefix: null,
      isDeliveryNoteFinalized: false,
      invoiceId: null,
      invoiceNumber: null,
      invoicePrefix: null,
      hasInvoice: false,
      hasFinalizedInvoice: false,
    },
    orderDays: {
      harvesting_day: null,
      packing_day: null,
      washing_day: null,
    },
    setOrderDays: vi.fn(),
    oddDefaults: {
      default_harvesting_day: null,
      default_packing_day: null,
      default_washing_day: null,
    },
    orderNote: "",
    setOrderNote: vi.fn(),
    totalSum: "---",

    // API
    apiFunctions: { create: vi.fn(), update: vi.fn(), delete: vi.fn() },
    apiFunctionsCrates: { create: vi.fn(), update: vi.fn(), delete: vi.fn() },
    listParams: { year: 2026, delivery_week: 24, day_number: 0, reseller: null },

    // Callbacks
    fetchData: vi.fn(),
    handleDataChange: vi.fn(),
    handleCratesDataChange: vi.fn(),
    handleSaveSuccess: vi.fn(),
    handleFinalizeInvoicesSuccess: vi.fn(),
    handleFinalizeDNSuccess: vi.fn(),
    handleCreateInvoiceSuccess: vi.fn(),
    calculatePricePerUnit: vi.fn(),

    // Summary
    summaryColumns: [],
    summaryDataOffers: {},
    summaryDataArticles: {},
    summaryDataCrates: {},

    // Settings
    defaultTaxRateArticles: 7,
  }),
}));

vi.mock("@features/commissioning/hooks", () => ({
  useOrderColumns: () => ({
    columnsOffers: [],
    columnsArticles: [],
    filteredColumnsCrates: [],
    createCustomSave: () => vi.fn(),
    createCustomSaveOffers: () => vi.fn(),
  }),
}));

// ── Child component / selector / modal / table stubs ─────────────────────────

vi.mock("@features/commissioning/modals", () => ({
  DeliveryNoteModal: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="delivery-note-modal" /> : null,
  InvoiceModal: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="invoice-modal" /> : null,
}));

vi.mock("@shared/selectors", () => ({
  WeekSelector: () => <div data-testid="week-selector" />,
  DaySelector: () => <div data-testid="day-selector" />,
  ResellerSelector: () => <div data-testid="reseller-selector" />,
}));

// EditableTable (eagerly mounted inside every Tabs pane) → tiny stub.
// Re-export the permission gate helpers the page imports from this barrel.
vi.mock("@shared/tables", () => ({
  EditableTable: () => <div data-testid="editable-table" />,
  gatedByPermission: (canModify: boolean) => ({ canModify }),
  gatedByPermissionOnlyEdit: (canModify: boolean) => ({ canModify }),
  SUMMARY_ROW_STYLE: {},
}));

vi.mock("@features/commissioning/components/OrderInfoPanel", () => ({
  OrderInfoPanel: () => <div data-testid="order-info-panel" />,
}));

vi.mock("@features/commissioning/selectors/OrderDaySelectors", () => ({
  OrderDaySelectors: () => <div data-testid="order-day-selectors" />,
}));

// ── Import under test (AFTER the mocks) ──────────────────────────────────────

import Orders from "../Orders";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("Orders (render-loop smoke)", () => {
  it("renders without crashing", async () => {
    const client = makeQueryClient();
    render(
      <QueryClientProvider client={client}>
        <Orders />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("commissioning.orders"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("week-selector")).toBeInTheDocument();
    expect(screen.getByTestId("order-info-panel")).toBeInTheDocument();
  });

  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        {profiler.wrap(<Orders />, "orders")}
      </QueryClientProvider>,
    );

    await screen.findByText("commissioning.orders");
    await flushMicrotasks(50);

    // Healthy mount commits a handful of times (initial + memo settling).
    // A real setState-in-render loop would be in the thousands; 80 is a
    // generous ceiling that still catches the bug.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
