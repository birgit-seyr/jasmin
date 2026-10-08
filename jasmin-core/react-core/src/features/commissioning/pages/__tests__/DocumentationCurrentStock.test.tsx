/**
 * DocumentationCurrentStock: the stock count of one day in one storage. Beside
 * the stock the movements leave for each article (the expected stock) the farm
 * staff enters what they counted, counts an article that is not listed yet,
 * and finalizes, confirms or zeroes several counts at once. Rendered through
 * the real week, day and storage selectors, EditableTable, column hooks and
 * phone card. The generated commissioning client is the mocking boundary: its
 * hooks are real TanStack queries around spies that answer from an in-memory
 * stock list. The new-article dialog is a stub.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The page reads today's week and
 * weekday when it mounts.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticle, StockComparison, Storage, UnitEnum } from "@shared/api/generated/models";
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
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
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
vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => viewport.mobile }));

vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

// The signed-in user's roles, per test.
const auth = vi.hoisted(() => ({ roles: ["staff"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles }, logout: () => {} }),
}));

const api = vi.hoisted(() => ({
  storages: vi.fn(), shareArticles: vi.fn(), counts: vi.fn(), saveCount: vi.fn(),
  finalize: vi.fn(), setAsExpected: vi.fn(), setToZero: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown) {
      return useQuery({ queryKey: queryKey(path, params), queryFn: async () => request(params) });
    };
  return {
    useCommissioningStoragesList: queryHook("storages", api.storages),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
    useCommissioningCurrentStockComparisonList: queryHook("current_stock_comparison", api.counts),
    getCommissioningCurrentStockComparisonListQueryKey: (params?: unknown) =>
      queryKey("current_stock_comparison", params),
    commissioningCurrentStockComparisonPartialUpdate: (id: string, body: unknown) =>
      api.saveCount(id, body),
    commissioningCurrentStockComparisonDestroy: vi.fn(),
    commissioningCurrentStockBulkFinalizeCreate: (body: unknown) => api.finalize(body),
    commissioningCurrentStockBulkSetAsExpectedCreate: (body: unknown) => api.setAsExpected(body),
    commissioningCurrentStockBulkSetToZeroCreate: (body: unknown) => api.setToZero(body),
  };
});

// The new-article dialog: saving it hands the page the created article.
vi.mock("@features/commissioning/modals", () => ({
  ShareArticleModal: ({ isOpen, onSuccess }: { isOpen: boolean; onSuccess: (saved: object) => void }) =>
    isOpen ? (
      <div role="dialog" aria-label="commissioning.add_share_article">
        <button type="button" onClick={() => onSuccess({ id: "art-leeks" })}>
          save article
        </button>
      </div>
    ) : null,
}));

import DocumentationCurrentStock from "../DocumentationCurrentStock";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Backend day numbers: 0 = Monday … 6 = Sunday.
const TUESDAY = 1;
const WEDNESDAY = 2;

const CELLAR: Storage = { id: "st-cellar", name: "Cellar", is_active: true };
const COLD_ROOM: Storage = { id: "st-cold-room", name: "Cold room", is_active: true };

const article = (id: string, name: string, unit: UnitEnum): ShareArticle => ({
  id, name, default_movement_unit: unit, is_active: true,
});
const CARROTS = article("art-carrots", "Carrots", "KG");
const LETTUCE = article("art-lettuce", "Lettuce", "PCS");
const BEETROOT = article("art-beetroot", "Beetroot", "KG");
const RADISHES = article("art-radishes", "Radishes", "BUNCH");
const APPLES = article("art-apples", "Apples", "KG");
const PUMPKINS = article("art-pumpkins", "Pumpkins", "PCS");
const LEEKS = article("art-leeks", "Leeks", "KG");

type RowPlace = { week?: number; day?: number; storage?: Storage };

/** One article's line of a day's stock list; its id names the count it belongs to. */
function stockRow(
  of: ShareArticle,
  { week = 41, day = TUESDAY, storage = CELLAR, ...fields }: Partial<StockComparison> & RowPlace = {},
): StockComparison {
  const row = {
    share_article: of.id ?? "", share_article_name: of.name,
    unit: of.default_movement_unit as string, size: "M", storage_id: storage.id ?? null,
    theoretical_current_stock: null, amount: null, is_finalized: false, note: "",
    for_shares: false, for_resellers: false, for_markets: false, washed: false, cleaned: false,
    ...fields,
  };
  const id = [row.share_article, row.unit, row.size, row.storage_id, 2026, week, day].join("_");
  return { ...row, id };
}

const CARROTS_ROW = stockRow(CARROTS, { theoretical_current_stock: 1250 });
const LETTUCE_ROW = stockRow(LETTUCE, {
  size: "L", theoretical_current_stock: 40, amount: 38, for_shares: true, note: "Two heads wilted",
});
const BEETROOT_ROW = stockRow(BEETROOT, {
  theoretical_current_stock: -4, amount: 0, is_finalized: true, for_shares: true, for_resellers: true,
});

/** What the in-memory farm holds; the request spies answer from it. */
let farm: { storages: Storage[]; articles: ShareArticle[]; rows: StockComparison[] };

type ListParams = { year: number; delivery_week: number; day_number: number; storage?: string };
type SaveBody = Record<string, unknown>;

/** The rows the backend lists for a day: one storage's, or every storage's. */
const listed = ({ year, delivery_week, day_number, storage }: ListParams) =>
  farm.rows
    .filter((row) => {
      const [, , , storageId, ...day] = row.id.split("_");
      return (
        day.join("_") === `${year}_${delivery_week}_${day_number}` &&
        (!storage || storageId === storage)
      );
    })
    .map((row) => ({ ...row }));

/** Stores a count and answers like the backend: with the saved entry, which carries
 *  neither the expected stock nor the finalized flag. */
function recordCount(compositeId: string, body: SaveBody) {
  const [articleId, unit, size, storageId] = compositeId.split("_");
  const before = farm.rows.find((row) => row.id === compositeId) ?? {
    ...stockRow(farm.articles.find((item) => item.id === articleId)!),
    id: compositeId, unit, size, storage_id: storageId,
  };
  const saved: StockComparison = {
    ...before,
    amount: body.amount == null || body.amount === "" ? before.amount : Number(body.amount),
    for_shares: Boolean(body.for_shares),
    for_resellers: Boolean(body.for_resellers),
    note: (body.note as string | null) ?? null,
  };
  farm.rows = [...farm.rows.filter((row) => row.id !== compositeId), saved];
  const { theoretical_current_stock: _expected, is_finalized: _finalized, ...entry } = saved;
  return entry;
}

/** A bulk endpoint that changes every listed id. */
const bulkChange =
  (change: (row: StockComparison) => Partial<StockComparison>) =>
  async ({ ids }: { ids: string[] }) => {
    farm.rows = farm.rows.map((row) => (ids.includes(row.id) ? { ...row, ...change(row) } : row));
    return { updated: ids.length, created: 0, errors: [] };
  };

const serverError = (message: string) =>
  Object.assign(new Error(message), {
    isAxiosError: true, response: { status: 400, data: { code: "validation_error", message } },
  });

// ── Helpers ─────────────────────────────────────────────────────────────────

const STORAGE = "placeholder.storage_selector";
const DAY = "common.delivery_day";
const WEEK = "common.week";
const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const COUNT = "commissioning.actual_stock";
const NOTE = "commissioning.note";
const ADD_ROW = /table\.add_plus_icon/;
const ADD_CARD = /table\.add_record/;
const ADD_ARTICLE = /commissioning\.add_share_article/;
const FINALIZE = "commissioning.finalize";
const SET_AS_EXPECTED = "commissioning.set_as_expected_stock";
const SET_TO_ZERO = "commissioning.set_to_zero";
const PAST_WEEK = "table.past_week_readonly";

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const page = profiler.wrap(<DocumentationCurrentStock />);
  render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>);
  return { profiler };
}

const lastListRequest = () => api.counts.mock.lastCall?.[0] as ListParams | undefined;
const lastSave = () => api.saveCount.mock.lastCall as [string, SaveBody];

/** The label a selector shows for its current value. */
function selectedIn(name: string): string {
  const select = screen.getByRole("combobox", { name }).closest(".ant-select");
  return select?.querySelector(".ant-select-selection-item")?.textContent ?? "";
}

function openDropdown(): HTMLElement {
  const open = Array.from(document.querySelectorAll<HTMLElement>(".ant-select-dropdown")).filter(
    (dropdown) => !dropdown.classList.contains("ant-select-dropdown-hidden"),
  );
  const dropdown = open[open.length - 1];
  if (!dropdown) throw new Error("No select dropdown is open");
  return dropdown;
}

async function optionsOf(combobox: HTMLElement): Promise<string[]> {
  await userEvent.click(combobox);
  return Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map(
    (option) => option.textContent ?? "",
  );
}

async function pickOption(combobox: HTMLElement, label: string) {
  await userEvent.click(combobox);
  const option = await waitFor(() => {
    const match = Array.from(
      openDropdown().querySelectorAll<HTMLElement>(".ant-select-item-option"),
    ).find((item) => item.textContent === label);
    if (!match) throw new Error(`No option ${label} is offered`);
    return match;
  });
  await userEvent.click(option);
}

const choose = (name: string, label: string) =>
  pickOption(screen.getByRole("combobox", { name }), label);

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

function tableBody(): HTMLElement {
  const body = document.querySelector<HTMLElement>(".ant-table-tbody");
  if (!body) throw new Error("The stock table is not rendered");
  return body;
}

const bodyRows = () => Array.from(tableBody().querySelectorAll<HTMLElement>("tr.ant-table-row"));

function rowOf(text: string): HTMLElement {
  const row = within(tableBody()).getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

const countField = () => within(editingRow()).getByRole("textbox", { name: COUNT });
const save = () => userEvent.click(screen.getByRole("button", { name: "table.save" }));
const flag = (name: string) =>
  within(editingRow()).getByRole("checkbox", { name: `commissioning.${name}` });

/** Opens a listed row for counting by clicking the count it shows. */
async function startCount(articleName: string, shownCount: string) {
  await userEvent.click(within(rowOf(articleName)).getByText(shownCount));
  return countField();
}

async function typeCount(text: string) {
  await userEvent.clear(countField());
  await userEvent.type(countField(), text);
}

async function newRowFor(articleName: string) {
  await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
  await pickOption(within(editingRow()).getByRole("combobox", { name: ARTICLE }), articleName);
}

/** The checkbox that selects a row for the bulk actions. */
function selectionBox(row: HTMLElement): HTMLInputElement {
  const box = row.querySelector<HTMLInputElement>(".ant-table-selection-column input");
  if (!box) throw new Error("The row has no selection checkbox");
  return box;
}

/** The phone card that shows ``text``. */
function cardOf(text: string): HTMLElement {
  const list = document.querySelector<HTMLElement>(".mobile-card-list");
  if (!list) throw new Error("The cards are not rendered");
  const card = within(list).getByText(text).closest<HTMLElement>(".mobile-card-item");
  if (!card) throw new Error(`No card shows ${text}`);
  return card;
}

/** The input of the open row dialog's field labelled ``label``. */
function dialogInput(label: string, role: "combobox" | "textbox"): HTMLElement {
  const dialog = screen.getByRole("dialog");
  const item = within(dialog).getByText(label).closest<HTMLElement>(".ant-form-item");
  if (!item) throw new Error(`The dialog has no field ${label}`);
  return within(item).getByRole(role);
}

const isBusy = (container: HTMLElement = document.body) =>
  container.querySelector('[aria-busy="true"]') !== null;
const tableIsBusy = () => {
  const table = document.querySelector<HTMLElement>(".ant-table-wrapper");
  return table !== null && isBusy(table);
};

/** Waits until the first storage's stock of the day is on screen. */
async function loaded(articleName = "Carrots") {
  await waitFor(() => expect(lastListRequest()).toMatchObject({ storage: CELLAR.id }));
  await screen.findByText(articleName);
  await waitFor(() => expect(isBusy()).toBe(false));
}

/** Steps the week selector back to a week more than a week ago (week 39). */
async function toPastWeek() {
  await userEvent.click(arrow(WEEK, "common.previous"));
  await userEvent.click(arrow(WEEK, "common.previous"));
  await waitFor(() => expect(lastListRequest()).toMatchObject({ delivery_week: 39 }));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  auth.roles = ["staff"];
  farm = {
    storages: [CELLAR, COLD_ROOM],
    articles: [CARROTS, LETTUCE, BEETROOT, RADISHES, APPLES, PUMPKINS],
    rows: [
      CARROTS_ROW,
      LETTUCE_ROW,
      BEETROOT_ROW,
      stockRow(APPLES, { storage: COLD_ROOM, theoretical_current_stock: 300 }),
      stockRow(PUMPKINS, { day: WEDNESDAY, theoretical_current_stock: 12 }),
      stockRow(PUMPKINS, { week: 42, theoretical_current_stock: 9 }),
      stockRow(CARROTS, { week: 40, theoretical_current_stock: 1000 }),
      stockRow(CARROTS, { week: 39, theoretical_current_stock: 950, amount: 900 }),
    ],
  };
  api.storages.mockReset().mockImplementation(async () => [...farm.storages]);
  api.shareArticles.mockReset().mockImplementation(async () => [...farm.articles]);
  api.counts.mockReset().mockImplementation(async (params: ListParams) => listed(params));
  api.saveCount.mockReset().mockImplementation(async (id: string, body: SaveBody) =>
    recordCount(id, body),
  );
  api.finalize.mockReset().mockImplementation(
    bulkChange((row) => ({ is_finalized: true, amount: row.amount ?? row.theoretical_current_stock })),
  );
  api.setAsExpected.mockReset().mockImplementation(
    bulkChange((row) => ({ amount: row.amount ?? row.theoretical_current_stock })),
  );
  api.setToZero.mockReset().mockImplementation(bulkChange((row) => ({ amount: row.amount ?? 0 })));
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("DocumentationCurrentStock loading", () => {
  it("opens on today in the first storage and lists that storage's stock", async () => {
    renderPage();

    await loaded();
    expect(selectedIn(DAY)).toBe("Tuesday, 06.10.2026");
    expect(selectedIn(STORAGE)).toBe("Cellar");
    expect(lastListRequest()).toEqual({
      year: 2026, delivery_week: 41, day_number: TUESDAY, storage: CELLAR.id,
    });
    expect(bodyRows()).toHaveLength(3);
    expect(screen.queryByText("Apples")).not.toBeInTheDocument();
    expect(screen.getByText("commissioning.inventory_end_of_day_note")).toBeInTheDocument();
    expect(screen.getByText("explainers.currentstock")).toBeInTheDocument();
  });

  it("shows a spinner over the table while the stock loads", async () => {
    let answer!: (rows: StockComparison[]) => void;
    const rows = new Promise<StockComparison[]>((resolve) => (answer = resolve));
    api.counts.mockImplementation(() => rows);
    renderPage();

    await waitFor(() => expect(lastListRequest()).toMatchObject({ storage: CELLAR.id }));
    expect(tableIsBusy()).toBe(true);
    expect(bodyRows()).toHaveLength(0);

    answer([CARROTS_ROW]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });

  it("says there is nothing to count when the storage holds no stock that day", async () => {
    farm.rows = [];
    renderPage();

    await waitFor(() => expect(lastListRequest()).toMatchObject({ storage: CELLAR.id }));
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("shows no rows when the stock cannot be loaded, and loads another day's", async () => {
    api.counts.mockImplementation(async (params: ListParams) => {
      if (params.day_number === TUESDAY) throw new Error("Network Error");
      return listed(params);
    });
    renderPage();

    await waitFor(() => expect(lastListRequest()).toMatchObject({ storage: CELLAR.id }));
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);

    await choose(DAY, "Wednesday, 07.10.2026");

    expect(await within(tableBody()).findByText("Pumpkins")).toBeInTheDocument();
  });
});

// ── The stock list ──────────────────────────────────────────────────────────

describe("DocumentationCurrentStock stock list", () => {
  it("shows each article's unit, expected stock, count and flags in the tenant's number format", async () => {
    renderPage();
    await loaded();

    for (const header of [ARTICLE, UNIT, /commissioning\.expected_stock/, COUNT]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(screen.queryByRole("columnheader", { name: "commissioning.size" })).not.toBeInTheDocument();
    const carrots = rowOf("Carrots");
    expect(within(carrots).getByText("commissioning.units.kg")).toBeInTheDocument();
    expect(within(carrots).getByText("1.250")).toBeInTheDocument();
    expect(within(carrots).getByText("-")).toBeInTheDocument();
    expect(within(carrots).getByText("commissioning.not_finalized")).toBeInTheDocument();
    const lettuce = rowOf("Lettuce");
    expect(within(lettuce).getByText("commissioning.units.pcs")).toBeInTheDocument();
    expect(within(lettuce).getByText("40")).toBeInTheDocument();
    expect(within(lettuce).getByText("38")).toBeInTheDocument();
    expect(within(lettuce).getByText("Two heads wilted")).toBeInTheDocument();
    const [forShares, forResellers] = within(lettuce)
      .getAllByRole("checkbox")
      .filter((box) => !box.closest(".ant-table-selection-column"));
    expect(forShares).toBeChecked();
    expect(forResellers).not.toBeChecked();
    // More handed out than came in leaves a negative expected stock.
    const beetroot = rowOf("Beetroot");
    expect(within(beetroot).getByText("-4")).toBeInTheDocument();
    expect(within(beetroot).getByText("0")).toBeInTheDocument();
    expect(within(beetroot).getByText("commissioning.finalized")).toBeInTheDocument();
  });

  it("formats the amounts in the tenant's number locale", async () => {
    tenantSettings.values = { number_locale: "en-US" };
    renderPage();
    await loaded();

    expect(within(rowOf("Carrots")).getByText("1,250")).toBeInTheDocument();
  });

  it("adds the size column when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await loaded();

    expect(screen.getByRole("columnheader", { name: "commissioning.size" })).toBeInTheDocument();
    expect(within(rowOf("Lettuce")).getByText("commissioning.large")).toBeInTheDocument();
    expect(within(rowOf("Carrots")).getByText("commissioning.medium")).toBeInTheDocument();
  });
});

// ── Week, day and storage ───────────────────────────────────────────────────

describe("DocumentationCurrentStock choosing the week, day and storage", () => {
  it("offers every day of the week with its date", async () => {
    renderPage();
    await loaded();

    expect(await optionsOf(screen.getByRole("combobox", { name: DAY }))).toEqual([
      "Monday, 05.10.2026", "Tuesday, 06.10.2026", "Wednesday, 07.10.2026",
      "Thursday, 08.10.2026", "Friday, 09.10.2026", "Saturday, 10.10.2026", "Sunday, 11.10.2026",
    ]);
  });

  it("dates the days in the tenant's date format", async () => {
    tenantSettings.values = { date_format: "YYYY-MM-DD" };
    renderPage();
    await loaded();

    expect(selectedIn(DAY)).toBe("Tuesday, 2026-10-06");
  });

  it("lists another day's stock when the day changes", async () => {
    renderPage();
    await loaded();

    await choose(DAY, "Wednesday, 07.10.2026");

    expect(await within(tableBody()).findByText("Pumpkins")).toBeInTheDocument();
    expect(within(rowOf("Pumpkins")).getByText("12")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(lastListRequest()).toMatchObject({ day_number: WEDNESDAY, storage: CELLAR.id });
  });

  it("lists another storage's stock when the storage changes", async () => {
    renderPage();
    await loaded();

    const storages = await optionsOf(screen.getByRole("combobox", { name: STORAGE }));
    expect(storages).toEqual(["Cellar", "Cold room"]);
    await userEvent.click(within(openDropdown()).getByText("Cold room"));

    expect(await within(tableBody()).findByText("Apples")).toBeInTheDocument();
    expect(within(rowOf("Apples")).getByText("300")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(lastListRequest()).toMatchObject({ day_number: TUESDAY, storage: COLD_ROOM.id });
  });

  it("loads the next week's stock from the week arrow", async () => {
    renderPage();
    await loaded();

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await within(tableBody()).findByText("Pumpkins")).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe("Tuesday, 13.10.2026");
    expect(lastListRequest()).toEqual({
      year: 2026, delivery_week: 42, day_number: TUESDAY, storage: CELLAR.id,
    });
  });
});

// ── Counting ────────────────────────────────────────────────────────────────

describe("DocumentationCurrentStock counting a listed article", () => {
  it("records the count for the chosen day and storage and shows it beside the expected stock", async () => {
    renderPage();
    await loaded();

    await startCount("Carrots", "-");
    // An article counted for the first time goes to the shares and the resellers.
    expect(flag("for_shares")).toBeChecked();
    expect(flag("for_resellers")).toBeChecked();
    await typeCount("1200");
    await save();

    await waitFor(() => expect(within(rowOf("Carrots")).getByText("1.200")).toBeInTheDocument());
    expect(within(rowOf("Carrots")).getByText("1.250")).toBeInTheDocument();
    expect(api.saveCount).toHaveBeenCalledTimes(1);
    const [id, body] = lastSave();
    expect(id).toBe(CARROTS_ROW.id);
    expect(Number(body.amount)).toBe(1200);
    expect(body).toMatchObject({
      share_article: CARROTS.id, unit: "KG", size: "M", for_shares: true, for_resellers: true,
      date: "2026-10-06", year: 2026, delivery_week: 41, day_number: TUESDAY, storage: CELLAR.id,
    });
  });

  it("keeps the article, unit and expected stock locked while a count is corrected", async () => {
    renderPage();
    await loaded();

    expect(await startCount("Lettuce", "38")).toHaveValue("38");
    const row = editingRow();
    expect(within(row).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(row).getByText("Lettuce")).toBeInTheDocument();
    expect(within(row).getByText("40")).toBeInTheDocument();
    expect(flag("for_shares")).toBeChecked();
    expect(flag("for_resellers")).not.toBeChecked();
    await typeCount("36");
    await userEvent.clear(within(row).getByRole("textbox", { name: NOTE }));
    await userEvent.type(within(row).getByRole("textbox", { name: NOTE }), "Four heads wilted");
    await save();

    await waitFor(() => expect(within(rowOf("Lettuce")).getByText("36")).toBeInTheDocument());
    expect(within(rowOf("Lettuce")).getByText("Four heads wilted")).toBeInTheDocument();
    const [id, body] = lastSave();
    expect(id).toBe(LETTUCE_ROW.id);
    expect(Number(body.amount)).toBe(36);
    expect(body).toMatchObject({
      share_article: LETTUCE.id, unit: "PCS", size: "L", for_shares: true, for_resellers: false,
      note: "Four heads wilted",
    });
  });

  it("saves the count with Enter", async () => {
    renderPage();
    await loaded();

    await startCount("Carrots", "-");
    await typeCount("1240{Enter}");

    await waitFor(() => expect(within(rowOf("Carrots")).getByText("1.240")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });

  it("takes whole positive numbers only", async () => {
    renderPage();
    await loaded();

    await startCount("Carrots", "-");
    await typeCount("-1a2,5");

    expect(countField()).toHaveValue("125");
  });

  it("keeps the row open and shows why when the server refuses the count", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const refusal = "Inventory entry is finalized — unfinalize it before changing the count.";
    api.saveCount.mockRejectedValue(serverError(refusal));
    renderPage();
    await loaded();

    await startCount("Beetroot", "0");
    await typeCount("3");
    await save();

    expect(await screen.findByText("table.save_failed_title")).toBeInTheDocument();
    expect(screen.getByText(`${refusal} — table.save_failed_hint`)).toBeInTheDocument();
    expect(countField()).toHaveValue("3");
  });
});

describe("DocumentationCurrentStock counting an article that is not listed", () => {
  it("records a count for the article in its usual unit and shows it on top", async () => {
    renderPage();
    await loaded();

    await newRowFor("Radishes");
    expect(within(editingRow()).getByTitle("commissioning.units.bunch")).toBeInTheDocument();
    await typeCount("6");
    await save();

    await waitFor(() => expect(bodyRows()).toHaveLength(4));
    expect(within(bodyRows()[0]).getByText("Radishes")).toBeInTheDocument();
    expect(within(bodyRows()[0]).getByText("6")).toBeInTheDocument();
    const [id, body] = lastSave();
    expect(id).toBe("art-radishes_BUNCH_M_st-cellar_2026_41_1");
    expect(Number(body.amount)).toBe(6);
    expect(body).toMatchObject({
      share_article: RADISHES.id, unit: "BUNCH", size: "M", for_shares: true, for_resellers: true,
      for_markets: false, washed: false, cleaned: false, date: "2026-10-06", storage: CELLAR.id,
    });
  });

  it("files a new count under the chosen day and storage", async () => {
    renderPage();
    await loaded();
    await choose(STORAGE, "Cold room");
    await within(tableBody()).findByText("Apples");
    await choose(DAY, "Thursday, 08.10.2026");
    await waitFor(() => expect(lastListRequest()).toMatchObject({ day_number: 3 }));

    await newRowFor("Radishes");
    await typeCount("2");
    await save();

    await waitFor(() => expect(api.saveCount).toHaveBeenCalledTimes(1));
    const [id, body] = lastSave();
    expect(id).toBe("art-radishes_BUNCH_M_st-cold-room_2026_41_3");
    expect(body).toMatchObject({ date: "2026-10-08", day_number: 3, storage: COLD_ROOM.id });
  });

  it("starts a new count when the staff presses +", async () => {
    renderPage();
    await loaded();

    await userEvent.keyboard("+");

    expect(within(editingRow()).getByRole("combobox", { name: ARTICLE })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
  });

  it("refuses a second count for an article, unit and size already listed", async () => {
    renderPage();
    await loaded();

    await newRowFor("Carrots");
    await typeCount("5");
    await save();

    const banner = "validation.unique.share_article_unit_size_must_be_unique — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    expect(api.saveCount).not.toHaveBeenCalled();
    expect(editingRow()).toBeInTheDocument();
  });

  it("counts a listed article again in another unit", async () => {
    renderPage();
    await loaded();

    await newRowFor("Carrots");
    await pickOption(within(editingRow()).getByRole("combobox", { name: UNIT }), "commissioning.units.pcs");
    await typeCount("30");
    await save();

    await waitFor(() => expect(api.saveCount).toHaveBeenCalledTimes(1));
    expect(lastSave()[0]).toBe("art-carrots_PCS_M_st-cellar_2026_41_1");
    await waitFor(() => expect(within(tableBody()).getAllByText("Carrots")).toHaveLength(2));
  });

  it("needs an article and a unit before it saves", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage();
    await loaded();

    await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
    await save();

    const banner = "table.save_failed_generic — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    for (const name of [ARTICLE, UNIT]) {
      const field = within(editingRow()).getByRole("combobox", { name });
      expect(field).toHaveAttribute("aria-invalid", "true");
    }
    expect(api.saveCount).not.toHaveBeenCalled();
  });

  it("offers an article added from the page right away", async () => {
    renderPage();
    await loaded();

    await userEvent.click(screen.getByRole("button", { name: ADD_ARTICLE }));
    farm.articles = [...farm.articles, LEEKS];
    const dialog = screen.getByRole("dialog", { name: "commissioning.add_share_article" });
    await userEvent.click(within(dialog).getByRole("button", { name: "save article" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
    await userEvent.click(within(editingRow()).getByRole("combobox", { name: ARTICLE }));
    expect(await within(openDropdown()).findByText("Leeks")).toBeInTheDocument();
  });
});

// ── Bulk actions ────────────────────────────────────────────────────────────

describe("DocumentationCurrentStock bulk actions", () => {
  it("finalizes the selected counts, an uncounted one at its expected stock", async () => {
    renderPage();
    await loaded();

    await userEvent.click(selectionBox(rowOf("Carrots")));
    await userEvent.click(selectionBox(rowOf("Lettuce")));
    await userEvent.click(screen.getByRole("button", { name: FINALIZE }));

    await waitFor(() => expect(api.finalize).toHaveBeenCalledTimes(1));
    expect([...(api.finalize.mock.calls[0][0] as { ids: string[] }).ids].sort()).toEqual(
      [CARROTS_ROW.id, LETTUCE_ROW.id].sort(),
    );
    await waitFor(() =>
      expect(within(rowOf("Carrots")).getByText("commissioning.finalized")).toBeInTheDocument(),
    );
    expect(within(rowOf("Lettuce")).getByText("commissioning.finalized")).toBeInTheDocument();
    expect(within(rowOf("Carrots")).getAllByText("1.250")).toHaveLength(2);
  });

  it.each([
    ["the expected stock", SET_AS_EXPECTED, api.setAsExpected, "1.250"],
    ["zero", SET_TO_ZERO, api.setToZero, "0"],
  ])("sets a selected uncounted article's count to %s", async (_to, action, endpoint, shown) => {
    renderPage();
    await loaded();

    await userEvent.click(selectionBox(rowOf("Carrots")));
    await userEvent.click(screen.getByRole("button", { name: action }));

    await waitFor(() => expect(endpoint).toHaveBeenCalledWith({ ids: [CARROTS_ROW.id] }));
    await waitFor(() => expect(within(rowOf("Carrots")).queryByText("-")).not.toBeInTheDocument());
    expect(within(rowOf("Carrots")).getAllByText(shown).length).toBeGreaterThan(0);
  });

  it("keeps the bulk actions off until a count is selected and never selects the unsaved row", async () => {
    renderPage();
    await loaded();

    expect(screen.getByText("commissioning.for_selected")).toBeInTheDocument();
    for (const action of [FINALIZE, SET_AS_EXPECTED, SET_TO_ZERO]) {
      expect(screen.getByRole("button", { name: action })).toBeDisabled();
    }
    await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));

    expect(selectionBox(editingRow())).toBeDisabled();
    expect(selectionBox(rowOf("Carrots"))).toBeEnabled();
  });
});

// ── Past weeks and roles ────────────────────────────────────────────────────

describe("DocumentationCurrentStock read-only stock", () => {
  /** No way to add a count or change one. */
  async function expectReadOnly(articleName: string, shownCount: string) {
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();

    await userEvent.click(within(rowOf(articleName)).getByText(shownCount));
    await userEvent.keyboard("+");

    expect(within(tableBody()).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(tableBody()).queryByRole("combobox")).not.toBeInTheDocument();
    expect(api.saveCount).not.toHaveBeenCalled();
  }

  it("shows a week more than a week back read-only", async () => {
    renderPage();
    await loaded();

    await toPastWeek();

    expect(screen.getByText(PAST_WEEK)).toBeInTheDocument();
    expect(await within(tableBody()).findByText("950")).toBeInTheDocument();
    await expectReadOnly("Carrots", "900");
    expect(screen.queryByRole("button", { name: FINALIZE })).not.toBeInTheDocument();
    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(document.querySelector(".ant-table-selection-column")).toBeNull();
    expect(screen.getByRole("button", { name: ADD_ARTICLE })).toBeDisabled();
  });

  it("still lets the staff count last week", async () => {
    renderPage();
    await loaded();

    await userEvent.click(arrow(WEEK, "common.previous"));

    expect(await within(tableBody()).findByText("1.000")).toBeInTheDocument();
    expect(lastListRequest()).toMatchObject({ delivery_week: 40 });
    expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
    expect(await startCount("Carrots", "-")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ARTICLE })).toBeEnabled();
  });

  it("shows the stock read-only to a user without a staff role", async () => {
    auth.roles = ["member"];
    renderPage();
    await loaded();

    await expectReadOnly("Carrots", "-");
  });

  it.each(["gardener", "management", "office"])("lets the %s role count", async (role) => {
    auth.roles = [role];
    renderPage();
    await loaded();

    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    expect(await startCount("Carrots", "-")).toBeInTheDocument();
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("DocumentationCurrentStock on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each article as a card with its expected stock, count, unit and flags", async () => {
    renderPage();
    await loaded("Lettuce");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const lettuce = cardOf("Lettuce");
    for (const text of [
      "commissioning.large", "commissioning.expected", "40", "commissioning.units.pcs",
      "commissioning.actual", "38", "Two heads wilted", "commissioning.for_shares",
    ]) {
      expect(within(lettuce).getByText(text)).toBeInTheDocument();
    }
    expect(within(lettuce).queryByText("commissioning.for_resellers")).not.toBeInTheDocument();
    const beetroot = cardOf("Beetroot");
    expect(within(beetroot).getByRole("img", { name: "commissioning.finalized" })).toBeInTheDocument();
    expect(within(beetroot).getByText("-4")).toBeInTheDocument();
    expect(within(beetroot).getByText("commissioning.for_resellers")).toBeInTheDocument();
    expect(within(cardOf("Carrots")).getByText("–")).toBeInTheDocument();
  });

  it("corrects a count from its card with the article and unit locked", async () => {
    renderPage();
    await loaded("Lettuce");

    await userEvent.click(cardOf("Lettuce"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("table.edit_record")).toBeInTheDocument();
    expect(dialogInput(ARTICLE, "combobox")).toBeDisabled();
    expect(dialogInput(UNIT, "combobox")).toBeDisabled();
    expect(dialogInput(COUNT, "textbox")).toHaveValue("38");
    await userEvent.clear(dialogInput(COUNT, "textbox"));
    await userEvent.type(dialogInput(COUNT, "textbox"), "36");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(cardOf("Lettuce")).getByText("36")).toBeInTheDocument();
    const [id, body] = lastSave();
    expect(id).toBe(LETTUCE_ROW.id);
    expect(Number(body.amount)).toBe(36);
    expect(body).toMatchObject({ date: "2026-10-06", day_number: TUESDAY, storage: CELLAR.id });
  });

  it("counts an article that is not listed", async () => {
    renderPage();
    await loaded("Lettuce");

    await userEvent.click(screen.getByRole("button", { name: ADD_CARD }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getAllByText("table.add_record").length).toBeGreaterThan(0);
    await pickOption(dialogInput(ARTICLE, "combobox"), "Radishes");
    await userEvent.type(dialogInput(COUNT, "textbox"), "6");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    const radishes = await waitFor(() => cardOf("Radishes"));
    expect(within(radishes).getByText("6")).toBeInTheDocument();
    expect(within(radishes).getAllByText("commissioning.units.bunch").length).toBeGreaterThan(0);
    expect(lastSave()[0]).toBe("art-radishes_BUNCH_M_st-cellar_2026_41_1");
  });

  it("labels the day in the short phone format and leaves out the bulk actions and the explainer", async () => {
    renderPage();
    await loaded("Lettuce");

    expect(selectedIn(DAY)).toBe("Tu, 06.10.");
    expect(screen.queryByRole("button", { name: FINALIZE })).not.toBeInTheDocument();
    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(screen.queryByText("explainers.currentstock")).not.toBeInTheDocument();
    expect(screen.getByText("commissioning.inventory_end_of_day_note")).toBeInTheDocument();
  });

  it("offers no new count in a past week", async () => {
    renderPage();
    await loaded("Lettuce");

    await toPastWeek();

    expect(screen.getByText(PAST_WEEK)).toBeInTheDocument();
    await waitFor(() => expect(within(cardOf("Carrots")).getByText("950")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: ADD_CARD })).not.toBeInTheDocument();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("DocumentationCurrentStock render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await loaded();
    await flushMicrotasks();

    // A setState-in-render loop makes thousands of commits.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});
