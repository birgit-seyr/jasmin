/**
 * PurchaseList: the week's purchase list, with next week's needs merged in
 * while "include next week" is ticked.
 *
 * The generated API client is the mocking boundary. The summary hook returns
 * module-level constants, the way a settled TanStack query hands back the same
 * data object on every render, and tells the two weeks apart by the call
 * shape: the selected week's query takes no options, next week's is gated by
 * `enabled`. The two save endpoints are spies. EditableTable is a stub that
 * records its props, so the tests read the rows the page hands the table and
 * drive the table's save hooks the way its save does: `customSave` with the
 * form values and the row, then `apiFunctions.update` under the row's key.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41) before the
 * imports run as well as before every test. The page reads "today" when it
 * mounts, so a test that moves the clock before rendering opens on that week.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type {
  EditableTableProps,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { profileRenders, flushMicrotasks } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

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

const api = vi.hoisted(() => ({
  summaryRetrieve: vi.fn(),
  create: vi.fn(),
  partialUpdate: vi.fn(),
}));

const SUMMARY_URL = "/api/commissioning/documentation_summary/summary/";

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDocumentationSummarySummaryRetrieve: (
    params: unknown,
    options?: unknown,
  ) => api.summaryRetrieve(params, options),
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey: (
    params?: unknown,
  ) => [SUMMARY_URL, ...(params ? [params] : [])],
  commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate: (
    body: unknown,
  ) => api.create(body),
  commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate:
    (id: string, body: unknown) => api.partialUpdate(id, body),
}));

// @hooks/index barrel — only the hooks PurchaseList reads from it. The column
// hooks return benign empty configs; the option hooks return identity-ish
// label getters; useNumberFormat returns a simple formatter. These stubs mean
// the page never reaches the real useTenant via this barrel.
vi.mock("@hooks/index", async () => {
  const { useYearWeekState } = await import("@hooks/useYearWeekState");
  return {
    useYearWeekState,
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

// The selectors fire their own queries when real; the stubs are buttons that
// set the one week and the one supplier the tests pick.
vi.mock("@shared/selectors", () => ({
  WeekSelector: ({
    setSelectedYear,
    setSelectedWeek,
  }: {
    setSelectedYear: (year: number) => void;
    setSelectedWeek: (week: number | null) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        setSelectedYear(2026);
        setSelectedWeek(52);
      }}
    >
      pick 2026 week 52
    </button>
  ),
  ResellerSelector: ({
    setSelectedReseller,
  }: {
    setSelectedReseller: (seller: string | null) => void;
  }) => (
    <button type="button" onClick={() => setSelectedReseller("seller-picked")}>
      pick supplier
    </button>
  ),
}));

// The grid's props from its latest render.
const table = vi.hoisted(() => ({ props: null as unknown }));

vi.mock("@shared/tables", async () => {
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  return {
    EditableTable: (props: EditableTableProps) => {
      table.props = props;
      return <div data-testid="editable-table" />;
    },
    wrapApiFunctions,
  };
});

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

// ── Fixtures ─────────────────────────────────────────────────────────────────

const summaryRow = (fields: Record<string, unknown>) => ({
  unit: "KG",
  size: "M",
  note: "",
  theoretical_id: null,
  additional_id: null,
  theoretical_purchase_amount: 0,
  additional_theoretical_purchase_amount: 0,
  purchase_amount: null,
  theoretical_current_stock: 0,
  amount_per_pu: "2.00",
  seller: null,
  ...fields,
});

// The selected week: apples with a planned amount, and carrots held without
// any amount, which the list leaves out on its own.
const CURRENT_ROWS = [
  summaryRow({
    id: "cur-a",
    share_article: "art-a",
    share_article_name: "Apples",
    theoretical_purchase_amount: 4,
    note: "apples this week",
  }),
  summaryRow({
    id: "cur-c",
    share_article: "art-c",
    share_article_name: "Carrots",
    note: "this week",
  }),
];

// Next week: apples and carrots again, beans in size L and dill, which the
// selected week lacks.
const NEXT_ROWS = [
  summaryRow({
    id: "next-a",
    share_article: "art-a",
    share_article_name: "Apples",
    theoretical_purchase_amount: 5,
  }),
  summaryRow({
    id: "next-b",
    share_article: "art-b",
    share_article_name: "Beans",
    size: "L",
    theoretical_purchase_amount: 3,
    additional_theoretical_purchase_amount: 2,
    note: "next note",
    seller: "seller-next",
    amount_per_pu: "2.50",
    theoretical_id: "theo-next-b",
    additional_id: "add-next-b",
  }),
  summaryRow({
    id: "next-c",
    share_article: "art-c",
    share_article_name: "Carrots",
    theoretical_purchase_amount: 3,
  }),
  summaryRow({
    id: "next-d",
    share_article: "art-d",
    share_article_name: "Dill",
    unit: "PCS",
    theoretical_purchase_amount: 1,
  }),
];

const settled = (data: unknown) => ({
  data,
  isLoading: false,
  isFetching: false,
  error: null,
  refetch: vi.fn(),
});
const SELECTED_WEEK = settled(CURRENT_ROWS);
const NEXT_WEEK = settled(NEXT_ROWS);
const IDLE = settled(undefined);

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderPage() {
  const client = makeQueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <PurchaseList />
    </QueryClientProvider>,
  );
  return { invalidateSpy };
}

function grid(): EditableTableProps {
  if (!table.props) throw new Error("the purchase table never rendered");
  return table.props as EditableTableProps;
}

const rowsOf = (shareArticle: string) =>
  (grid().initialData ?? []).filter(
    (row) => row.share_article === shareArticle,
  );

function rowOf(shareArticle: string): TableRecord {
  const rows = rowsOf(shareArticle);
  if (rows.length !== 1) {
    throw new Error(`${rows.length} rows for ${shareArticle}, expected one`);
  }
  return rows[0];
}

async function includeNextWeek() {
  await userEvent.click(
    screen.getByRole("checkbox", { name: "commissioning.include_next_week" }),
  );
}

/** What the table's save sends for `row`: customSave, then update by key. */
async function save(row: TableRecord, formValues: Record<string, unknown>) {
  const record = { ...row, key: String(row.id) };
  const payload = grid().customSave!(formValues, record);
  if (!payload) throw new Error("customSave refused the row");
  await grid().apiFunctions!.update!(record.key, payload);
}

const selectedWeekParams = () =>
  api.summaryRetrieve.mock.calls
    .filter(([, options]) => options === undefined)
    .map(([params]) => params as Record<string, unknown>);

function lastNextWeekParams(): Record<string, unknown> {
  const calls = api.summaryRetrieve.mock.calls.filter(
    ([, options]) => options !== undefined,
  );
  if (calls.length === 0) throw new Error("next week was never asked for");
  return calls[calls.length - 1][0] as Record<string, unknown>;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  table.props = null;
  api.summaryRetrieve
    .mockReset()
    .mockImplementation(
      (_params: unknown, options?: { query?: { enabled?: boolean } }) => {
        if (options === undefined) return SELECTED_WEEK;
        return options.query?.enabled === false ? IDLE : NEXT_WEEK;
      },
    );
  api.create.mockReset().mockResolvedValue({ id: "purchase-new" });
  api.partialUpdate.mockReset().mockResolvedValue({ id: "cur-a" });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("PurchaseList (smoke)", () => {
  it("renders without crashing", async () => {
    renderPage();

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

    render(
      <QueryClientProvider client={makeQueryClient()}>
        {profiler.wrap(<PurchaseList />, "purchase-list")}
      </QueryClientProvider>,
    );

    await screen.findByText("commissioning.purchase_list");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("PurchaseList opening week", () => {
  // The module loaded in week 41 of 2026, so this shows that the page reads
  // the date when it opens.
  it("opens on today's week when it opens after New Year", async () => {
    vi.setSystemTime(new Date(2027, 0, 4, 12, 0));
    renderPage();

    expect(selectedWeekParams()[0]).toMatchObject({
      year: 2027,
      delivery_week: 1,
    });
    await includeNextWeek();
    expect(lastNextWeekParams()).toMatchObject({ year: 2027, delivery_week: 2 });
  });
});

describe("PurchaseList with next week included", () => {
  it("gives an article only next week needs a row of its own with this week's empty amounts", async () => {
    renderPage();
    await includeNextWeek();

    const beans = rowOf("art-b");
    expect(beans.id).toEqual(expect.any(String));
    expect(beans.id).not.toBe("next-b");
    expect(rowOf("art-d").id).not.toBe(beans.id);
    expect(beans).toMatchObject({
      theoretical_id: null,
      additional_id: null,
      theoretical_purchase_amount: 0,
      additional_theoretical_purchase_amount: 0,
      purchase_amount: null,
      note: "",
      computed_next_week_theoretical: 3,
    });
    expect(rowOf("art-a")).toMatchObject({
      id: "cur-a",
      computed_next_week_theoretical: 5,
    });
  });

  it("shows an article the selected week holds without amounts as that week's row", async () => {
    renderPage();
    await includeNextWeek();

    expect(rowOf("art-c")).toMatchObject({
      id: "cur-c",
      note: "this week",
      computed_next_week_theoretical: 3,
    });
  });

  it("leaves the query's rows as the server sent them", async () => {
    renderPage();
    await includeNextWeek();

    for (const row of [...CURRENT_ROWS, ...NEXT_ROWS]) {
      expect(row).not.toHaveProperty("next_week_theoretical");
    }
  });

  it("saves an extra amount on a next-week-only row as the selected week's entry", async () => {
    renderPage();
    await includeNextWeek();
    const beans = rowOf("art-b");

    await save(beans, {
      ...beans,
      amount_per_pu: "2.5",
      additional_theoretical_purchase: "4",
    });

    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({
        model: "purchase",
        year: 2026,
        delivery_week: 41,
        share_article: "art-b",
        unit: "KG",
        size: "L",
        amount: 10,
        amount_per_pu: "2.5",
        seller: "seller-next",
        note: null,
      }),
    );
    expect(api.partialUpdate).not.toHaveBeenCalled();
  });

  it("keeps a note-only save on a next-week-only row in the selected week", async () => {
    renderPage();
    await includeNextWeek();
    const beans = rowOf("art-b");

    await save(beans, {
      ...beans,
      additional_theoretical_purchase: "",
      note: "Bring crates",
    });

    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({
        year: 2026,
        delivery_week: 41,
        amount: 0,
        note: "Bring crates",
      }),
    );
    expect(api.partialUpdate).not.toHaveBeenCalled();
  });

  it("still creates the week's entry when the row is saved again before the refetch", async () => {
    renderPage();
    await includeNextWeek();
    const beans = rowOf("art-b");
    // The table merges the create's answer over the row: the row brings the
    // new entry's id but keeps its key until the refetch replaces it.
    const saved = { ...beans, id: "purchase-new", key: String(beans.id) };

    const payload = grid().customSave!(
      { ...saved, amount_per_pu: "2.5", additional_theoretical_purchase: "2" },
      saved,
    );
    await grid().apiFunctions!.update!(saved.key, payload!);

    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({ size: "L", seller: "seller-next", amount: 5 }),
    );
    expect(api.partialUpdate).not.toHaveBeenCalled();
  });

  it("takes the picked supplier over next week's for a next-week-only row", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "pick supplier" }));
    await includeNextWeek();
    const beans = rowOf("art-b");

    await save(beans, { ...beans, additional_theoretical_purchase: "1" });

    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({ seller: "seller-picked" }),
    );
  });

  it("still updates a row of the selected week by its own id", async () => {
    renderPage();
    await includeNextWeek();
    const apples = rowOf("art-a");

    await save(apples, {
      ...apples,
      amount_per_pu: "2",
      additional_theoretical_purchase: "1",
    });

    expect(api.partialUpdate).toHaveBeenCalledWith(
      "cur-a",
      expect.objectContaining({
        year: 2026,
        delivery_week: 41,
        amount: 2,
        size: "M",
        seller: null,
        note: "apples this week",
      }),
    );
    expect(api.create).not.toHaveBeenCalled();
  });

  it("keeps the selected week's query when the box is ticked", async () => {
    renderPage();
    await includeNextWeek();

    expect(selectedWeekParams().length).toBeGreaterThan(0);
    for (const params of selectedWeekParams()) {
      expect(params).not.toHaveProperty("include_next_week");
    }
  });
});

describe("PurchaseList saves", () => {
  it("keeps the size picked on a new row and falls back to M", () => {
    renderPage();
    const newRow = { key: -1 };
    const typed = {
      share_article: "art-x",
      unit: "KG",
      amount_per_pu: "1",
      additional_theoretical_purchase: "3",
    };

    expect(grid().customSave!({ ...typed, size: "L" }, newRow)).toMatchObject({
      size: "L",
      amount: 3,
      seller: null,
    });
    expect(grid().customSave!({ ...typed, size: "" }, newRow)).toMatchObject({
      size: "M",
    });
  });

  it("refreshes both weeks after a save", () => {
    const { invalidateSpy } = renderPage();

    grid().onSaveSuccess!({ key: "cur-a" }, "update");

    const selected = selectedWeekParams();
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: [SUMMARY_URL, selected[selected.length - 1]],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: [SUMMARY_URL, lastNextWeekParams()],
    });
  });

  it("asks for ISO week 53 after week 52 of 2026", async () => {
    renderPage();
    await userEvent.click(
      screen.getByRole("button", { name: "pick 2026 week 52" }),
    );

    expect(lastNextWeekParams()).toMatchObject({ year: 2026, delivery_week: 53 });
  });
});
