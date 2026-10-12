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

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { RowSaveRefused } from "@shared/tables/BasicEditableTable/RowSaveRefused";
import type { EditableTableProps } from "@shared/tables/BasicEditableTable/types";
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

// The tab on screen, the order's crate lines and what is being read, per test.
const ordersState = vi.hoisted(() => ({
  activeTab: "offers",
  dataCrates: [] as Record<string, unknown>[],
  loading: false,
  cratesLoading: false,
  selectedReseller: null as string | null,
  orderDays: {
    harvesting_day: null,
    packing_day: null,
    washing_day: null,
    cleaning_day: null,
  } as Record<string, number | null>,
}));

vi.mock("@features/commissioning/hooks/useOrdersData", () => ({
  useOrdersData: () => ({
    // Selection state
    selectedYear: 2026,
    setSelectedYear: vi.fn(),
    selectedWeek: 24,
    setSelectedWeek: vi.fn(),
    selectedDay: 0,
    setSelectedDay: vi.fn(),
    selectedReseller: ordersState.selectedReseller,
    setSelectedReseller: vi.fn(),
    activeTab: ordersState.activeTab,
    setActiveTab: vi.fn(),
    showOnlyOrderedOffers: false,
    setShowOnlyOrderedOffers: vi.fn(),

    // Data
    data: [],
    filteredDataOffers: [],
    filteredDataArticles: [],
    filteredDataArticlesCount: 0,
    filteredDataOffersCount: 0,
    dataCrates: ordersState.dataCrates,
    dataCratesCount: ordersState.dataCrates.length,
    daysWithOrders: [],
    loading: ordersState.loading,
    cratesLoading: ordersState.cratesLoading,

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
    orderDays: ordersState.orderDays,
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
    handleFinalizeDeliveryNotesSuccess: vi.fn(),
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

// EditableTable (one inside the Tabs pane on screen) → tiny stub that keeps
// the props of the crate table, the one focusing the crate type, and of the
// order-line table on screen. Re-export the permission gate helpers the page
// imports from this barrel.
const tables = vi.hoisted(() => ({
  crates: null as unknown,
  orderLines: null as unknown,
}));
vi.mock("@shared/tables", () => ({
  EditableTable: (props: { focusIndex?: string }) => {
    if (props.focusIndex === "crate_type_name") tables.crates = props;
    else tables.orderLines = props;
    return <div data-testid="editable-table" />;
  },
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

function renderOrders() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <Orders />
    </QueryClientProvider>,
  );
}

function crateTable(): EditableTableProps {
  if (!tables.crates) throw new Error("The crate table never rendered");
  return tables.crates as EditableTableProps;
}

beforeEach(() => {
  ordersState.activeTab = "offers";
  ordersState.dataCrates = [];
  ordersState.loading = false;
  ordersState.cratesLoading = false;
  ordersState.selectedReseller = null;
  ordersState.orderDays = {
    harvesting_day: null,
    packing_day: null,
    washing_day: null,
    cleaning_day: null,
  };
  tables.crates = null;
  tables.orderLines = null;
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("Orders crate lines", () => {
  // Small crates ordered at two prices: two lines of one crate type, each
  // named by a crate row of its own.
  const SMALL_CRATES_AT_125 = {
    id: "ct-small_row-1",
    crate_type: "ct-small",
    crate_type_name: "Small",
    amount: 4,
    price_per_unit: "1.25",
    rabatt: 0,
    tax_rate: 19,
  };
  const SMALL_CRATES_AT_150 = {
    ...SMALL_CRATES_AT_125,
    id: "ct-small_row-4",
    amount: 2,
    price_per_unit: "1.50",
  };

  it("refuses a new crate line of a crate type the order lists, while each line of that type saves on its own", async () => {
    ordersState.activeTab = "crates";
    ordersState.dataCrates = [SMALL_CRATES_AT_125, SMALL_CRATES_AT_150];
    renderOrders();
    await screen.findByText("commissioning.orders");
    const crates = crateTable();

    let refusal: unknown;
    try {
      crates.customSave!({ crate_type: "ct-small", amount: 3 }, { key: -1 });
    } catch (error) {
      refusal = error;
    }
    expect(refusal).toBeInstanceOf(RowSaveRefused);
    expect(refusal).toMatchObject({
      message: "validation.unique.crate_type",
      fieldErrors: { crate_type_name: "validation.unique.crate_type" },
    });

    // The table holds no crate-type uniqueness of its own, which would refuse
    // either line of the type.
    expect(crates.uniqueCheck).toBeUndefined();
    expect(
      crates.customSave!(
        { crate_type: "ct-small", amount: 3 },
        { ...SMALL_CRATES_AT_150, key: "ct-small_row-4" },
      ),
    ).toEqual({
      crate_type: "ct-small",
      amount: 3,
      year: 2026,
      delivery_week: 24,
      day_number: 0,
      reseller: null,
    });
  });

  it("spins only the crate table while only the crate list is read again", async () => {
    ordersState.cratesLoading = true;
    ordersState.activeTab = "articles";
    const articlesTab = renderOrders();
    await screen.findByText("commissioning.orders");
    // A spinner over the order lines would catch the click on the next line.
    expect(tables.orderLines).toMatchObject({ loading: false });
    articlesTab.unmount();

    ordersState.activeTab = "crates";
    renderOrders();
    await screen.findByText("commissioning.orders");
    expect(crateTable().loading).toBe(true);
  });
});

describe("Orders without the days a new order needs", () => {
  it("adds and edits no line of a new order while one of its days is missing", async () => {
    ordersState.activeTab = "articles";
    ordersState.selectedReseller = "reseller-1";
    ordersState.orderDays = {
      harvesting_day: 1,
      packing_day: 3,
      washing_day: null,
      cleaning_day: 2,
    };
    renderOrders();
    await screen.findByText("commissioning.orders");

    expect(tables.orderLines).toMatchObject({
      permissions: { canModify: false },
    });
  });

  it("lets the office add lines once every day is picked", async () => {
    ordersState.activeTab = "articles";
    ordersState.selectedReseller = "reseller-1";
    ordersState.orderDays = {
      harvesting_day: 1,
      packing_day: 3,
      washing_day: 2,
      cleaning_day: 2,
    };
    renderOrders();
    await screen.findByText("commissioning.orders");

    expect(tables.orderLines).toMatchObject({
      permissions: { canModify: true },
    });
  });
});

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
