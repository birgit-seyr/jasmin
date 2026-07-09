// PurchaseList is a heavy filter-driven page: a WeekSelector + ResellerSelector
// drive a summary retrieve (current + optional next week), the rows flow into an
// EditableTable, and a lazy react-pdf generator hangs off the toolbar. We mock
// every boundary it touches — the generated API module, the two hook barrels
// (which internally call useTenant), the selectors, the table, the PDF
// generator, and the small UI atoms — so the test stays focused on what THIS
// page owns: that it mounts, renders its heading, and does not re-render in a
// loop on initial mount.

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

// Generated API module — every named export the page pulls from it must be
// present, or the unlisted import resolves to undefined and crashes the mount.
// The summary retrieve returns {} (the page reads object fields off it and also
// tolerates non-array), the mutation request fns are plain resolved stubs, and
// the query-key export returns a stable key array.
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDocumentationSummarySummaryRetrieve: () => ({
    // Honest wire shape: the endpoint returns DocumentationSummaryRow[] (the
    // page maps/filters it directly — an object here crashes .filter).
    data: [],
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey: () => [
    "documentation_summary_summary",
  ],
  commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate: vi
    .fn()
    .mockResolvedValue({}),
  commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate:
    vi.fn().mockResolvedValue({}),
}));

// @hooks/index barrel — only the hooks PurchaseList reads from it. The column
// hooks return benign empty configs; the option hooks return identity-ish
// label getters; useNumberFormat returns a simple formatter. These stubs mean
// the page never reaches the real useTenant via this barrel.
vi.mock("@hooks/index", async () => {
  const { useYearWeekState, currentYear, currentWeek } = await import(
    "@hooks/useYearWeekState"
  );
  return {
    useYearWeekState,
    currentYear,
    currentWeek,
    useInvalidateAfterTableMutation: () => ({
      onSaveSuccess: vi.fn(),
      onDeleteSuccess: vi.fn(),
    }),
  useIsMobile: () => false,
  useNoteColumn: () => ({
    noteColumn: { title: "note", dataIndex: "note", key: "note" },
  }),
  useNumberFormat: () => ({
    format: (value: number) => String(value),
  }),
  useVegetableSizeOptions: () => ({
    getVegetableSizeLabel: (value: string) => value,
  }),
  useUnitOptions: () => ({
    getUnitLabel: (value: string) => value,
  }),
  };
});

// useTenant is mocked directly too (belt-and-suspenders): the barrel mocks above
// already short-circuit it, but any deep @hooks/configuration/useTenant import
// would bypass the barrel.
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

// @features/commissioning/hooks barrel — the data + column hooks PurchaseList
// reads. useShareArticleColumn / useAmountUnitSizeColumns internally call
// useTenant in production, so stubbing them here keeps the mount tenant-free.
vi.mock("@features/commissioning/hooks", () => ({
  useSellers: () => ({ sellers: [] }),
  useShareArticles: () => ({ refetch: vi.fn() }),
  useShareArticleColumn: () => ({
    shareArticleColumn: {
      title: "share_article",
      dataIndex: "share_article_name",
      key: "share_article_name",
    },
    handleUnitChange: vi.fn(),
  }),
  useAmountUnitSizeColumns: () => ({ amountUnitSizeColumns: [] }),
}));

vi.mock("@shared/auth", () => ({
  useRoles: () => ({ isOffice: true }),
}));

// Selectors fire their own queries when real (ResellerSelector especially) —
// stub both to inert markers.
vi.mock("@shared/selectors", () => ({
  WeekSelector: () => <div data-testid="week-selector" />,
  ResellerSelector: () => <div data-testid="reseller-selector" />,
}));

// EditableTable is the heavy grid; wrapApiFunctions is a passthrough helper the
// page also imports from this module.
vi.mock("@shared/tables", () => ({
  EditableTable: () => <div data-testid="editable-table" />,
  wrapApiFunctions: (fns: unknown) => fns,
}));

vi.mock("@shared/ui", () => ({
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer-text">{children}</div>
  ),
  PastWarningMessage: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="past-warning">{children}</div>
  ),
  ToolTipIcon: () => <span data-testid="tooltip-icon" />,
}));

vi.mock("@features/commissioning/components", () => ({
  AddShareArticleEntry: () => <div data-testid="add-share-article-entry" />,
}));

// Lazy react-pdf generator — must be stubbed or it pulls in @react-pdf/renderer.
vi.mock("@features/commissioning/pdfs/exports/PurchaseListPDFGenerator", () => ({
  default: () => <div data-testid="purchase-list-pdf-generator" />,
}));

// ── Imports under test ───────────────────────────────────────────────────────

import PurchaseList from "../PurchaseList";

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

describe("PurchaseList (smoke)", () => {
  it("renders without crashing", async () => {
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        <PurchaseList />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("commissioning.purchase_list"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("editable-table")).toBeInTheDocument();
    expect(
      screen.getByTestId("purchase-list-pdf-generator"),
    ).toBeInTheDocument();
  });

  // Render-loop smoke test — PurchaseList drives a filter selector pair, two
  // summary queries, a memo-heavy row processor, and an EditableTable. A
  // healthy mount commits a small handful of times. 80 is a generous ceiling
  // that still catches a real setState-in-render loop (thousands of commits).
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        {profiler.wrap(<PurchaseList />, "purchase-list")}
      </QueryClientProvider>,
    );

    await screen.findByText("commissioning.purchase_list");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
