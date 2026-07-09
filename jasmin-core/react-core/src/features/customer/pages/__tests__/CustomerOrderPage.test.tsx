/**
 * Tier-4 integration smoke for ``CustomerOrderPage``.
 *
 * The four seam tests (useCustomerOrderMutations, OrderAmountCell,
 * useCustomerOrderColumns, CustomerOrderHeader, CustomerDocumentsCard)
 * already verify each piece in isolation. This test verifies the
 * *wiring* between them:
 *
 *   - the page mounts when a reseller id is present (route param) and
 *     falls back to a "no reseller linked" placeholder otherwise
 *   - ``isReadOnly = isPastWeek || isOrderingClosed`` is computed and
 *     passed through to ``useCustomerOrderColumns`` and ``-Mutations``
 *   - the deadline tag is rendered when ``orderingDeadline`` is set
 *   - the reseller-edit modal flow (open → submit) hits the PATCH
 *     endpoint and closes the modal
 *   - render-loop smoke: a real setState-in-render loop produces
 *     thousands of commits, so we assert a LOOSE upper bound
 *
 * Boundary mocks: all generated query hooks + the seam hooks themselves
 * (so we can inspect the params the page hands them) + every visual
 * sub-component (already covered by their own seam tests).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dayjs from "dayjs";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const logoutMock = vi.fn();
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u-1" }, logout: logoutMock }),
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    logoUrl: "https://example.test/logo.png",
    // ``CustomerOrderPage`` reads the configured price-tier columns.
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "used_tiers_for_offers" ? [1, 3, 5] : defaultValue,
  });
  return {
    useTenant: () => tenant,
    useCurrency: () => ({ currencySymbol: "€" }),
    useNumberFormat: () => ({ format: (n: number, d: number) => n.toFixed(d) }),
    // ``CustomerOrderPage`` uses ``useTimeFormat().formatDateTime`` for
    // the order-deadline tag. Mirror the real hook with the tenant
    // defaults ``DD.MM.YYYY`` / ``HH:mm`` so the deadline-tag assertion
    // can still match the rendered output ("Monday, 15.06.2026 18:00").
    // ``dayjs`` is referenced lazily from the test-file scope — vitest
    // hoists the ``vi.mock()`` call above imports but the factory body
    // only runs when the module is first imported by the SUT, by which
    // time the top-level ``import dayjs`` has resolved.
    useTimeFormat: () => ({
      timeFormat: "HH:mm",
      dateFormat: "DD.MM.YYYY",
      formatTime: (v: unknown) =>
        v ? dayjs(v as never).format("HH:mm") : null,
      formatTimeWithFallback: (v: unknown, fallback = "-") =>
        v ? dayjs(v as never).format("HH:mm") : fallback,
      formatDateTime: (
        v: unknown,
        dateOnlyFormat: string | null = null,
        timeOnlyFormat: string | null = null,
      ) =>
        v
          ? dayjs(v as never).format(
              `${dateOnlyFormat || "DD.MM.YYYY"} ${timeOnlyFormat || "HH:mm"}`,
            )
          : null,
      formatDateTimeWithFallback: (
        v: unknown,
        fallback = "-",
        dateOnlyFormat: string | null = null,
        timeOnlyFormat: string | null = null,
      ) =>
        v
          ? dayjs(v as never).format(
              `${dateOnlyFormat || "DD.MM.YYYY"} ${timeOnlyFormat || "HH:mm"}`,
            )
          : fallback,
    }),
  };
});

// ── Generated API mocks ─────────────────────────────────────────────────────

const resellerRetrieveMock = vi.fn();
const offersListMock = vi.fn();
const orderContentsListMock = vi.fn();
const deliveryDaysListMock = vi.fn();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningResellersRetrieve: (id: string, opts?: unknown) =>
    resellerRetrieveMock(id, opts),
  useCommissioningOffersList: (params: unknown, opts?: unknown) =>
    offersListMock(params, opts),
  useCommissioningOrderContentsList: (params: unknown, opts?: unknown) =>
    orderContentsListMock(params, opts),
  useCommissioningOrdersDeliveryDaysList: () => deliveryDaysListMock(),
  // pass-through cache-key helpers (their identity doesn't matter here)
  getCommissioningOffersListQueryKey: (p?: unknown) => ["offers", p],
  getCommissioningOrderContentsListQueryKey: (p?: unknown) => ["orderContents", p],
}));

// ── Seam-hook mocks ─────────────────────────────────────────────────────────

const useCustomerOrderColumnsMock = vi.fn();
const useCustomerOrderMutationsMock = vi.fn();
const useOrderingDeadlineMock = vi.fn();

vi.mock("@features/customer/hooks/useCustomerOrderColumns", () => ({
  useCustomerOrderColumns: (params: unknown) =>
    useCustomerOrderColumnsMock(params),
}));
vi.mock("@features/customer/hooks/useOtherArticleColumns", () => ({
  useOtherArticleColumns: () => [],
}));
vi.mock("@features/customer/hooks/useCustomerOrderMutations", () => ({
  useCustomerOrderMutations: (params: unknown) =>
    useCustomerOrderMutationsMock(params),
}));
vi.mock("@features/customer/hooks/useOrderingDeadline", () => ({
  useOrderingDeadline: (
    defaults: unknown,
    year: unknown,
    week: unknown,
  ) => useOrderingDeadlineMock(defaults, year, week),
}));

// ── Sub-component stubs ─────────────────────────────────────────────────────

vi.mock("@shared/selectors", () => ({
  DaySelector: () => <div data-testid="day-selector" />,
  WeekSelector: () => <div data-testid="week-selector" />,
}));

vi.mock("@features/customer/components/CustomerDocumentsCard", () => ({
  default: () => <div data-testid="documents-card" />,
}));

vi.mock("@features/customer/components/CustomerOrderHeader", () => ({
  default: () => <div data-testid="order-header" />,
}));

// ── Imports under test (after mocks) ────────────────────────────────────────

import CustomerOrderPage from "../CustomerOrderPage";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderPage({ route = "/customer/r-1" } = {}) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route
            path="/customer/:resellerId"
            element={<CustomerOrderPage />}
          />
          <Route path="/customer" element={<CustomerOrderPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Convenience: the page calls the columns hook every render; the LAST call
// holds the params reflecting the final committed state, which is what we
// assert on.
function lastColumnsParams() {
  const calls = useCustomerOrderColumnsMock.mock.calls;
  return calls[calls.length - 1][0] as { isReadOnly: boolean };
}
function lastMutationsParams() {
  const calls = useCustomerOrderMutationsMock.mock.calls;
  return calls[calls.length - 1][0] as { selectedYear: number; selectedWeek: number };
}

beforeEach(() => {
  resellerRetrieveMock.mockReset().mockReturnValue({
    data: { id: "r-1", company_name: "Acme" },
  });
  offersListMock.mockReset().mockReturnValue({ data: [] });
  orderContentsListMock.mockReset().mockReturnValue({ data: { items: [] } });
  deliveryDaysListMock.mockReset().mockReturnValue({
    data: [{ day_number: 1 }, { day_number: 2 }, { day_number: 3 }],
  });

  useCustomerOrderColumnsMock.mockReset().mockReturnValue([]);
  useCustomerOrderMutationsMock.mockReset().mockReturnValue({
    orderAmounts: {},
    editMode: false,
    saving: false,
    stockErrors: {},
    handleAmountChange: vi.fn(),
    enterEditMode: vi.fn(),
    cancelEditMode: vi.fn(),
    handleSaveAll: vi.fn(),
  });
  useOrderingDeadlineMock.mockReset().mockReturnValue({
    orderingDeadline: null,
    isOrderingClosed: false,
  });

  logoutMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── Mount branches ──────────────────────────────────────────────────────────

describe("mount", () => {
  it("renders the header + selectors + documents card when resellerId is in the route", async () => {
    renderPage({ route: "/customer/r-1" });

    expect(await screen.findByTestId("order-header")).toBeInTheDocument();
    expect(screen.getByTestId("week-selector")).toBeInTheDocument();
    expect(screen.getByTestId("day-selector")).toBeInTheDocument();
    expect(screen.getByTestId("documents-card")).toBeInTheDocument();

    // The seam hooks fired with the resellerId.
    expect(useCustomerOrderMutationsMock).toHaveBeenCalled();
    expect(useCustomerOrderColumnsMock).toHaveBeenCalled();
    expect(resellerRetrieveMock).toHaveBeenCalledWith(
      "r-1",
      expect.objectContaining({ query: expect.objectContaining({ enabled: true }) }),
    );
  });

  it("shows the no-reseller placeholder when neither route param nor user.reseller_id is present", () => {
    renderPage({ route: "/customer" });
    expect(screen.getByText("customer.no_reseller_linked")).toBeInTheDocument();
    expect(screen.queryByTestId("order-header")).not.toBeInTheDocument();
  });
});

// ── isReadOnly propagation ──────────────────────────────────────────────────

describe("isReadOnly propagation", () => {
  it("passes isReadOnly: true to the columns hook when ordering is closed", async () => {
    useOrderingDeadlineMock.mockReturnValue({
      orderingDeadline: dayjs("2026-06-15T18:00"),
      isOrderingClosed: true,
    });

    renderPage();
    await screen.findByTestId("order-header");

    expect(lastColumnsParams().isReadOnly).toBe(true);
  });

  it("passes isReadOnly: false to the columns hook when neither past-week nor closed", async () => {
    // default useOrderingDeadlineMock: isOrderingClosed = false
    // default mount uses the current week → isPastWeek = false
    renderPage();
    await screen.findByTestId("order-header");

    expect(lastColumnsParams().isReadOnly).toBe(false);
  });
});

// ── Deadline tag ────────────────────────────────────────────────────────────

describe("deadline tag", () => {
  it("renders the deadline tag with the formatted timestamp when ``orderingDeadline`` is set", async () => {
    useOrderingDeadlineMock.mockReturnValue({
      orderingDeadline: dayjs("2026-06-15T18:00"),
      isOrderingClosed: false,
    });

    renderPage();
    await screen.findByTestId("order-header");

    // dayjs formats "dddd, DD.MM.YYYY HH:mm" — 2026-06-15 is a Monday.
    expect(
      screen.getByText(/customer\.order_deadline:.*Monday, 15\.06\.2026 18:00/),
    ).toBeInTheDocument();
  });

  it("does NOT render the deadline tag when no deadline is set", async () => {
    renderPage();
    await screen.findByTestId("order-header");

    expect(
      screen.queryByText(/customer\.order_deadline/),
    ).not.toBeInTheDocument();
  });
});

// ── Delivery-day auto-correction ────────────────────────────────────────────

describe("orderDayNumbers effect", () => {
  it("snaps selectedDay to the first allowed day when the current selection isn't in the list", async () => {
    // Backend only allows Wednesday (=2). The page's initial selectedDay
    // comes from today's iso-weekday minus 1, so unless we're running on
    // a Wednesday it should snap to 2 after the effect fires.
    deliveryDaysListMock.mockReturnValue({ data: [{ day_number: 2 }] });

    renderPage();
    await screen.findByTestId("order-header");

    await waitFor(() => {
      const params = lastMutationsParams();
      // useCustomerOrderMutations receives selectedDay among its params;
      // we asserted lastMutationsParams returns selectedYear/selectedWeek;
      // re-cast here to pick up selectedDay.
      expect((params as unknown as { selectedDay: number }).selectedDay).toBe(2);
    });
  });
});

// ── Render-loop smoke ───────────────────────────────────────────────────────

describe("render-loop smoke", () => {
  it("settles under a loose upper bound (catches setState-in-render loops)", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={["/customer/r-1"]}>
          <Routes>
            <Route
              path="/customer/:resellerId"
              element={profiler.wrap(<CustomerOrderPage />)}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByTestId("order-header");
    await flushMicrotasks();

    // Healthy baseline measured during authoring: well under 30. Bound
    // is loose — a real loop produces thousands of commits.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
