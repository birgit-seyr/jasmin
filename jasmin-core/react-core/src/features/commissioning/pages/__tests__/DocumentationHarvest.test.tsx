/**
 * DocumentationHarvest: what was harvested on one day into one storage — the
 * expected harvest next to the actual one, with a note — plus the bulk
 * finalize / set-as-expected actions and the CSV export. Rendered through the
 * real week, day and storage selectors, EditableTable, column hooks, phone
 * card and CSV export modal. The generated commissioning client is the mocking
 * boundary: its hooks are real TanStack queries around spies that answer from
 * an in-memory farm, and its mutations write to that farm. The new-article
 * modal and the browser download are stubbed.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41, day number 1).
 * The clock is set before the imports run as well as before every test; the
 * page reads "today" when it mounts.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DocumentationSummaryRow,
  ShareArticle,
  Storage,
} from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Per-test tenant settings; anything unset falls back to the caller's default.
const tenantSettings = vi.hoisted(() => ({
  values: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// Phone or desktop viewport, per test.
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({
  useIsMobile: () => viewport.mobile,
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["gardener"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

const api = vi.hoisted(() => ({
  summary: vi.fn(), storages: vi.fn(), shareArticles: vi.fn(),
  create: vi.fn(), update: vi.fn(), destroy: vi.fn(),
  finalize: vi.fn(), setAsExpected: vi.fn(), exportCsv: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      const enabled = options?.query?.enabled;
      return useQuery({ queryKey: queryKey(path, params), queryFn: async () => request(params), enabled });
    };
  const summaryPath = "documentation_summary/summary";
  return {
    useCommissioningDocumentationSummarySummaryRetrieve: queryHook(summaryPath, api.summary),
    getCommissioningDocumentationSummarySummaryRetrieveQueryKey: (params?: unknown) =>
      queryKey(summaryPath, params),
    useCommissioningStoragesList: queryHook("storages", api.storages),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
    commissioningHarvestCreate: api.create,
    commissioningHarvestPartialUpdate: api.update,
    commissioningHarvestDestroy: api.destroy,
    commissioningBulkFinalizeCreate: api.finalize,
    commissioningHarvestBulkSetAsExpectedCreate: api.setAsExpected,
    commissioningHarvestExportCsvRetrieve: api.exportCsv,
  };
});

// The page needs only the harvest export and the new-article modal; the barrel
// would also load every other modal of the app. The new-article modal is a
// stub whose "create" adds an article to the farm, as saving the real one does.
vi.mock("@features/commissioning/modals", async () => ({
  ExportCsvHarvest: (await import("@features/commissioning/modals/csv/ExportCsvHarvest"))
    .default,
  ShareArticleModal: function ShareArticleModal(props: {
    isOpen: boolean;
    onSuccess?: (saved: Record<string, unknown>) => void;
  }) {
    const create = () => {
      farm.articles = [...farm.articles, CHARD];
      props.onSuccess?.({ ...CHARD });
    };
    return props.isOpen ? (
      <div role="dialog" aria-label="commissioning.add_share_article">
        <button type="button" onClick={create}>create share article</button>
      </div>
    ) : null;
  },
}));

// The files the CSV export saved, in order.
const downloads = vi.hoisted(() => ({ files: [] as string[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (_blob: Blob, filename: string) => downloads.files.push(filename),
}));

import DocumentationHarvest from "../DocumentationHarvest";

// ── Fixtures ────────────────────────────────────────────────────────────────

const COLD_STORE: Storage = { id: "st-cold", name: "Cold store", is_short_term_harvest_storage: true };
const ROOT_CELLAR: Storage = { id: "st-cellar", name: "Root cellar", is_long_term_harvest_storage: true };
const FARM_SHOP: Storage = { id: "st-shop", name: "Farm shop" };
const STORAGES = [COLD_STORE, ROOT_CELLAR, FARM_SHOP];

const article = (
  name: string,
  unit: ShareArticle["default_movement_unit"],
  fields: Partial<ShareArticle> = {},
): ShareArticle => ({ id: `sa-${name.toLowerCase()}`, name, default_movement_unit: unit, ...fields });

const CARROTS = article("Carrots", "KG");
const LETTUCE = article("Lettuce", "PCS");
const RADISHES = article("Radishes", "BUNCH");
const KALE = article("Kale", "KG");
const POTATOES = article("Potatoes", "KG");
const BEETROOT = article("Beetroot", "KG");
const LEEKS = article("Leeks", "KG");
const PUMPKINS = article("Pumpkins", "PCS", { default_pieces_per_pu_harvest: "8", default_crate_harvest: "crate-e2" });
const CHARD = article("Chard", "BUNCH");

/** A summary row: one recorded harvest of one article in one storage. */
type HarvestRow = DocumentationSummaryRow & Record<string, unknown>;

const harvest = (
  id: string,
  ofArticle: ShareArticle,
  storage: Storage,
  fields: Partial<DocumentationSummaryRow> = {},
): HarvestRow => ({
  id,
  share_article: ofArticle.id ?? null,
  share_article_name: ofArticle.name,
  unit: ofArticle.default_movement_unit,
  size: "M", note: "", is_finalized: false, harvest_amount: null,
  theoretical_harvest_amount: null, additional_theoretical_harvest_amount: null,
  theoretical_id: null, additional_id: null, theoretical_current_stock: null,
  forecast_plot_name: null, forecast_bed_number: null, forecast_note: null,
  amount_per_pu: null, harvesting_crate: null, harvesting_crate_name: null,
  seller: null, seller_name: null, price_per_unit: null,
  // The summary flags the storage a row is kept in among all active ones.
  ...Object.fromEntries(STORAGES.map((s) => [`storage_${s.id}`, s.id === storage.id])),
  ...fields,
});

// Tuesday of week 41 in the cold store: carrots harvested against a plan of
// 10 kg plus 2.5 kg added later, lettuce planned but not harvested yet, and
// radishes harvested without a plan. Kale carries no amount at all.
const CARROTS_ROW = harvest("h-carrots", CARROTS, COLD_STORE, {
  theoretical_harvest_amount: 10, additional_theoretical_harvest_amount: 2.5,
  harvest_amount: "11.00", note: "Bed 3",
});
const LETTUCE_ROW = harvest("h-lettuce", LETTUCE, COLD_STORE, { size: "L", theoretical_harvest_amount: 40 });
const RADISHES_ROW = harvest("h-radishes", RADISHES, COLD_STORE, { harvest_amount: "6.00" });
const KALE_ROW = harvest("h-kale", KALE, COLD_STORE, { theoretical_harvest_amount: 0, harvest_amount: "0.00" });
const POTATOES_ROW = harvest("h-potatoes", POTATOES, ROOT_CELLAR, { harvest_amount: "250.00" });
const BEETROOT_ROW = harvest("h-beetroot", BEETROOT, COLD_STORE, { harvest_amount: "4.00" });
const LEEKS_ROW = harvest("h-leeks", LEEKS, COLD_STORE, { harvest_amount: "7.00" });

type SummaryParams = { year: number; delivery_week: number; day_number: number };
type Payload = Record<string, unknown>;

const dayKey = (year: number, week: number, day: number) => `${year}/${week}/${day}`;
const dayOf = (payload: Payload) =>
  dayKey(payload.year as number, payload.delivery_week as number, payload.day_number as number);

/** What the in-memory farm holds; the request spies answer from it. */
let farm: { storages: Storage[]; articles: ShareArticle[]; harvests: Record<string, HarvestRow[]> };
let createdCount = 0;

/** The day a harvest row is recorded on, and the row itself. */
function findHarvest(id: string): [string, HarvestRow] {
  for (const [day, rows] of Object.entries(farm.harvests)) {
    const row = rows.find((candidate) => candidate.id === id);
    if (row) return [day, row];
  }
  throw new Error(`No harvest ${id} on the farm`);
}

function replaceHarvest(id: string, change: Partial<HarvestRow>): HarvestRow {
  const [day, row] = findHarvest(id);
  const updated = { ...row, ...change };
  farm.harvests[day] = farm.harvests[day].map((each) => (each.id === id ? updated : each));
  return updated;
}

/** An amount as the backend's two-decimal field returns it. */
const decimal = (value: unknown) => Number(value).toFixed(2);

/** The fields every harvest saved from the frozen day in the cold store carries. */
const TUESDAY_IN_COLD_STORE = { storage: COLD_STORE.id, year: 2026, delivery_week: 41, day_number: 1 };

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<DocumentationHarvest />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const STORAGE = "placeholder.storage_selector";
const DAY = "common.delivery_day";
const WEEK = "common.week";
const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const EXPECTED = "commissioning.expected_harvest";
const ACTUAL = "commissioning.actual_harvest";
const NOTE = "commissioning.note";
const ADD = /table\.add_plus_icon/;

/**
 * The same number in either decimal notation, with or without trailing zeros:
 * amountText(12.5) matches "12.5", "12,5", "12.50" and "12,50", whatever the
 * unit's precision.
 */
function amountText(value: number): RegExp {
  const [whole, fraction = ""] = String(value).split(".");
  return new RegExp(fraction ? `^${whole}[.,]${fraction}0*$` : `^${whole}(?:[.,]0+)?$`);
}

/** The label a select shows for its current value. */
const selectionOf = (combobox: HTMLElement) =>
  combobox.closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent ?? "";
const selectedIn = (name: string) => selectionOf(screen.getByRole("combobox", { name }));

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

async function choose(combobox: HTMLElement, option: string) {
  await userEvent.click(combobox);
  await userEvent.click(within(openDropdown()).getByText(option));
}

const chooseIn = (name: string, option: string) => choose(screen.getByRole("combobox", { name }), option);

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

/** The cell of a row under the column whose header names ``header``. */
function cellOf(name: string, header: string): HTMLElement {
  const column = screen.getAllByRole("columnheader").findIndex((cell) => cell.textContent?.includes(header));
  return within(rowOf(name)).getAllByRole("cell")[column];
}

/** The row being edited: the one whose actual harvest is an input. */
function editingRow(): HTMLElement {
  const row = screen.getByRole("textbox", { name: ACTUAL }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

const save = () => userEvent.click(screen.getByRole("button", { name: "table.save" }));
const startNewRow = () => userEvent.click(screen.getByRole("button", { name: ADD }));
const chooseArticle = (name: string) =>
  choose(within(editingRow()).getByRole("combobox", { name: ARTICLE }), name);

/** The phone card of an article; a closing editor may still show its name. */
function cardOf(name: string): HTMLElement {
  const cards = Array.from(document.querySelectorAll<HTMLElement>(".mobile-card-item"));
  const card = cards.find((item) => within(item).queryByText(name));
  if (!card) throw new Error(`No card shows ${name}`);
  return card;
}

const findCard = (name: string) => waitFor(() => cardOf(name));

/** A field of the open row editor dialog, found through its label. */
function fieldOf(dialog: HTMLElement, label: string, role: "combobox" | "textbox") {
  const item = within(dialog).getByText(label).closest<HTMLElement>(".ant-form-item");
  if (!item) throw new Error(`No field labelled ${label}`);
  return within(item).getByRole(role);
}

const tableIsBusy = () => document.querySelector('.ant-table-wrapper [aria-busy="true"]') !== null;

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

/** An API refusal in the canonical error shape. */
const refusal = (message: string, details: Record<string, unknown> = {}) => ({
  isAxiosError: true,
  message: "Request failed with status code 400",
  response: { status: 400, data: { code: "validation_error", message, details } },
});

const lastSummaryRequest = () => api.summary.mock.lastCall?.[0];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  auth.roles = ["gardener"];
  downloads.files = [];
  createdCount = 0;
  farm = {
    storages: [...STORAGES],
    articles: [CARROTS, LETTUCE, RADISHES, KALE, POTATOES, BEETROOT, LEEKS, PUMPKINS],
    harvests: {
      [dayKey(2026, 41, 1)]: [CARROTS_ROW, LETTUCE_ROW, RADISHES_ROW, KALE_ROW, POTATOES_ROW],
      [dayKey(2026, 41, 2)]: [BEETROOT_ROW],
      [dayKey(2026, 39, 1)]: [LEEKS_ROW],
    },
  };
  api.storages.mockReset().mockImplementation(async () => [...farm.storages]);
  api.shareArticles.mockReset().mockImplementation(async () => [...farm.articles]);
  api.summary.mockReset().mockImplementation(async (params: SummaryParams) => [
    ...(farm.harvests[dayKey(params.year, params.delivery_week, params.day_number)] ?? []),
  ]);
  // Create and update answer with the saved row in summary shape, as the API does.
  api.create.mockReset().mockImplementation(async (payload: Payload) => {
    const ofArticle = farm.articles.find((a) => a.id === payload.share_article);
    const storage = farm.storages.find((s) => s.id === payload.storage);
    if (!ofArticle || !storage) throw new Error("Unknown article or storage");
    createdCount += 1;
    const row = harvest(`h-new-${createdCount}`, ofArticle, storage, {
      unit: payload.unit as string, size: payload.size as string,
      note: (payload.note as string) ?? "", harvest_amount: decimal(payload.amount),
    });
    farm.harvests[dayOf(payload)] = [...(farm.harvests[dayOf(payload)] ?? []), row];
    return row;
  });
  api.update.mockReset().mockImplementation(async (id: string, payload: Payload) =>
    replaceHarvest(id, { harvest_amount: decimal(payload.amount), note: (payload.note as string) ?? "" }),
  );
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    const [day] = findHarvest(id);
    farm.harvests[day] = farm.harvests[day].filter((row) => row.id !== id);
  });
  api.finalize.mockReset().mockImplementation(async ({ ids }: { ids: string[] }) => {
    ids.forEach((id) => replaceHarvest(id, { is_finalized: true }));
    return { finalized: ids.length };
  });
  // The expected amount becomes the actual harvest of the matching row.
  api.setAsExpected.mockReset().mockImplementation(async ({ selectedData }: { selectedData: Payload[] }) => {
    for (const item of selectedData) {
      const row = farm.harvests[dayOf(item)].find(
        (candidate) =>
          candidate.share_article === item.id &&
          candidate.unit === item.theoretical_harvest_unit &&
          candidate.size === item.theoretical_harvest_size &&
          candidate[`storage_${item.storage}`],
      );
      if (row) replaceHarvest(row.id, { harvest_amount: decimal(item.theoretical_harvest_amount) });
    }
  });
  api.exportCsv.mockReset().mockResolvedValue("article;amount\r\nCarrots;11,00\r\n");
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("DocumentationHarvest loading", () => {
  it("opens on today in the first storage and lists the harvest kept there", async () => {
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "commissioning.documentation_harvest" })).toBeInTheDocument();
    expect(selectedIn(STORAGE)).toBe("Cold store");
    expect(selectedIn(DAY)).toBe("Tuesday, 06.10.2026");
    expect(api.storages).toHaveBeenCalledWith({ is_active: true });
    const request = { year: 2026, delivery_week: 41, day_number: 1, is_past: false, model: "harvest" };
    expect(lastSummaryRequest()).toEqual(request);
    // Kale carries no amount and the potatoes lie in the root cellar.
    expect(bodyRows()).toHaveLength(3);
    expect(screen.getByText("Lettuce")).toBeInTheDocument();
    expect(screen.getByText("Radishes")).toBeInTheDocument();
    expect(screen.queryByText("Kale")).not.toBeInTheDocument();
    expect(screen.queryByText("Potatoes")).not.toBeInTheDocument();
    expect(screen.getByText("explainers.documentationharvest")).toBeInTheDocument();
  });

  it("loads no harvest until the storages are known", async () => {
    const storages = pending<Storage[]>();
    api.storages.mockImplementation(() => storages.promise);
    renderPage();

    await waitFor(() => expect(api.storages).toHaveBeenCalled());
    expect(api.summary).not.toHaveBeenCalled();
    expect(bodyRows()).toHaveLength(0);

    storages.answer([...farm.storages]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(lastSummaryRequest()).toMatchObject({ day_number: 1, model: "harvest" });
  });

  it("shows a spinner over the table while the day's harvest loads", async () => {
    const rows = pending<HarvestRow[]>();
    api.summary.mockImplementation(() => rows.promise);
    renderPage();

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);

    rows.answer([CARROTS_ROW]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });
});

// ── Harvest rows ────────────────────────────────────────────────────────────

describe("DocumentationHarvest harvest rows", () => {
  it("shows each harvest's unit, expected amount with what was added, actual amount and note", async () => {
    renderPage();
    await screen.findByText("Carrots");

    for (const header of [ARTICLE, UNIT, EXPECTED, ACTUAL, NOTE]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(screen.queryByRole("columnheader", { name: "commissioning.size" })).not.toBeInTheDocument();

    expect(cellOf("Carrots", UNIT)).toHaveTextContent("commissioning.units.kg");
    expect([cellOf("Carrots", EXPECTED).textContent, cellOf("Carrots", ACTUAL).textContent]).toEqual(["12,50", "11,00"]);
    expect(cellOf("Carrots", NOTE)).toHaveTextContent("Bed 3");
    expect(cellOf("Lettuce", UNIT)).toHaveTextContent("commissioning.units.pcs");
    expect(cellOf("Lettuce", EXPECTED).textContent).toBe("40,0");
    expect(cellOf("Lettuce", ACTUAL)).toHaveTextContent(/^$/);
    expect(cellOf("Radishes", UNIT)).toHaveTextContent("commissioning.units.bunch");
    expect(cellOf("Radishes", EXPECTED)).toHaveTextContent(/^$/);
    expect(cellOf("Radishes", ACTUAL).textContent).toBe("6,0");
    for (const name of ["Carrots", "Lettuce", "Radishes"]) {
      expect(within(rowOf(name)).getByText("commissioning.not_finalized")).toBeInTheDocument();
    }
  });

  it("writes a summed expected harvest without float noise, in the tenant's number format", async () => {
    tenantSettings.values = { number_locale: "en-US" }; // 0.1 + 0.2 is 0.30000000000000004 in floating point.
    farm.harvests[dayKey(2026, 41, 1)] = [harvest("h-kale", KALE, COLD_STORE, { theoretical_harvest_amount: 0.1, additional_theoretical_harvest_amount: 0.2, harvest_amount: "1234.500" })];
    renderPage();
    await screen.findByText("Kale");
    expect([cellOf("Kale", EXPECTED).textContent, cellOf("Kale", ACTUAL).textContent]).toEqual(["0.30", "1,234.50"]);
  });

  it("adds the size column when the farm shows sizes, and dates the day in the farm's format", async () => {
    tenantSettings.values = { show_size_column: true, date_format: "MM/DD/YYYY" };
    renderPage();
    await screen.findByText("Lettuce");

    expect(cellOf("Lettuce", "commissioning.size")).toHaveTextContent("commissioning.large");
    expect(cellOf("Carrots", "commissioning.size")).toHaveTextContent("commissioning.medium");
    expect(selectedIn(DAY)).toBe("Tuesday, 10/06/2026");
  });

  it("lists a long-term storage's harvest without an expected amount or bulk actions", async () => {
    renderPage();
    await screen.findByText("Carrots");
    expect(screen.getByText("commissioning.for_selected")).toBeInTheDocument();

    await chooseIn(STORAGE, "Root cellar");

    expect(await screen.findByText("Potatoes")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(1);
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: EXPECTED })).not.toBeInTheDocument();
    expect(cellOf("Potatoes", ACTUAL)).toHaveTextContent(amountText(250));
    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "commissioning.finalize" })).not.toBeInTheDocument();
  });

  it("says there is no harvest in a storage nothing was brought to", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await chooseIn(STORAGE, "Farm shop");

    await waitFor(() => expect(bodyRows()).toHaveLength(0));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
  });
});

// ── Week and day ────────────────────────────────────────────────────────────

describe("DocumentationHarvest choosing the week and day", () => {
  it("lists another day's harvest when the day changes", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await chooseIn(DAY, "Wednesday, 07.10.2026");

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(selectedIn(STORAGE)).toBe("Cold store");
    expect(lastSummaryRequest()).toMatchObject({ delivery_week: 41, day_number: 2 });
  });

  it("loads the same weekday of the next week from the week arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(selectedIn(DAY)).toBe("Tuesday, 13.10.2026"));
    const request = { year: 2026, delivery_week: 42, day_number: 1, is_past: false, model: "harvest" };
    expect(lastSummaryRequest()).toEqual(request);
    await waitFor(() => expect(bodyRows()).toHaveLength(0));
  });

  it("shows a week more than a week back read-only", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastSummaryRequest()).toMatchObject({ delivery_week: 40 }));
    expect(lastSummaryRequest()).toMatchObject({ is_past: false });
    expect(screen.queryByText("table.past_week_readonly")).not.toBeInTheDocument();

    await userEvent.click(arrow(WEEK, "common.previous"));

    expect(await screen.findByText("Leeks")).toBeInTheDocument();
    expect(lastSummaryRequest()).toMatchObject({ delivery_week: 39, is_past: true });
    expect(screen.getByText("table.past_week_readonly")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ADD })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();
    expect(within(rowOf("Leeks")).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /commissioning\.add_share_article/ })).toBeDisabled();

    await userEvent.click(within(rowOf("Leeks")).getByText(amountText(7)));

    expect(screen.queryByRole("textbox", { name: ACTUAL })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });
});

// ── Adding, correcting and deleting ─────────────────────────────────────────

describe("DocumentationHarvest adding a harvest", () => {
  it("records a new harvest with the article's unit, crate and amount per unit", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Pumpkins");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.pcs"));
    await userEvent.type(screen.getByRole("textbox", { name: ACTUAL }), "12,5");
    expect(screen.getByRole("textbox", { name: ACTUAL })).toHaveValue("12,5");
    await userEvent.type(screen.getByRole("textbox", { name: NOTE }), "Under the walnut");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({
        ...TUESDAY_IN_COLD_STORE,
        share_article: PUMPKINS.id, unit: "PCS", size: "M", amount: "12.5",
        note: "Under the walnut", amount_per_pu: "8", harvesting_crate: "crate-e2",
      }),
    );
    expect(await screen.findByText("Under the walnut")).toBeInTheDocument();
    expect(cellOf("Pumpkins", ACTUAL)).toHaveTextContent(amountText(12.5));
    expect(screen.queryByRole("textbox", { name: ACTUAL })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
  });

  it("starts a new entry from the + key", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.keyboard("+");

    expect(await screen.findByRole("combobox", { name: ARTICLE })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
  });

  it("refuses an article, unit and size already recorded that day until the unit differs", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Carrots");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.kg"));
    await userEvent.type(screen.getByRole("textbox", { name: ACTUAL }), "3");
    await save();

    const unique = "validation.unique.share_article_unit_size_must_be_unique";
    expect(await screen.findByText(`${unique} — table.save_failed_hint`)).toBeInTheDocument();
    expect(screen.getByText("table.save_failed_title")).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();

    await chooseIn(UNIT, "commissioning.units.bunch");
    await save();

    const bunches = { share_article: CARROTS.id, unit: "BUNCH", amount: "3" };
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining(bunches)));
    await waitFor(() => expect(screen.queryByText("table.save_failed_title")).not.toBeInTheDocument());
    expect(screen.getAllByText("Carrots")).toHaveLength(2);
  });

  it("asks for the article before saving", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await userEvent.type(screen.getByRole("textbox", { name: ACTUAL }), "5");
    await save();

    expect(await screen.findByText("table.save_failed_title")).toBeInTheDocument();
    const article = () => screen.getByRole("combobox", { name: ARTICLE });
    await waitFor(() => expect(article()).toHaveAttribute("aria-invalid", "true"));
    expect(api.create).not.toHaveBeenCalled();
  });
});

describe("DocumentationHarvest correcting a harvest", () => {
  it("saves a corrected amount and note while the article and unit stay as recorded", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(within(rowOf("Carrots")).getByText(amountText(11)));

    const amount = screen.getByRole("textbox", { name: ACTUAL });
    expect(amount).toHaveValue("11,00");
    const row = editingRow();
    expect(within(row).getByText("Carrots")).toBeInTheDocument();
    expect(within(row).queryByRole("combobox", { name: ARTICLE })).not.toBeInTheDocument();
    expect(within(row).queryByRole("combobox", { name: UNIT })).not.toBeInTheDocument();
    await userEvent.clear(amount);
    await userEvent.type(amount, "11,75");
    const note = screen.getByRole("textbox", { name: NOTE });
    await userEvent.clear(note);
    await userEvent.type(note, "Bed 3 and 4");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      CARROTS_ROW.id,
      expect.objectContaining({
        ...TUESDAY_IN_COLD_STORE,
        share_article: CARROTS.id, unit: "KG", size: "M", amount: "11.75", note: "Bed 3 and 4",
      }),
    );
    await waitFor(() => expect(cellOf("Carrots", ACTUAL)).toHaveTextContent(amountText(11.75)));
    expect(cellOf("Carrots", NOTE)).toHaveTextContent("Bed 3 and 4");
  });

  it("keeps the row open with the server's reason when a save is refused", async () => {
    const reason = "Ensure this value has at most 8 digits.";
    api.update.mockRejectedValueOnce(refusal(reason, { amount: [reason] }));
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(within(rowOf("Radishes")).getByText(amountText(6)));
    const amount = screen.getByRole("textbox", { name: ACTUAL });
    await userEvent.clear(amount);
    await userEvent.type(amount, "8{Enter}");

    expect(await screen.findByText(`${ACTUAL}: ${reason} — table.save_failed_hint`)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: ACTUAL })).toHaveValue("8");

    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(cellOf("Radishes", ACTUAL)).toHaveTextContent(amountText(8)));
    expect(screen.queryByText("table.save_failed_title")).not.toBeInTheDocument();
  });
});

describe("DocumentationHarvest deleting a harvest", () => {
  const deleteButtonOf = (name: string) =>
    within(rowOf(name)).queryByRole("button", { name: "table.delete" });
  const deleteRadishes = async () => {
    await userEvent.click(deleteButtonOf("Radishes")!);
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));
  };

  it("deletes a harvest without an expected amount after confirmation and reloads the day", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const loads = api.summary.mock.calls.length;

    expect(deleteButtonOf("Carrots")).not.toBeInTheDocument();
    expect(deleteButtonOf("Lettuce")).not.toBeInTheDocument();
    await deleteRadishes();

    await waitFor(() => expect(screen.queryByText("Radishes")).not.toBeInTheDocument());
    expect(api.destroy).toHaveBeenCalledWith(RADISHES_ROW.id);
    await waitFor(() => expect(api.summary.mock.calls.length).toBeGreaterThan(loads));
    expect(bodyRows()).toHaveLength(2);
  });

  it("keeps the harvest and says why when the server refuses to delete it", async () => {
    api.destroy.mockRejectedValueOnce(refusal("The harvest has already been moved on."));
    renderPage();
    await screen.findByText("Carrots");

    await deleteRadishes();

    expect(await screen.findByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("The harvest has already been moved on.")).toBeInTheDocument();
    expect(screen.getByText("Radishes")).toBeInTheDocument();
  });
});

// ── Bulk actions ────────────────────────────────────────────────────────────

describe("DocumentationHarvest bulk actions", () => {
  const FINALIZE = "commissioning.finalize";
  const SET_AS_EXPECTED = "commissioning.set_as_expected_harvest_for";
  const select = (name: string) => userEvent.click(within(rowOf(name)).getByRole("checkbox"));

  it("finalizes the selected harvests", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const finalize = screen.getByRole("button", { name: FINALIZE });
    expect(finalize).toBeDisabled();

    await select("Carrots");
    await select("Radishes");
    await userEvent.click(finalize);

    const ids = [CARROTS_ROW.id, RADISHES_ROW.id];
    await waitFor(() => expect(api.finalize).toHaveBeenCalledWith({ model: "harvest", app_label: "commissioning", ids }));
    expect(await within(rowOf("Carrots")).findByText("commissioning.finalized")).toBeInTheDocument();
    expect(within(rowOf("Radishes")).getByText("commissioning.finalized")).toBeInTheDocument();
    expect(within(rowOf("Lettuce")).getByText("commissioning.not_finalized")).toBeInTheDocument();
  });

  it("records the expected harvest of the short-term storage as harvested", async () => {
    renderPage();
    await screen.findByText("Lettuce");
    const setAsExpected = screen.getByRole("button", { name: SET_AS_EXPECTED });
    expect(setAsExpected).toBeDisabled();

    await select("Lettuce");
    await userEvent.click(setAsExpected);

    const expected = { theoretical_harvest_amount: "40", theoretical_harvest_unit: "PCS", theoretical_harvest_size: "L" };
    await waitFor(() =>
      expect(api.setAsExpected).toHaveBeenCalledWith({
        selectedData: [{ ...TUESDAY_IN_COLD_STORE, id: LETTUCE.id, ...expected }],
      }),
    );
    await waitFor(() => expect(cellOf("Lettuce", ACTUAL)).toHaveTextContent(amountText(40)));
  });

  it("won't set the expected harvest over an actual one or where none is expected", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const setAsExpected = screen.getByRole("button", { name: SET_AS_EXPECTED });

    await select("Lettuce");
    expect(setAsExpected).toBeEnabled();
    await select("Carrots");
    expect(setAsExpected).toBeDisabled();
    expect(screen.getByRole("button", { name: FINALIZE })).toBeEnabled();

    await select("Carrots");
    await select("Lettuce");
    await select("Radishes");
    expect(setAsExpected).toBeDisabled();
  });

  it("says why when finalizing is refused", async () => {
    api.finalize.mockRejectedValueOnce(refusal("Lettuce has no actual harvest yet."));
    renderPage();
    await screen.findByText("Lettuce");

    await select("Lettuce");
    await userEvent.click(screen.getByRole("button", { name: FINALIZE }));

    expect(await screen.findByText("Lettuce has no actual harvest yet.")).toBeInTheDocument();
    expect(within(rowOf("Lettuce")).getByText("commissioning.not_finalized")).toBeInTheDocument();
  });
});

// ── CSV export and new articles ─────────────────────────────────────────────

describe("DocumentationHarvest CSV export", () => {
  it("downloads the harvest of a date range, summed per article when asked", async () => {
    const EXPORT = "commissioning.export_harvest_csv";
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(screen.getByRole("button", { name: EXPORT }));
    const dialog = await screen.findByRole("dialog", { name: EXPORT });
    const download = within(dialog).getByRole("button", { name: /common\.download/ });
    expect(download).toBeDisabled();

    await userEvent.click(within(dialog).getByPlaceholderText("Start date"));
    await userEvent.click(await screen.findByText("common.last_month"));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "commissioning.sum_by_share_article" }));
    await userEvent.click(download);

    const range = { date_from: "2026-09-01", date_to: "2026-09-30" };
    await waitFor(() => expect(api.exportCsv).toHaveBeenCalledWith({ ...range, summed: true }));
    await waitFor(() => expect(downloads.files).toEqual(["ernte_2026-09-01_2026-09-30_summiert.csv"]));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: EXPORT })).not.toBeInTheDocument());
  });
});

describe("DocumentationHarvest new share articles", () => {
  it("offers an article created from the page in the article picker", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const loads = api.shareArticles.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: /commissioning\.add_share_article/ }));
    const dialog = await screen.findByRole("dialog", { name: "commissioning.add_share_article" });
    await userEvent.click(within(dialog).getByRole("button", { name: "create share article" }));

    expect(dialog).not.toBeInTheDocument();
    await waitFor(() => expect(api.shareArticles.mock.calls.length).toBeGreaterThan(loads));
    await startNewRow();
    await chooseArticle("Chard");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.bunch"));
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("DocumentationHarvest without a staff role", () => {
  it("shows the harvest without a way to add, correct or delete it", async () => {
    auth.roles = ["member"];
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: ADD })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();
    await userEvent.click(within(rowOf("Carrots")).getByText(amountText(11)));
    await userEvent.keyboard("+");

    expect(screen.queryByRole("textbox", { name: ACTUAL })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("DocumentationHarvest on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each harvest as a card with its expected and actual amount instead of the table", async () => {
    renderPage();
    const carrots = await findCard("Carrots");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(selectedIn(DAY)).toBe("Tu, 06.10.");
    for (const text of ["commissioning.expected", "commissioning.actual", "Bed 3"]) {
      expect(within(carrots).getByText(text)).toBeInTheDocument();
    }
    expect(within(carrots).getByText(amountText(12.5))).toBeInTheDocument();
    expect(within(carrots).getByText(amountText(11))).toBeInTheDocument();
    expect(within(carrots).getByText("commissioning.units.kg")).toBeInTheDocument();
    const lettuce = cardOf("Lettuce");
    expect(within(lettuce).getByText("commissioning.large")).toBeInTheDocument();
    expect(within(lettuce).getByText(amountText(40))).toBeInTheDocument();
    expect(within(lettuce).getByText("–")).toBeInTheDocument();
    expect(within(cardOf("Radishes")).getByText(amountText(6))).toBeInTheDocument();

    await chooseIn(STORAGE, "Root cellar");

    const potatoes = await findCard("Potatoes");
    expect(within(potatoes).queryByText("commissioning.expected")).not.toBeInTheDocument();
    expect(within(potatoes).getByText(amountText(250))).toBeInTheDocument();
    expect(within(potatoes).getByText("commissioning.units.kg")).toBeInTheDocument();
  });

  it("corrects a harvest from its card", async () => {
    renderPage();
    await userEvent.click(await findCard("Carrots"));

    const dialog = await screen.findByRole("dialog", { name: "table.edit_record" });
    const amount = fieldOf(dialog, ACTUAL, "textbox");
    expect(amount).toHaveValue("11,00");
    expect(fieldOf(dialog, ARTICLE, "combobox")).toBeDisabled();
    expect(fieldOf(dialog, UNIT, "combobox")).toBeDisabled();
    await userEvent.clear(amount);
    await userEvent.type(amount, "11,75");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith(
        CARROTS_ROW.id,
        expect.objectContaining({
          ...TUESDAY_IN_COLD_STORE,
          share_article: CARROTS.id, unit: "KG", size: "M", amount: "11.75", note: "Bed 3",
        }),
      ),
    );
    await waitFor(() => expect(within(cardOf("Carrots")).getByText(amountText(11.75))).toBeInTheDocument());
  });

  it("records a new harvest from the add button", async () => {
    renderPage();
    await findCard("Carrots");

    await userEvent.click(screen.getByRole("button", { name: /table\.add_record/ }));
    const dialog = await screen.findByRole("dialog", { name: "table.add_record" });
    await choose(fieldOf(dialog, ARTICLE, "combobox"), "Pumpkins");
    await waitFor(() => expect(selectionOf(fieldOf(dialog, UNIT, "combobox"))).toBe("commissioning.units.pcs"));
    await userEvent.type(fieldOf(dialog, ACTUAL, "textbox"), "3");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        expect.objectContaining({
          ...TUESDAY_IN_COLD_STORE,
          share_article: PUMPKINS.id, unit: "PCS", size: "M", amount: "3",
        }),
      ),
    );
    expect(within(await findCard("Pumpkins")).getByText(amountText(3))).toBeInTheDocument();
  });

  it("leaves out the bulk actions, row selection, deleting, the CSV export and the explainer", async () => {
    renderPage();
    await findCard("Carrots");

    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "commissioning.finalize" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "commissioning.export_harvest_csv" })).not.toBeInTheDocument();
    expect(screen.queryByText("explainers.documentationharvest")).not.toBeInTheDocument();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("DocumentationHarvest render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Carrots");
    await flushMicrotasks();

    // About 13 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});
