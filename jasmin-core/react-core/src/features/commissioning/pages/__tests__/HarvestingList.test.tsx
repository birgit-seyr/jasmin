/**
 * HarvestingList: what to harvest on one day, per article for the shares and the
 * orders, in units and packaging units (PU). The real selectors, EditableTable,
 * hooks, phone cards, dialog and PDF button are rendered; the generated clients
 * are the mocking boundary — real TanStack queries around spies that answer from
 * an in-memory farm. The PDF library and the download are stubbed. The clock is
 * frozen on Tuesday 6 October 2026 (ISO week 41, day number 1); the page reads
 * today when it mounts; the clock is set before the imports too.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Crate, DocumentationSummaryRow, ShareArticle, UnitEnum } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// The canonical mock, with one `t` for every render as react-i18next keeps it.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The tenant's settings as the page loaded them and as the server keeps them:
// saving a setting changes the server's, and refreshing the tenant reloads them.
const tenantStore = vi.hoisted(() => ({
  loaded: {} as Record<string, unknown>, saved: {} as Record<string, unknown>,
  listeners: new Set<() => void>(), current: null as unknown,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { useSyncExternalStore } = await import("react");
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  type Tenant = ReturnType<typeof makeUseTenantMock>;
  const load = (): Tenant =>
    makeUseTenantMock({
      getSetting: (key: string, defaultValue?: unknown) =>
        key in tenantStore.loaded ? tenantStore.loaded[key] : defaultValue,
      refreshTenant: async () => {
        tenantStore.loaded = { ...tenantStore.saved };
        tenantStore.current = load();
        tenantStore.listeners.forEach((listener) => listener());
      },
    });
  tenantStore.current = load();
  const subscribe = (listener: () => void) => {
    tenantStore.listeners.add(listener);
    return () => void tenantStore.listeners.delete(listener);
  };
  return { useTenant: () => useSyncExternalStore(subscribe, () => tenantStore.current as Tenant) };
});

// Phone or desktop viewport, per test.
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => viewport.mobile }));
vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles }, logout: () => {} }),
}));

const api = vi.hoisted(() => ({
  summary: vi.fn(), add: vi.fn(), update: vi.fn(), confirm: vi.fn(), shares: vi.fn(), deliveryDays: vi.fn(),
  totals: vi.fn(), variations: vi.fn(), crates: vi.fn(), shareArticles: vi.fn(), saveSettings: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryOptions = (path: string, request: (params: unknown) => unknown, params?: unknown) => ({
    queryKey: [`/api/commissioning/${path}/`, ...(params ? [params] : [])],
    queryFn: async () => request(params),
  });
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      return useQuery({ ...queryOptions(path, request, params), enabled: options?.query?.enabled });
    };
  const summary = "documentation_summary/summary";
  return {
    useCommissioningDocumentationSummarySummaryRetrieve: queryHook(summary, api.summary),
    getCommissioningDocumentationSummarySummaryRetrieveQueryKey: (params?: unknown) =>
      queryOptions(summary, api.summary, params).queryKey,
    commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate: (body: unknown) => api.add(body),
    commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate: (id: string, body: unknown) =>
      api.update(id, body),
    commissioningHarvestPartialUpdate: (id: string, body: unknown) => api.confirm(id, body),
    useCommissioningSharesList: queryHook("shares", api.shares),
    useCommissioningSharesDeliveryDaysList: queryHook("shares_delivery_days", api.deliveryDays),
    getCommissioningShareTypeVariationsTotalsRetrieveQueryOptions: (params: unknown) =>
      queryOptions("share_type_variations_totals", api.totals, params),
    useCommissioningShareTypeVariationsList: queryHook("share_type_variations", api.variations),
    useCommissioningCratesList: queryHook("crates", api.crates),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
  };
});
vi.mock("@shared/api/generated/tenants/tenants", () => ({
  tenantsSettingsUpdateCurrentSettingsUpdate: (body: unknown) => api.saveSettings(body),
}));

// The documents handed to the PDF renderer and the files saved, in order.
const printed = vi.hoisted(() => ({
  documents: [] as { template: string; props: Record<string, unknown> }[], files: [] as string[],
}));
// Partial: the PDF templates build their styles with the real library when they load.
vi.mock("@react-pdf/renderer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
  pdf: (document: { type: { name: string }; props: Record<string, unknown> }) => ({
    toBlob: async () => {
      printed.documents.push({ template: document.type.name, props: document.props });
      return new Blob(["%PDF-1.7"], { type: "application/pdf" });
    },
  }),
}));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (_blob: Blob, filename: string) => void printed.files.push(filename),
}));

import HarvestingList from "../HarvestingList";

// ── Fixtures ────────────────────────────────────────────────────────────────

const MONDAY = 0, TUESDAY = 1, WEDNESDAY = 2; // Backend day numbers: 0 = Monday … 6 = Sunday.
const E1: Crate = { id: "crate-e1", name: "Euro crate 30", short_name: "E1" };
const E2: Crate = { id: "crate-e2", name: "Euro crate 60", short_name: "E2" };
const CRATES = [E1, E2];

const article = (name: string, unit: UnitEnum, fields: Partial<ShareArticle> = {}): ShareArticle => ({
  id: `art-${name.toLowerCase()}`, name, default_movement_unit: unit, is_active: true, is_purchased: false, ...fields,
});
const CARROTS = article("Carrots", "KG", { default_kg_per_pu_harvest: "10", default_crate_harvest: E2.id });
const KOHLRABI = article("Kohlrabi", "PCS", { default_pieces_per_pu_harvest: "12", default_crate_harvest: E1.id });
const LETTUCE = article("Lettuce", "PCS"), RADISHES = article("Radishes", "BUNCH"), BEETROOT = article("Beetroot", "KG");
const LEEKS = article("Leeks", "KG"), POTATOES = article("Potatoes", "KG"), CELERIAC = article("Celeriac", "PCS");
const PUMPKINS = article("Pumpkins", "PCS");
const ARTICLES = [CARROTS, LETTUCE, RADISHES, BEETROOT, LEEKS, POTATOES, KOHLRABI, CELERIAC, PUMPKINS];

type Size = "S" | "M" | "L";
/** What one side — the shares or the orders — plans, holds in stock and adds by hand. */
interface Side { planned?: number; stock?: number; added?: number }
/** One article's harvest on one day, as the backend keeps it. */
interface Entry {
  id: string; article: ShareArticle; year: number; week: number; day: number; unit: UnitEnum; size: Size;
  shares: Side; orders: Side; perPu: number | null; crate: Crate | null; plot: string | null;
  bed: number | null; note: string; forecastNote: string | null; harvested: number | null;
}

const entry = (id: string, of: ShareArticle, fields: Partial<Omit<Entry, "id" | "article">> = {}): Entry => ({
  id, article: of, year: 2026, week: 41, day: TUESDAY, unit: of.default_movement_unit, size: "M", shares: {},
  orders: {}, perPu: null, crate: null, plot: null, bed: null, note: "", forecastNote: null, harvested: null, ...fields,
});

/** What the farm plans and harvests on Tuesday of week 41 and the days around it. */
const farmEntries = (): Entry[] => [
  entry("h-carrots", CARROTS, { shares: { planned: 30, stock: 10, added: 5 }, orders: { planned: 20 }, perPu: 10, crate: E2,
    plot: "Field A", bed: 3, note: "Pull by hand", forecastNote: "Early variety" }),
  entry("h-lettuce", LETTUCE, { size: "L", shares: { planned: 66 }, perPu: 12, crate: E1, plot: "Field A", bed: 1, harvested: 66 }),
  // More taken out than came in leaves a negative stock.
  entry("h-radishes", RADISHES, { orders: { planned: 15, stock: -3, added: 5 }, plot: "Greenhouse", note: "For the farm shop" }),
  // The stock already covers the plan.
  entry("h-beetroot", BEETROOT, { shares: { planned: 20, stock: 30 }, perPu: 8, crate: E2 }),
  entry("h-leeks", LEEKS, { shares: { planned: 16 }, perPu: 8, crate: E2, plot: "Field B", bed: 2 }),
  entry("h-potatoes", POTATOES),
  entry("h-kohlrabi", KOHLRABI, { day: WEDNESDAY, shares: { planned: 24 }, perPu: 12, crate: E1 }),
  entry("h-pumpkins-42", PUMPKINS, { week: 42, shares: { planned: 9 } }),
  entry("h-celeriac-40", CELERIAC, { week: 40, shares: { planned: 36 } }),
  entry("h-celeriac-39", CELERIAC, { week: 39, shares: { planned: 33, added: 2 } }),
  entry("h-leeks-2027", LEEKS, { year: 2027, week: 42, shares: { planned: 7 } }),
];

/** An amount of both sides together and of each side, under the summary's field names. */
const bySide = <F extends string>(field: F, item: Entry, side: keyof Side) => {
  const [share, order] = [item.shares[side] ?? 0, item.orders[side] ?? 0];
  const amounts = { [field]: share + order, [`${field}_share_content`]: share, [`${field}_order_content`]: order };
  return amounts as Record<F | `${F}_share_content` | `${F}_order_content`, number>;
};

/** A list row the way the summary endpoint sends it. */
const summaryRow = (item: Entry): DocumentationSummaryRow => ({
  id: item.id, share_article: item.article.id ?? null, share_article_name: item.article.name, unit: item.unit,
  size: item.size, note: item.note, is_finalized: false, theoretical_id: null, additional_id: null,
  harvest_amount: item.harvested == null ? null : item.harvested.toFixed(2),
  ...bySide("theoretical_harvest_amount", item, "planned"), ...bySide("theoretical_current_stock", item, "stock"),
  ...bySide("additional_theoretical_harvest_amount", item, "added"),
  forecast_plot_name: item.plot, forecast_bed_number: item.bed, forecast_note: item.forecastNote,
  amount_per_pu: item.perPu == null ? null : item.perPu.toFixed(3),
  harvesting_crate: item.crate?.id ?? null, harvesting_crate_name: item.crate?.short_name ?? null,
  seller: null, seller_name: null, price_per_unit: null, organic_status: null,
});

/** Every week the farm delivers on Wednesday and Thursday what it harvests on
 *  Tuesday, and on Friday what it harvests on Wednesday. */
const sharesOf = ({ year, delivery_week }: { year: number; delivery_week: number }) =>
  [[2, 1], [3, 1], [4, 2]].map(([deliveryDay, harvestDay]) => ({
    id: `share-${delivery_week}-${deliveryDay}`, year, delivery_week, delivery_day_number: deliveryDay, harvesting_day: harvestDay,
    delivery_day: `dd-${deliveryDay}`, share_type_variation: "stv-veg-s" }));
const DELIVERY_DAYS = ["dd-wed", "dd-thu", "dd-fri"].map((id, index) => ({ id, day_number: index + 2, valid_from: "2026-01-05" }));
const VARIATIONS = (
  [["stv-veg-s", "S", "Vegetables", 1], ["stv-veg-m", "M", "Vegetables", 2], ["stv-veg-l", "L", "Vegetables", 3],
    ["stv-fruit-m", "M", "Fruit", 1]] as const
).map(([id, size, share_type_name, sort_order]) => ({ id, size, share_type_name, sort_order }));
const counts = (...rows: [string, string, number][]) =>
  rows.map(([id, size, total_quantity]) =>
    ({ share__share_type_variation_id: id, share__share_type_variation__size: size, total_quantity }));
/** The shares delivered on each delivery day, per variation. */
const SHARE_COUNTS: Record<string, ReturnType<typeof counts>> = {
  "dd-wed": counts(["stv-veg-s", "S", 40], ["stv-veg-m", "M", 25]),
  "dd-thu": counts(["stv-veg-s", "S", 10], ["stv-fruit-m", "M", 12], ["stv-veg-l", "L", 0]),
  "dd-fri": counts(["stv-veg-m", "M", 30]),
};

/** What the in-memory farm holds; the request spies answer from it. */
let farm: { entries: Entry[] };
type SummaryParams = { year: number; delivery_week: number; day_number: number };
type SaveBody = Record<string, unknown>;
const listed = ({ year, delivery_week, day_number }: SummaryParams) =>
  farm.entries.filter((item) => item.year === year && item.week === delivery_week && item.day === day_number).map(summaryRow);
const amountOf = (value: unknown) => (value == null || value === "" ? 0 : Number(value));

/** A save's PU, crate, note and added amounts, as the service applies them: it
 *  clears a PU or crate the body leaves out and keeps a note it leaves out. */
function withSaved(before: Entry, body: SaveBody): Entry {
  const added = (side: Side, key: string) => (key in body ? { ...side, added: amountOf(body[key]) } : side);
  return {
    ...before, shares: added(before.shares, "amount_share_content"), orders: added(before.orders, "amount_order_content"),
    perPu: amountOf(body.amount_per_pu), crate: CRATES.find((crate) => crate.id === body.harvesting_crate) ?? null,
    note: typeof body.note === "string" ? body.note : before.note,
  };
}

function changeEntry(id: string, change: (before: Entry) => Entry) {
  const before = farm.entries.find((item) => item.id === id);
  if (!before) throw new Error(`No harvest ${id}`);
  const saved = change(before);
  farm.entries = farm.entries.map((item) => (item.id === id ? saved : item));
  return summaryRow(saved);
}

function addEntry(body: SaveBody) {
  const of = ARTICLES.find((item) => item.id === body.share_article);
  if (!of) throw new Error(`No article ${String(body.share_article)}`);
  const place = { year: Number(body.year), week: Number(body.delivery_week), day: Number(body.day_number) };
  const saved = withSaved(entry(`h-new-${of.id}`, of, { ...place, unit: body.unit as UnitEnum, size: body.size as Size }), body);
  farm.entries = [...farm.entries, saved];
  return summaryRow(saved);
}

const serverError = (message: string) =>
  Object.assign(new Error(message), { isAxiosError: true, response: { status: 400, data: { code: "validation_error", message } } });

// ── Helpers ─────────────────────────────────────────────────────────────────

const YEAR = "common.year", WEEK = "common.week", DAY = "common.delivery_day";
const HARVEST_DAY = "commissioning.harvesting_day", PAST_WEEK = "table.past_week_readonly";
const ARTICLE = "commissioning.vegetables_and_fruits", UNIT = "commissioning.unit", SIZE = "commissioning.size";
const SHARES = "commissioning.title_share_content", ORDERS = "commissioning.title_order_content";
const PLANNED = "commissioning.theoretical_harvest", IN_STOCK = "commissioning.still_in_stock";
const TO_HARVEST = "commissioning.to_harvest", ADDED = "commissioning.additional_theoretical_harvest";
const TOTAL = "commissioning.amount_harvesting_list", PER_PU = "commissioning.per_pu";
const TEAM_SHARES = `${TOTAL} / (${SHARES})`, TEAM_ORDERS = `${TOTAL} / (${ORDERS})`;
const CRATE = "commissioning.harvesting_crate", NOTE = "commissioning.note", ACTIONS = "table.actions";
const OFFICE_VIEW = "commissioning.office_view", TEAM_VIEW = "commissioning.gardener_view";
const ROUND_UP = "commissioning.round_up_to_full_vpe", CRATES_NEEDED = "commissioning.needed_harvesting_crates";
const CONFIRM = "commissioning.actual_harvest", SET_AS_EXPECTED = "commissioning.set_as_expected_harvest";
const ADD_ROW = /table\.add_plus_icon/, EDIT = "table.edit", SAVE = "table.save";
const KG = "commissioning.units.kg", PCS = "commissioning.units.pcs", BUNCHES = "commissioning.units.bunch", PU = "commissioning.pu";

/** A grouped column's leaf, named after the group and the leaf. */
const under = (group: string, leaf: string) => `${group}: ${leaf}`;
/** Matches an accessible name that contains ``key`` (buttons add their icon's name). */
const containing = (key: string) => new RegExp(key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
/** ``element``, or a failure that says what is missing. */
function present<T>(element: T | null | undefined, missing: string): T {
  if (!element) throw new Error(missing);
  return element;
}

/** The text of an element by line: a line break or a block starts a new one. */
function textOf(element: Element): string {
  const lines = [""];
  const walk = (node: Node): void =>
    node.childNodes.forEach((child) => {
      const block = child.nodeName === "BR" || child.nodeName === "DIV";
      if (block) lines.push("");
      if (child.nodeType === Node.TEXT_NODE) lines[lines.length - 1] += child.textContent ?? "";
      else walk(child);
      if (block) lines.push("");
    });
  walk(element);
  return lines.map((line) => line.trim()).filter(Boolean).join(" / ");
}

const isBusy = (container: Element = document.body) => container.querySelector('[aria-busy="true"]') !== null;

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<HarvestingList />)}</QueryClientProvider>);
  return { profiler };
}

/** Renders the page and waits until the day's articles are on screen. */
async function openPage(articleName = "Carrots") {
  const page = renderPage();
  await screen.findByText(articleName);
  await waitFor(() => expect(isBusy()).toBe(false));
  return page;
}

const lastListRequest = () => api.summary.mock.lastCall?.[0] as SummaryParams | undefined;
const totalsRequest = (day: string) => ({ year: 2026, delivery_week: 41, delivery_day: day, physical_share_type_variations: true });
const listRequest = (fields: Partial<SummaryParams & { is_past: boolean }> = {}) =>
  ({ year: 2026, delivery_week: 41, day_number: TUESDAY, is_past: false, model: "harvest", is_preparation_lists: true, ...fields });

/** The label a selector shows for its current value. */
const selectedIn = (name: string) =>
  screen.getByRole("combobox", { name }).closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent;
const openDropdown = () => {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  return present(Array.from(open).pop(), "No dropdown is open");
};
const optionIn = (dropdown: HTMLElement, label: string) => {
  const options = Array.from(dropdown.querySelectorAll<HTMLElement>(".ant-select-item-option"));
  return present(options.find((option) => option.textContent === label), `No option ${label}`);
};

async function pickOption(combobox: HTMLElement, label: string) {
  await userEvent.click(combobox);
  await userEvent.click(await waitFor(() => optionIn(openDropdown(), label)));
}

const choose = (name: string, label: string) => pickOption(screen.getByRole("combobox", { name }), label);
/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  return within(present(stepper, `No stepper around ${name}`)).getByRole("button", { name: direction });
}

/** The harvest table; the crate summary below it is a table too. */
const harvestTable = () => present(document.querySelector<HTMLElement>(".ant-table-wrapper"), "The table is not rendered");
const bodyRows = () => Array.from(harvestTable().querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));
const rowOf = (text: string) =>
  present(within(harvestTable()).getByText(text).closest<HTMLElement>("tr"), `No table row shows ${text}`);

/** The harvest table's columns, left to right. */
function columnNames(): string[] {
  const [top, bottom] = Array.from(harvestTable().querySelectorAll<HTMLElement>("thead > tr"));
  const leaves = bottom ? Array.from(bottom.querySelectorAll<HTMLElement>(":scope > th")) : [];
  return Array.from(top.querySelectorAll<HTMLElement>(":scope > th")).flatMap((header) => {
    const span = Number(header.getAttribute("colspan") ?? 1);
    return span === 1 ? [textOf(header)] : leaves.splice(0, span).map((leaf) => under(textOf(header), textOf(leaf)));
  });
}

/** A row's cell texts, each under its column's name. */
function cellsOf(row: HTMLElement): Record<string, string> {
  const cells = Array.from(row.querySelectorAll<HTMLElement>(":scope > td"));
  return Object.fromEntries(columnNames().map((name, index) => [name, cells[index] ? textOf(cells[index]) : ""]));
}

const articlesListed = () => bodyRows().map((row) => cellsOf(row)[ARTICLE]);
const totalOf = (name: string, side = SHARES) => cellsOf(rowOf(name))[under(TOTAL, side)];
const editingRow = () => present(screen.getByRole("button", { name: SAVE }).closest<HTMLElement>("tr"), "No row is being edited");
const field = (name: string) => within(editingRow()).getByRole("textbox", { name });
const save = () => userEvent.click(screen.getByRole("button", { name: SAVE }));

async function retype(name: string, text: string) {
  await userEvent.clear(field(name));
  await userEvent.type(field(name), text);
}

const cellTexts = (rows: Iterable<HTMLTableRowElement>) =>
  Array.from(rows, (row) => Array.from(row.cells, (cell) => cell.textContent ?? ""));
/** The crates the day's harvest needs, as the desktop's summary table lists them. */
function cratesNeeded(): string[][] {
  const table = screen.getByRole("columnheader", { name: (name) => name.startsWith(CRATES_NEEDED) }).closest("table");
  return cellTexts(present(table, "No crate summary").querySelectorAll<HTMLTableRowElement>("tbody > tr.ant-table-row"));
}

/** The share totals of the delivery days the harvest is for. */
function shareTotals(): string[] {
  const card = screen.getByText("commissioning.variations_totals").closest<HTMLElement>(".variations-totals-card");
  return within(present(card, "No share totals")).queryAllByRole("listitem").map((item) => item.textContent ?? "");
}

const deliveryDaysShown = () => screen.getByText("commissioning.delivery_day_shares").textContent;
const downloadButton = () => screen.getByRole("button", { name: containing("download.harvesting_list") });
const roundUpBox = () => screen.getByRole("checkbox", { name: ROUND_UP });

/** No way to add a row or to change one. */
async function expectReadOnly(articleName: string, shownAmount: string) {
  expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: EDIT })).not.toBeInTheDocument();
  await userEvent.click(within(rowOf(articleName)).getByText(shownAmount));
  await userEvent.keyboard("+");
  expect(within(harvestTable()).queryByRole("textbox")).not.toBeInTheDocument();
  expect(within(harvestTable()).queryByRole("combobox")).not.toBeInTheDocument();
  expect(api.update).not.toHaveBeenCalled();
  expect(api.add).not.toHaveBeenCalled();
}

/** The phone list from top to bottom: plot headings in brackets and each card's article. */
function phoneList(): string[] {
  const list = present(document.querySelector<HTMLElement>(".mobile-card-list"), "No cards are rendered");
  return Array.from(list.querySelectorAll<HTMLElement>(".harvest-plot-header, .mobile-card-item"), (item) =>
    item.classList.contains("harvest-plot-header")
      ? `[${item.textContent}]`
      : (ARTICLES.find(({ name }) => within(item).queryByText(name))?.name ?? "A card without an article"),
  );
}

/** The phone card of an article. */
function cardOf(name: string): HTMLElement {
  const cards = Array.from(document.querySelectorAll<HTMLElement>(".mobile-card-item"));
  return present(cards.find((card) => within(card).queryByText(name)), `No card shows ${name}`);
}

/** Each amount line of a card: what for, how much, how many PUs. */
const amountsOn = (card: HTMLElement) => cellTexts(card.querySelectorAll("tr"));
const confirmButtonOf = (name: string) => within(cardOf(name)).getByTitle(CONFIRM);
/** The round button turns green once the harvest is confirmed and stays red until then. */
const looksConfirmed = (button: HTMLElement) => button.classList.contains("is-confirmed");
const confirmDialog = () => screen.findByRole("dialog", { name: CONFIRM });

/** The crates the day's harvest needs, as the phone's card lists them. */
function phoneCratesNeeded(): string[][] {
  const card = present(screen.getByText(CRATES_NEEDED).closest<HTMLElement>(".ant-card"), "No crate card");
  return Array.from(card.querySelectorAll(".ant-card-body > div"), (line) => Array.from(line.children, (part) => part.textContent ?? ""));
}

type PdfConfig = { include?: boolean; title?: unknown; dataKey?: string; tickBox?: boolean; render?: (row: SaveBody) => unknown };
type PdfColumn = { dataIndex?: string; pdf?: PdfConfig };

/** The header and the rows the PDF prints, read through its (flat) columns as the template does. */
function printedTable(props: Record<string, unknown>) {
  const columns = (props.columns as PdfColumn[]).filter((column) => column.pdf?.include);
  const cell = ({ pdf, dataIndex }: PdfColumn, row: SaveBody) =>
    pdf?.tickBox ? "☐" : String((pdf?.render ? pdf.render(row) : row[pdf?.dataKey ?? dataIndex ?? ""]) ?? "");
  return {
    header: columns.map((column) => String(column.pdf?.title ?? "")),
    rows: (props.data as SaveBody[]).map((row) => columns.map((column) => cell(column, row))),
  };
}

/** Sets the tenant's settings as loaded by the page and kept by the server. */
function tenantHas(settings: Record<string, unknown>) {
  tenantStore.loaded = { ...settings };
  tenantStore.saved = { ...settings };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantHas({});
  viewport.mobile = false;
  auth.roles = ["office"];
  Object.assign(printed, { documents: [], files: [] });
  farm = { entries: farmEntries() };
  api.summary.mockReset().mockImplementation(async (params: SummaryParams) => listed(params));
  api.add.mockReset().mockImplementation(async (body: SaveBody) => addEntry(body));
  api.update.mockReset().mockImplementation(async (id: string, body: SaveBody) => changeEntry(id, (old) => withSaved(old, body)));
  api.confirm.mockReset().mockImplementation(async (id: string, body: SaveBody) =>
    changeEntry(id, (old) => ({ ...old, harvested: Number(body.amount) })));
  api.shares.mockReset().mockImplementation(async (params: SummaryParams) => sharesOf(params));
  api.deliveryDays.mockReset().mockResolvedValue(DELIVERY_DAYS);
  api.totals.mockReset().mockImplementation(async ({ delivery_day }: { delivery_day: string }) =>
    ({ variations: SHARE_COUNTS[delivery_day] ?? [] }));
  api.variations.mockReset().mockResolvedValue(VARIATIONS);
  api.crates.mockReset().mockResolvedValue(CRATES);
  api.shareArticles.mockReset().mockResolvedValue(ARTICLES);
  api.saveSettings.mockReset().mockImplementation(async ({ settings }: { settings: Record<string, unknown> }) => {
    tenantStore.saved = { ...tenantStore.saved, ...settings };
    return { ...tenantStore.saved };
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("loading and rows", () => {
  it("opens on today's harvest, the deliveries it is for and their share totals", async () => {
    await openPage();
    expect(screen.getByRole("heading", { level: 1, name: "commissioning.harvesting_list" })).toBeInTheDocument();
    expect(lastListRequest()).toEqual(listRequest());
    expect(selectedIn(DAY)).toBe(`${HARVEST_DAY} Tuesday, 06.10.2026`);
    expect(columnNames()).not.toContain(SIZE); // The farm doesn't use sizes.
    // Potatoes are planned at zero for the day.
    expect(articlesListed()).toEqual(["Carrots", "Lettuce", "Radishes", "Beetroot", "Leeks"]);
    expect(deliveryDaysShown()).toBe("commissioning.delivery_day_sharesWednesday, 07.10.2026 / Thursday, 08.10.2026");
    await waitFor(() =>
      expect(shareTotals()).toEqual(["Fruit commissioning.M: 12", "Vegetables commissioning.S: 50", "Vegetables commissioning.M: 25"]),
    );
    // Next week's shares too: a harvest late in the week can be for an early delivery of the next.
    expect(api.shares.mock.calls).toEqual([[{ year: 2026, delivery_week: 41 }], [{ year: 2026, delivery_week: 42 }]]);
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-10" });
    expect(api.totals.mock.calls.map(([params]) => params)).toEqual([totalsRequest("dd-wed"), totalsRequest("dd-thu")]);
    expect(screen.getByText("explainers.harvesting_list")).toBeInTheDocument();
    expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
  });

  it("shows what the shares and the orders plan, hold in stock, still need, add and come to, and the crates", async () => {
    tenantHas({ show_size_column: true });
    await openPage();
    expect(columnNames()).toEqual([
      ACTIONS, ARTICLE, UNIT, SIZE,
      ...[PLANNED, IN_STOCK, TO_HARVEST, ADDED, TOTAL].flatMap((group) => [under(group, SHARES), under(group, ORDERS)]),
      PER_PU, CRATE, NOTE,
    ]);
    expect(screen.getByRole("img", { name: "tooltip.additional_theoretical_harvest" })).toBeInTheDocument();
    expect(cellsOf(rowOf("Carrots"))).toMatchObject({
      [UNIT]: KG, [SIZE]: "commissioning.medium",
      [under(PLANNED, SHARES)]: "30,00", [under(PLANNED, ORDERS)]: "20,00", [under(IN_STOCK, SHARES)]: "10,00", [under(IN_STOCK, ORDERS)]: "",
      [under(TO_HARVEST, SHARES)]: "20,00", [under(TO_HARVEST, ORDERS)]: "20,00", [under(ADDED, SHARES)]: "5,00", [under(ADDED, ORDERS)]: "",
      [under(TOTAL, SHARES)]: `25,00 ${KG} / 2,5 ${PU}`, [under(TOTAL, ORDERS)]: `20,00 ${KG} / 2,0 ${PU}`,
      [PER_PU]: `10,00 ${KG}/${PU}`, [CRATE]: "E2",
      [NOTE]: "Pull by hand, Early variety / commissioning.plot: Field A, commissioning.bed_number: 3",
    });
    expect(cellsOf(rowOf("Lettuce"))).toMatchObject({
      [UNIT]: PCS, [SIZE]: "commissioning.large", [under(TOTAL, SHARES)]: `66,0 ${PCS} / 5,5 ${PU}`, [under(TOTAL, ORDERS)]: "",
      [CRATE]: "E1", [NOTE]: "commissioning.plot: Field A, commissioning.bed_number: 1",
    });
    // A negative stock counts as none; without a PU the amounts stay in bunches.
    expect(cellsOf(rowOf("Radishes"))).toMatchObject({
      [UNIT]: BUNCHES, [under(IN_STOCK, ORDERS)]: "", [under(TO_HARVEST, ORDERS)]: "15,0", [under(ADDED, ORDERS)]: "5,0",
      [under(TOTAL, ORDERS)]: `20,0 ${BUNCHES}`, [PER_PU]: "", [CRATE]: "-", [NOTE]: "For the farm shop / commissioning.plot: Greenhouse",
    });
    // The stock already covers the plan.
    expect(cellsOf(rowOf("Beetroot"))).toMatchObject({
      [under(IN_STOCK, SHARES)]: "30,00", [under(TO_HARVEST, SHARES)]: "", [under(TOTAL, SHARES)]: "",
    });
    // 66 lettuces at 12 fill 6 small crates; 45 kg carrots at 10 kg and 16 kg leeks at 8 kg fill 5 + 2 large ones.
    expect(cratesNeeded()).toEqual([["E1", "6"], ["E2", "7"]]);
  });

  it.each([
    ["the default German format", {}, `1.250,0 ${PCS} / 156,3 ${PU}`, "8,0", ["1.300,50", "0,30", "1.300,20"]],
    ["the tenant's English format", { number_locale: "en-US" }, `1,250.0 ${PCS} / 156.3 ${PU}`, "8.0", ["1,300.50", "0.30", "1,300.20"]],
  ])("writes amounts at the unit's precision, totals and PUs in %s", async (_format, settings, total, perPu, kilos) => {
    tenantHas(settings); // The potatoes' stock is 0.1 + 0.2, which is 0.30000000000000004 in floating point.
    farm.entries.push(entry("h-pumpkins", PUMPKINS, { shares: { planned: 1300, stock: 100, added: 50 }, perPu: 8 }),
      entry("h-potatoes-fractions", POTATOES, { shares: { planned: 1300.5, stock: 0.1 + 0.2 } }));
    await openPage("Pumpkins");
    expect(cellsOf(rowOf("Pumpkins"))).toMatchObject({ [under(TOTAL, SHARES)]: total, [PER_PU]: `${perPu} ${PCS}/${PU}` });
    expect([PLANNED, IN_STOCK, TO_HARVEST].map((group) => cellsOf(rowOf("Potatoes"))[under(group, SHARES)])).toEqual(kilos);
  });

  it("says there is nothing to harvest on a day without plans and keeps the download off", async () => {
    await openPage();

    await choose(DAY, `${HARVEST_DAY} Monday, 05.10.2026`);
    await waitFor(() => expect(lastListRequest()).toEqual(listRequest({ day_number: MONDAY })));
    await waitFor(() => expect(isBusy()).toBe(false));
    expect(within(harvestTable()).getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(cratesNeeded()).toEqual([]);
    expect(downloadButton()).toBeDisabled();
    // Nothing the farm delivers is harvested on a Monday.
    expect(deliveryDaysShown()).toBe("commissioning.delivery_day_shares");
    expect(shareTotals()).toEqual([]);
    expect(screen.getByText("common.no_data")).toBeInTheDocument();
  });

  it.each([["the table", false], ["the cards on a phone", true]])("shows a spinner instead of %s while loading", async (_where, mobile) => {
    viewport.mobile = mobile;
    // The list answers only when the test says so.
    let answer!: (rows: DocumentationSummaryRow[]) => void;
    api.summary.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    renderPage();

    await waitFor(() => expect(isBusy()).toBe(true));
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    // A phone lists the crates needed only once there is something to harvest.
    expect(screen.queryByText(CRATES_NEEDED) === null).toBe(mobile);
    answer(listed(listRequest()));
    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(isBusy()).toBe(false));
  });

  it("shows no rows and keeps the download off when the list cannot be loaded, and loads another day", async () => {
    api.summary.mockImplementation(async (params: SummaryParams) => {
      if (params.day_number === TUESDAY) throw new Error("Network Error");
      return listed(params);
    });
    renderPage();

    await waitFor(() => expect(api.summary).toHaveBeenCalled());
    await waitFor(() => expect(isBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);
    expect(downloadButton()).toBeDisabled();
    await choose(DAY, `${HARVEST_DAY} Wednesday, 07.10.2026`);
    expect(await within(harvestTable()).findByText("Kohlrabi")).toBeInTheDocument();
    expect(downloadButton()).toBeEnabled();
  });
});

describe("choosing the day and the week", () => {
  it("offers every day of the week as the harvest day and lists the chosen one with its deliveries", async () => {
    await openPage();

    await userEvent.click(screen.getByRole("combobox", { name: DAY }));
    const days = ["Monday, 05", "Tuesday, 06", "Wednesday, 07", "Thursday, 08", "Friday, 09", "Saturday, 10", "Sunday, 11"];
    const options = openDropdown().querySelectorAll(".ant-select-item-option-content");
    expect(Array.from(options, (option) => option.textContent)).toEqual(days.map((day) => `${HARVEST_DAY} ${day}.10.2026`));
    await userEvent.click(optionIn(openDropdown(), `${HARVEST_DAY} Wednesday, 07.10.2026`));
    await waitFor(() => expect(articlesListed()).toEqual(["Kohlrabi"]));
    expect(totalOf("Kohlrabi")).toBe(`24,0 ${PCS} / 2,0 ${PU}`);
    expect(lastListRequest()).toEqual(listRequest({ day_number: WEDNESDAY }));
    expect(deliveryDaysShown()).toBe("commissioning.delivery_day_sharesFriday, 09.10.2026");
    await waitFor(() => expect(shareTotals()).toEqual(["Vegetables commissioning.M: 30"]));
    expect(api.totals).toHaveBeenLastCalledWith(totalsRequest("dd-fri"));
  });

  it("loads the next week's list from the week arrow, and the same week of another year", async () => {
    await openPage();

    await userEvent.click(arrow(WEEK, "common.next"));
    await waitFor(() => expect(articlesListed()).toEqual(["Pumpkins"]));
    expect(selectedIn(DAY)).toBe(`${HARVEST_DAY} Tuesday, 13.10.2026`);
    expect(lastListRequest()).toEqual(listRequest({ delivery_week: 42 }));
    expect(deliveryDaysShown()).toBe("commissioning.delivery_day_sharesWednesday, 14.10.2026 / Thursday, 15.10.2026");
    expect(api.shares).toHaveBeenCalledWith({ year: 2026, delivery_week: 43 });
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-24" }); // The week after, for a harvest serving it.

    await choose(YEAR, "2027");
    await waitFor(() => expect(articlesListed()).toEqual(["Leeks"]));
    expect(selectedIn(DAY)).toBe(`${HARVEST_DAY} Tuesday, 19.10.2027`);
    expect(lastListRequest()).toEqual(listRequest({ year: 2027, delivery_week: 42 }));
  });
});

describe("team view", () => {
  it("keeps what the team needs, sorted by plot and bed, until the office view is back", async () => {
    tenantHas({ show_size_column: true });
    await openPage();

    await userEvent.click(screen.getByRole("button", { name: containing(TEAM_VIEW) }));
    await waitFor(() => expect(columnNames()).toEqual([ACTIONS, ARTICLE, TEAM_SHARES, TEAM_ORDERS, PER_PU, CRATE, NOTE]));
    // Beetroot needs no harvest: its stock covers the plan.
    expect(articlesListed()).toEqual(["Lettuce (commissioning.large)", "Carrots", "Leeks", "Radishes"]);
    expect(cellsOf(rowOf("Carrots"))).toMatchObject({
      [TEAM_SHARES]: `25,00 ${KG} / 2,5 ${PU}`, [TEAM_ORDERS]: `20,00 ${KG} / 2,0 ${PU}`, [PER_PU]: `10,00 ${KG}/${PU}`, [CRATE]: "E2",
      [NOTE]: "Pull by hand, Early variety / commissioning.plot: Field A, commissioning.bed_number: 3",
    });
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(downloadButton()).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: containing(OFFICE_VIEW) }));
    await waitFor(() => expect(columnNames()).toContain(under(PLANNED, SHARES)));
    expect(columnNames()).toContain(SIZE);
    expect(articlesListed()).toEqual(["Carrots", "Lettuce", "Radishes", "Beetroot", "Leeks"]);
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
  });

  it("lets the team change a row's crate and PU but not its amounts or note", async () => {
    await openPage();
    await userEvent.click(screen.getByRole("button", { name: containing(TEAM_VIEW) }));
    await waitFor(() => expect(columnNames()).toContain(TEAM_SHARES));

    await userEvent.click(within(rowOf("Carrots")).getByText("E2"));
    expect(within(editingRow()).getAllByRole("textbox").map((input) => input.getAttribute("aria-label"))).toEqual([PER_PU]);
    await pickOption(within(editingRow()).getByRole("combobox", { name: CRATE }), "E1");
    await save();
    await waitFor(() => expect(cellsOf(rowOf("Carrots"))[CRATE]).toBe("E1"));
    expect(api.update).toHaveBeenCalledWith("h-carrots", expect.objectContaining({
      amount_share_content: 5, amount_order_content: 0, amount_per_pu: "10.000", harvesting_crate: E1.id, note: "Pull by hand",
    }));
    expect(cratesNeeded()).toEqual([["E1", "11"], ["E2", "2"]]);
  });
});

describe("rounding up to full PUs", () => {
  it("rounds each total up to full PUs once switched on, keeps the choice for the farm, and goes back", async () => {
    await openPage();
    expect(roundUpBox()).not.toBeChecked();

    await userEvent.click(roundUpBox());
    expect(api.saveSettings).toHaveBeenLastCalledWith({ settings: { round_up_to_full_pu_harvesting: true } });
    await waitFor(() => expect(roundUpBox()).toBeChecked());
    expect([totalOf("Carrots"), totalOf("Carrots", ORDERS), totalOf("Lettuce")]).toEqual([
      `30,00 ${KG} / 3 ${PU}`, `20,00 ${KG} / 2 ${PU}`, `72,0 ${PCS} / 6 ${PU}`,
    ]);
    // Without a PU there is nothing to round.
    expect(totalOf("Radishes", ORDERS)).toBe(`20,0 ${BUNCHES}`);
    expect(cratesNeeded()).toEqual([["E1", "6"], ["E2", "7"]]);

    await userEvent.click(roundUpBox());
    expect(api.saveSettings).toHaveBeenLastCalledWith({ settings: { round_up_to_full_pu_harvesting: false } });
    await waitFor(() => expect(totalOf("Carrots")).toBe(`25,00 ${KG} / 2,5 ${PU}`));
    expect(roundUpBox()).not.toBeChecked();
  });

  it("opens rounded when the farm rounds, and stays so and says why when the change cannot be saved", async () => {
    tenantHas({ round_up_to_full_pu_harvesting: true });
    api.saveSettings.mockRejectedValue(serverError("Settings cannot be changed right now."));
    await openPage();
    expect(roundUpBox()).toBeChecked();
    expect(totalOf("Carrots")).toBe(`30,00 ${KG} / 3 ${PU}`);

    await userEvent.click(roundUpBox());
    expect(await screen.findByText("Settings cannot be changed right now.")).toBeInTheDocument();
    expect(roundUpBox()).toBeChecked();
    expect(totalOf("Carrots")).toBe(`30,00 ${KG} / 3 ${PU}`);
  });
});

describe("correcting the plan", () => {
  it("corrects the amounts added for the shares and the orders and recomputes the totals and crates", async () => {
    await openPage();

    await userEvent.click(within(rowOf("Carrots")).getByText("5,00"));
    // The article, its unit and its size stay as they are.
    for (const name of [ARTICLE, UNIT, SIZE]) expect(within(editingRow()).queryByRole("combobox", { name })).not.toBeInTheDocument();
    expect(field(SHARES)).toHaveValue("5");
    expect(field(ORDERS)).toHaveValue("0");
    await retype(SHARES, "12");
    await retype(ORDERS, "3");
    await save();
    await waitFor(() =>
      expect(cellsOf(rowOf("Carrots"))).toMatchObject({
        [under(ADDED, SHARES)]: "12,00", [under(ADDED, ORDERS)]: "3,00",
        [under(TOTAL, SHARES)]: `32,00 ${KG} / 3,2 ${PU}`, [under(TOTAL, ORDERS)]: `23,00 ${KG} / 2,3 ${PU}`,
      }),
    );
    expect(screen.queryByRole("button", { name: SAVE })).not.toBeInTheDocument();
    expect(api.update).toHaveBeenCalledTimes(1);
    // What the endpoint reads; the table also sends the row's display fields, which it ignores.
    expect(api.update).toHaveBeenCalledWith("h-carrots", expect.objectContaining({
      model: "harvest", year: 2026, delivery_week: 41, day_number: TUESDAY, share_article: CARROTS.id, unit: "KG",
      size: "M", note: "Pull by hand", amount_share_content: "12", amount_order_content: "3", amount_per_pu: "10.000",
      harvesting_crate: E2.id,
    }));
    expect(api.add).not.toHaveBeenCalled();
    // 55 kg of carrots fill 6 large crates now.
    expect(cratesNeeded()).toEqual([["E1", "6"], ["E2", "8"]]);
  });

  it("changes a row's PU, crate and note", async () => {
    await openPage();

    await userEvent.click(within(rowOf("Carrots")).getByRole("button", { name: EDIT }));
    await retype(PER_PU, "5");
    await pickOption(within(editingRow()).getByRole("combobox", { name: CRATE }), "E1");
    expect(field(NOTE)).toHaveValue("Pull by hand");
    await retype(NOTE, "Leave the tops on");
    await save();
    await waitFor(() =>
      expect(cellsOf(rowOf("Carrots"))).toMatchObject({
        [PER_PU]: `5,00 ${KG}/${PU}`, [CRATE]: "E1", [under(TOTAL, SHARES)]: `25,00 ${KG} / 5,0 ${PU}`,
        [NOTE]: "Leave the tops on, Early variety / commissioning.plot: Field A, commissioning.bed_number: 3",
      }),
    );
    expect(api.update).toHaveBeenCalledWith("h-carrots", expect.objectContaining({
      amount_share_content: 5, amount_order_content: 0, amount_per_pu: "5", harvesting_crate: E1.id, note: "Leave the tops on",
    }));
    // 45 kg of carrots at 5 kg fill 9 small crates.
    expect(cratesNeeded()).toEqual([["E1", "15"], ["E2", "2"]]);
  });

  it("adds an article the day doesn't list yet, with the article's PU and crate filled in", async () => {
    await openPage();

    await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
    await pickOption(within(editingRow()).getByRole("combobox", { name: ARTICLE }), "Kohlrabi");
    expect(within(editingRow()).getByTitle(PCS)).toBeInTheDocument();
    expect(field(PER_PU)).toHaveValue("12");
    expect(within(editingRow()).getByTitle("E1")).toBeInTheDocument();
    await userEvent.type(field(SHARES), "6");
    await save();
    await waitFor(() =>
      expect(cellsOf(bodyRows()[0])).toMatchObject({
        [ARTICLE]: "Kohlrabi", [under(ADDED, SHARES)]: "6,0", [CRATE]: "E1", [under(TOTAL, SHARES)]: `6,0 ${PCS} / 0,5 ${PU}`,
      }),
    );
    expect(bodyRows()).toHaveLength(6);
    expect(api.shareArticles).toHaveBeenCalledWith({ is_harvest_share_article: "true", is_active: "true", is_purchased: "false" });
    expect(api.add).toHaveBeenCalledTimes(1);
    expect(api.add).toHaveBeenCalledWith(expect.objectContaining({
      model: "harvest", year: 2026, delivery_week: 41, day_number: TUESDAY, share_article: KOHLRABI.id, unit: "PCS",
      size: "M", amount_share_content: "6", amount_per_pu: "12", harvesting_crate: E1.id,
    }));
    expect(cratesNeeded()).toEqual([["E1", "7"], ["E2", "7"]]);

    // "+" starts another row; one for an article, unit and size already listed is refused.
    await userEvent.keyboard("+");
    await pickOption(within(editingRow()).getByRole("combobox", { name: ARTICLE }), "Carrots");
    await userEvent.type(field(SHARES), "3");
    await save();
    const banner = "validation.unique.share_article_unit_size_must_be_unique — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    expect(api.add).toHaveBeenCalledTimes(1);
    expect(editingRow()).toBeInTheDocument();
  });

  it("keeps the row open and shows why when the server refuses the change", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const refusal = "The harvest of this day is already documented.";
    api.update.mockRejectedValue(serverError(refusal));
    await openPage();

    await userEvent.click(within(rowOf("Carrots")).getByText("5,00"));
    await retype(SHARES, "9");
    await save();
    expect(await screen.findByText("table.save_failed_title")).toBeInTheDocument();
    expect(screen.getByText(`${refusal} — table.save_failed_hint`)).toBeInTheDocument();
    expect(field(SHARES)).toHaveValue("9");
  });
});

describe("past weeks and roles", () => {
  it("still lets last week's plan be corrected but shows the week before read-only", async () => {
    await openPage();

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(totalOf("Celeriac")).toBe(`36,0 ${PCS}`));
    expect(lastListRequest()).toEqual(listRequest({ delivery_week: 40 }));
    expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    await userEvent.click(within(rowOf("Celeriac")).getByRole("button", { name: EDIT }));
    expect(field(SHARES)).toBeInTheDocument();

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastListRequest()).toEqual(listRequest({ delivery_week: 39, is_past: true })));
    expect(await screen.findByText(PAST_WEEK)).toBeInTheDocument();
    await waitFor(() => expect(totalOf("Celeriac")).toBe(`35,0 ${PCS}`));
    await expectReadOnly("Celeriac", "2,0");
  });

  it.each(["gardener", "staff", "office", "admin"])("lets the %s role add rows and correct them", async (role) => {
    auth.roles = [role];
    await openPage();
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    await userEvent.click(within(rowOf("Carrots")).getByText("5,00"));
    expect(field(SHARES)).toHaveValue("5");
  });

  it("shows the list read-only to management", async () => {
    auth.roles = ["management"];
    await openPage();
    await expectReadOnly("Carrots", "5,00");
    expect(downloadButton()).toBeEnabled();
  });
});

describe("download", () => {
  it("prints what there is to harvest in the team layout with the crates and share totals", async () => {
    await openPage();
    await waitFor(() => expect(shareTotals()).toHaveLength(3));

    await userEvent.click(downloadButton());
    await waitFor(() => expect(printed.files).toEqual(["commissioning.harvesting_list_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf"]));
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("HarvestingListPDF");
    expect(props).toMatchObject({
      title: "commissioning.KW 41/2026 · COMMON.WEEKDAY_TUESDAY", subtitle: "", pill: "commissioning.harvesting_list",
      dataFirstPageOnly: [{ crate_name: "E1", quantity: 6 }, { crate_name: "E2", quantity: 7 }],
    });
    // The same share totals as on screen, without the variation that has none.
    const totals = ([["stv-veg-s", "S", 50], ["stv-veg-m", "M", 25], ["stv-fruit-m", "M", 12]] as const)
      .map(([id, size, totalQuantity]) => ({ id, size, totalQuantity }));
    expect(props.variationsTotals).toEqual(expect.arrayContaining(totals));
    expect(props.variationsTotals).toHaveLength(3);
    const plot = (name: string, bed: number) => `commissioning.plot: ${name}, commissioning.bed_number: ${bed}`;
    // Beetroot needs no harvest, so the office view's row isn't printed.
    expect(printedTable(props)).toEqual({
      header: [ARTICLE, SHARES, ORDERS, PER_PU, "commissioning.harvesting_crate_short", NOTE, "✓"],
      rows: [
        ["Lettuce (commissioning.large)", `66,0 ${PCS} - 5,5 ${PU}`, "", `12,0 ${PCS}/${PU}`, "E1", plot("Field A", 1), "☐"],
        [
          "Carrots", `25,00 ${KG} - 2,5 ${PU}`, `20,00 ${KG} - 2,0 ${PU}`, `10,00 ${KG}/${PU}`, "E2",
          `Pull by hand, Early variety\n${plot("Field A", 3)}`, "☐",
        ],
        ["Leeks", `16,00 ${KG} - 2,0 ${PU}`, "", `8,00 ${KG}/${PU}`, "E2", plot("Field B", 2), "☐"],
        ["Radishes", "", `20,0 ${BUNCHES}`, "", "", "For the farm shop\ncommissioning.plot: Greenhouse", "☐"],
      ],
    });
  });
});

describe("on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("lists what to harvest as cards under their plots, without an editor or the office controls", async () => {
    await openPage();
    expect(document.querySelector(".ant-table-wrapper")).toBeNull();
    // Beetroot needs no harvest: its stock covers the plan.
    expect(phoneList()).toEqual(["[Field A]", "Lettuce", "Carrots", "[Field B]", "Leeks", "[Greenhouse]", "Radishes"]);
    expect(within(cardOf("Lettuce")).getByText("commissioning.large")).toBeInTheDocument();
    const carrots = cardOf("Carrots");
    expect(within(carrots).getByText("commissioning.bed_number: 3")).toBeInTheDocument();
    expect(within(carrots).getByText(`10,00 ${KG}/${PU}`)).toBeInTheDocument();
    expect(amountsOn(carrots)).toEqual([
      [`${SHARES}:`, `25,00 ${KG}`, `2,5 ${PU}`], [`${ORDERS}:`, `20,00 ${KG}`, `2,0 ${PU}`], ["Σ", `45,00 ${KG}`, `4,5 ${PU}`],
    ]);
    expect(within(carrots).getByText("Pull by hand, Early variety")).toBeInTheDocument();
    expect(amountsOn(cardOf("Radishes"))).toEqual([[`${ORDERS}:`, `20,0 ${BUNCHES}`, ""], ["Σ", `20,0 ${BUNCHES}`, ""]]);
    expect(selectedIn(DAY)).toBe("Tu, 06.10.");
    expect(phoneCratesNeeded()).toEqual([["E1", "6"], ["E2", "7"]]);
    await waitFor(() => expect(shareTotals()).toHaveLength(3));
    expect(roundUpBox()).not.toBeChecked();
    for (const name of [/table\.add/, containing(OFFICE_VIEW), containing(TEAM_VIEW), containing("download")]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByText("commissioning.delivery_day_shares")).not.toBeInTheDocument();
    expect(screen.queryByText("explainers.harvesting_list")).not.toBeInTheDocument();
    // Rows are edited on the desktop; a card opens no editor.
    expect(carrots).not.toHaveAttribute("role", "button");
    await userEvent.click(within(carrots).getByText("Carrots"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms a harvest from a card with the amount entered in the tenant's number format, and turns its button green", async () => {
    auth.roles = ["gardener"];
    await openPage();
    expect(looksConfirmed(confirmButtonOf("Carrots"))).toBe(false);

    await userEvent.click(confirmButtonOf("Carrots"));
    const dialog = await confirmDialog();
    expect(within(dialog).getByText("Carrots")).toBeInTheDocument();
    expect(dialog).toHaveTextContent(`commissioning.expected_harvest: 45 ${KG}`);
    const amount = within(dialog).getByRole("spinbutton", { name: CONFIRM });
    expect(amount).toHaveAttribute("aria-valuenow", "45");
    // The tenant writes numbers the German way, with a decimal comma.
    await userEvent.clear(amount);
    await userEvent.type(amount, "43,5");
    const readsBefore = api.summary.mock.calls.length;
    await userEvent.click(within(dialog).getByRole("button", { name: SET_AS_EXPECTED }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: CONFIRM })).not.toBeInTheDocument());
    expect(api.confirm).toHaveBeenCalledTimes(1);
    expect(api.confirm).toHaveBeenCalledWith("h-carrots", { amount: 43.5, year: 2026, delivery_week: 41, day_number: TUESDAY });
    expect(looksConfirmed(confirmButtonOf("Carrots"))).toBe(true);
    // The list is read again with the harvest recorded.
    await waitFor(() => expect(api.summary.mock.calls.length).toBeGreaterThan(readsBefore));
  });

  it("starts from the amount already harvested and saves nothing when cancelled", async () => {
    await openPage();
    expect(looksConfirmed(confirmButtonOf("Lettuce"))).toBe(true);

    await userEvent.click(confirmButtonOf("Lettuce"));
    const dialog = await confirmDialog();
    expect(within(dialog).getByText("Lettuce (commissioning.large)")).toBeInTheDocument();
    expect(within(dialog).getByRole("spinbutton")).toHaveAttribute("aria-valuenow", "66");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: CONFIRM })).not.toBeInTheDocument());
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it("keeps the dialog open with the amount when the server refuses the harvest", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.confirm.mockRejectedValue(serverError("The harvest of this day is finalized."));
    await openPage();

    await userEvent.click(confirmButtonOf("Carrots"));
    const dialog = await confirmDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: SET_AS_EXPECTED }));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: SET_AS_EXPECTED })).toBeEnabled());
    expect(within(dialog).getByRole("spinbutton")).toHaveAttribute("aria-valuenow", "45");
    expect(looksConfirmed(confirmButtonOf("Carrots"))).toBe(false);
  });

  it("shows a past week's cards without confirm buttons", async () => {
    await openPage();

    await userEvent.click(arrow(WEEK, "common.previous"));
    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(phoneList()).toEqual(["Celeriac"]));
    expect(screen.getByText(PAST_WEEK)).toBeInTheDocument();
    expect(screen.queryByTitle(CONFIRM)).not.toBeInTheDocument();
  });
});

describe("render loop", () => {
  it.each([["the desktop", false], ["a phone", true]])("settles after loading on %s instead of looping", async (_device, mobile) => {
    viewport.mobile = mobile;
    const { profiler } = await openPage();
    await flushMicrotasks();
    // A setState-in-render loop makes thousands of commits.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});
