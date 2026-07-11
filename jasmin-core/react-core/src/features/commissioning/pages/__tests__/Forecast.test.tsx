// Forecast is a heavy page with a TWO-PHASE gated render: ~10 hooks compose an
// ``isComponentReady`` gate, and the main forecast list query is only enabled
// once five gating queries (share options, share articles, plots, offer groups,
// share-type variations + their derived columns) have resolved. Until the gate
// opens the page renders an empty placeholder div — so this test mocks every
// gating hook to return RESOLVED, non-undefined data synchronously, then asserts
// the page mounts past the gate (the stubbed EditableTable testid is the anchor)
// and doesn't re-render in a loop. We mock the API boundary + every heavy child
// rather than going through MSW.

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

// The generated API boundary. Forecast imports five operation fns + the
// query-key helper + the list hook. The list hook is gated behind
// ``isComponentReady`` but we still return a fully-resolved (non-undefined)
// shape so the page never sits in a loading state.
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningBulkFinalizeCreate: vi.fn().mockResolvedValue({}),
  commissioningForecastBulkCopyToNextWeekCreate: vi.fn().mockResolvedValue({}),
  commissioningForecastCreate: vi.fn().mockResolvedValue({}),
  commissioningForecastDestroy: vi.fn().mockResolvedValue({}),
  commissioningForecastPartialUpdate: vi.fn().mockResolvedValue({}),
  getCommissioningForecastListQueryKey: () => ["forecast-list"],
  useCommissioningForecastList: () => ({
    data: [],
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

// The models module is type-only for ``Forecast`` / ``CommissioningForecastListParams``
// but ``ShareTypeEnum`` is a real runtime value — leave it real (cheap enum).

// @hooks barrel — every hook Forecast reads from it. The tenant mock keeps
// ``getSetting`` permissive (returns the default arg), so ``has_markets`` /
// ``sells_to_resellers`` fall through to their ``true`` defaults.
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  const { useYearWeekState, currentYear, currentWeek } = await import(
    "@hooks/useYearWeekState"
  );
  return {
    useYearWeekState,
    currentYear,
    currentWeek,
    useTenant: () => tenant,
    useIsMobile: () => false,
    useNoteColumn: () => ({
      noteColumn: { title: "note", dataIndex: "note", key: "note" },
    }),
    // activeShareOptions is read for ``fruit_and_veg_shares_are_separate`` —
    // an empty object makes it ``?? false`` so the (heavier) fruit branch and
    // its second variations query are skipped.
    useActiveShareOptions: () => ({ activeShareOptions: {} }),
    useTableRowSelection: () => ({
      selectedRowKeys: [],
      setSelectedRowKeys: vi.fn(),
      onSelectedRowsChange: vi.fn(),
      rowSelection: { type: "checkbox" },
    }),
    useInvalidateAfterTableMutation: () => ({
      onSaveSuccess: vi.fn(),
      onDeleteSuccess: vi.fn(),
      recentlyAddedIds: new Set<string>(),
    }),
    // Size-label getter for the per-variation column headers ("für GANZ").
    useShareTypeVariationSizeOptions: () => ({
      getShareTypeVariationSizeLabel: (s: string) => s,
    }),
  };
});

// Commissioning feature hooks — the GATING hooks. Every one must resolve to a
// non-undefined value (and ``amountUnitSizeColumns`` must be a NON-EMPTY array)
// or ``isComponentReady`` never flips and the page stays an empty div.
vi.mock("@features/commissioning/hooks", () => ({
  useShareArticles: () => ({ shareArticles: [], refetch: vi.fn() }),
  usePlots: () => ({ plots: [], countPlots: 0 }),
  useOfferGroups: () => ({ offerGroups: [], offerGroupsCount: 0 }),
  useShareTypeVariations: () => ({
    shareTypeVariations: [],
    shareTypeVariationsCount: 0,
  }),
  useFinalColumn: () => ({
    finalColumn: { title: "final", dataIndex: "is_finalized", key: "final" },
  }),
  useShareArticleColumn: () => ({
    shareArticleColumn: {
      title: "article",
      dataIndex: "share_article",
      key: "share_article",
    },
  }),
  useAmountUnitSizeColumns: () => ({
    amountUnitSizeColumns: [
      { title: "amount", dataIndex: "amount", key: "amount" },
    ],
  }),
  // Column-builder hook extracted from the page (FE-11); the table is stubbed
  // below, so an empty column set is enough for the render/smoke tests.
  useForecastColumns: () => [],
}));

vi.mock("@shared/auth", () => ({
  useRoles: () => ({ canEdit: true }),
}));

vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn(), user: { roles: ["office"] } }),
}));

// EditableTable → testid stub. Re-export the helpers Forecast imports from this
// module as plain passthroughs so the page's ``gatedByPermission`` /
// ``wrapApiFunctions`` calls don't blow up.
vi.mock("@shared/tables", () => ({
  EditableTable: () => <div data-testid="editable-table" />,
  gatedByPermission: (canEdit: boolean) => ({ canEdit }),
  wrapApiFunctions: (fns: unknown) => fns,
}));

// Selectors fire their own queries — stub them.
vi.mock("@shared/selectors", () => ({
  WeekSelector: () => <div data-testid="week-selector" />,
}));

// Shared UI widgets used past the gate.
vi.mock("@shared/ui", () => ({
  BulkActionButton: () => <div data-testid="bulk-action-button" />,
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer-text">{children}</div>
  ),
  PastWarningMessage: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="past-warning">{children}</div>
  ),
  ToolTipIcon: () => <span data-testid="tooltip-icon" />,
}));

// AddShareArticleEntry unconditionally mounts ShareArticleModal (which fires a
// share_options/active query) — stub it.
vi.mock("@features/commissioning/components", () => ({
  AddShareArticleEntry: () => <div data-testid="add-share-article-entry" />,
}));

// Mobile card factory passed to EditableTable — never invoked (EditableTable is
// stubbed) but the import must resolve.
vi.mock("@features/commissioning/components/mobileCards", () => ({
  ForecastMobileCard: () => <div data-testid="forecast-mobile-card" />,
}));

// ── Imports under test ───────────────────────────────────────────────────────

import Forecast from "../Forecast";

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

describe("Forecast (smoke)", () => {
  it("renders without crashing once the gating data resolves", async () => {
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        <Forecast />
      </QueryClientProvider>,
    );

    // The stubbed EditableTable only mounts AFTER the isComponentReady gate
    // opens — it's the most reliable "past the gate" anchor.
    expect(await screen.findByTestId("editable-table")).toBeInTheDocument();
    expect(screen.getByTestId("week-selector")).toBeInTheDocument();
    expect(
      screen.getByTestId("add-share-article-entry"),
    ).toBeInTheDocument();
  });

  // Render-loop smoke test — Forecast composes ~10 hooks + builds a large memo'd
  // column config gated behind isComponentReady. A healthy mount commits a
  // handful of times (initial + the gate flipping + memo settling). 80 is a
  // generous ceiling that still catches a real setState-in-render loop (which
  // produces thousands of commits).
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        {profiler.wrap(<Forecast />, "forecast")}
      </QueryClientProvider>,
    );

    await screen.findByTestId("editable-table");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
