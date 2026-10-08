/**
 * The washing list and the cleaning list: how much of each article the farm
 * has to wash or clean on one day — the theoretical amount the plan asks for,
 * less what is still in stock, plus an additional amount entered by hand. Both
 * pages are AdditionalTheoreticalSummaryList with their own documentation
 * model, labels, edit roles, PDF button and phone card, so the tests render the
 * real pages and run the shared behaviour against each. The real week and day
 * selectors, EditableTable, column hooks, phone cards and PDF buttons are
 * rendered. The generated commissioning client is the mocking boundary: its
 * hooks are real TanStack queries around spies that answer from an in-memory
 * farm. The PDF library and the browser download are stubbed, so no real PDF
 * is rendered.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The page reads today's week and
 * weekday when it mounts.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticle, UnitEnum } from "@shared/api/generated/models";
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
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles }, logout: () => {} }),
}));

const api = vi.hoisted(() => ({
  summary: vi.fn(), shareArticles: vi.fn(), add: vi.fn(), update: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      return useQuery({
        queryKey: queryKey(path, params),
        queryFn: async () => request(params),
        enabled: options?.query?.enabled,
      });
    };
  const summary = "documentation_summary/summary";
  return {
    useCommissioningDocumentationSummarySummaryRetrieve: queryHook(summary, api.summary),
    getCommissioningDocumentationSummarySummaryRetrieveQueryKey: (params?: unknown) =>
      queryKey(summary, params),
    commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate: (body: unknown) =>
      api.add(body),
    commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate: (id: string, body: unknown) =>
      api.update(id, body),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
  };
});

// The pages only need their own download button; the barrel would also load
// every other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  WashingListPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/WashingListPDFGenerator")
  ).default,
  CleaningListPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/CleaningListPDFGenerator")
  ).default,
}));

// The documents handed to the PDF renderer and the files saved, in order.
const printed = vi.hoisted(() => ({
  documents: [] as { template: string; props: Record<string, unknown> }[],
  files: [] as string[],
}));
// Partial: the PDF templates build their styles with the real library when
// they load.
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
  downloadBlob: (_blob: Blob, filename: string) => {
    printed.files.push(filename);
  },
}));

import CleaningList from "@features/commissioning/pages/CleaningList";
import WashingList from "@features/commissioning/pages/WashingList";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Backend day numbers: 0 = Monday … 6 = Sunday.
const TUESDAY = 1;
const WEDNESDAY = 2;

type Model = "washamount" | "cleanamount";
type Size = "S" | "M" | "L";

const article = (
  id: string, name: string, unit: UnitEnum, flags: Partial<ShareArticle> = {},
): ShareArticle => ({ id, name, default_movement_unit: unit, is_active: true, is_purchased: false, ...flags });
const CARROTS = article("art-carrots", "Carrots", "KG");
const LETTUCE = article("art-lettuce", "Lettuce", "PCS");
const BEETROOT = article("art-beetroot", "Beetroot", "KG");
const RADISHES = article("art-radishes", "Radishes", "BUNCH");
const POTATOES = article("art-potatoes", "Potatoes", "KG");
const KOHLRABI = article("art-kohlrabi", "Kohlrabi", "PCS");
const PUMPKINS = article("art-pumpkins", "Pumpkins", "PCS");
const LEEKS = article("art-leeks", "Leeks", "KG");
const CELERIAC = article("art-celeriac", "Celeriac", "PCS");
const APPLES = article("art-apples", "Apples", "KG", { is_purchased: true });
const KALE = article("art-kale", "Kale", "KG", { is_active: false });
const HONEY = article("art-honey", "Honey", "PCS");
/** Honey comes from the farm's bees, not from its fields. */
const NOT_HARVESTED = new Set([HONEY.id]);

/** One article's washing or cleaning on one day, as the backend keeps it. */
interface Entry {
  id: string; model: Model; article: ShareArticle;
  year: number; week: number; day: number; unit: UnitEnum; size: Size;
  theoretical: number | null; stock: number | null; additional: number | null; note: string;
}

function entry(model: Model, of: ShareArticle, fields: Partial<Omit<Entry, "id" | "model" | "article">> = {}): Entry {
  const place = {
    year: 2026, week: 41, day: TUESDAY, unit: of.default_movement_unit, size: "M" as Size,
    theoretical: null, stock: null, additional: null, note: "", ...fields,
  };
  const id = [model, of.id, place.unit, place.size, place.year, place.week, place.day].join("_");
  return { id, model, article: of, ...place };
}

/** What either list holds for Tuesday of week 41 and the days around it. */
const entriesFor = (model: Model): Entry[] => [
  entry(model, CARROTS, { theoretical: 40, stock: 15, additional: 5, note: "Scrub the soil off" }),
  entry(model, LETTUCE, { size: "L", theoretical: 60 }),
  // More taken out than came in leaves a negative stock.
  entry(model, BEETROOT, { theoretical: 20, stock: -4, additional: -5 }),
  entry(model, RADISHES, { theoretical: 10, stock: 30 }),
  entry(model, POTATOES, { theoretical: 0, stock: 50 }),
  entry(model, KOHLRABI, { day: WEDNESDAY, theoretical: 12 }),
  entry(model, PUMPKINS, { week: 42, theoretical: 9 }),
  entry(model, CARROTS, { week: 40, theoretical: 36 }),
  entry(model, CARROTS, { week: 39, theoretical: 33, additional: 2 }),
  entry(model, POTATOES, { year: 2027, theoretical: 7 }),
];

/** A list row the way the summary endpoint sends it for the entry's model. */
const summaryRow = (item: Entry): Record<string, unknown> => ({
  id: item.id, share_article: item.article.id, share_article_name: item.article.name,
  unit: item.unit, size: item.size, note: item.note,
  theoretical_id: item.theoretical == null ? null : `theoretical-${item.id}`,
  additional_id: item.additional == null ? null : `additional-${item.id}`,
  [`${item.model}_amount`]: null,
  [`theoretical_${item.model}_amount`]: item.theoretical,
  [`additional_theoretical_${item.model}_amount`]: item.additional,
  theoretical_current_stock: item.stock,
  forecast_plot_name: null, forecast_bed_number: null, forecast_note: null, amount_per_pu: null,
  harvesting_crate: null, harvesting_crate_name: null, seller: null, seller_name: null,
  price_per_unit: null,
});

/** What the in-memory farm holds; the request spies answer from it. */
let farm: { articles: ShareArticle[]; entries: Entry[] };

type SummaryParams = {
  year: number; delivery_week: number; day_number: number; is_past: boolean; model: Model;
};
type ArticleParams = { is_active?: boolean; is_purchased?: boolean; is_harvest_share_article?: boolean };
type SaveBody = Record<string, unknown>;

const listed = (params: SummaryParams) =>
  farm.entries
    .filter((item) => item.model === params.model && item.year === params.year)
    .filter((item) => item.week === params.delivery_week && item.day === params.day_number)
    .map(summaryRow);

const offered = (params: ArticleParams = {}) =>
  farm.articles.filter(
    (item) =>
      (params.is_active === undefined || item.is_active === params.is_active) &&
      (params.is_purchased === undefined || item.is_purchased === params.is_purchased) &&
      (params.is_harvest_share_article === undefined ||
        !NOT_HARVESTED.has(item.id) === params.is_harvest_share_article),
  );

const amountOf = (value: unknown) => (value == null || value === "" ? null : Number(value));
const noteOf = (body: SaveBody, before: Entry) =>
  typeof body.note === "string" ? body.note : before.note;

/** Stores the additional amount of the body's article, unit and size on the
 *  body's day and answers like the backend: with the entry's list row. */
function addAdditional(body: SaveBody) {
  const of = farm.articles.find((item) => item.id === body.share_article);
  if (!of) throw new Error(`No article ${String(body.share_article)}`);
  const fresh = entry(body.model as Model, of, {
    year: Number(body.year), week: Number(body.delivery_week), day: Number(body.day_number),
    unit: body.unit as UnitEnum, size: body.size as Size,
  });
  const before = farm.entries.find((item) => item.id === fresh.id) ?? fresh;
  const saved = { ...before, additional: amountOf(body.amount), note: noteOf(body, before) };
  farm.entries = [...farm.entries.filter((item) => item.id !== saved.id), saved];
  return summaryRow(saved);
}

function updateAdditional(id: string, body: SaveBody) {
  const before = farm.entries.find((item) => item.id === id);
  if (!before) throw new Error(`No entry ${id}`);
  const additional = "amount" in body ? amountOf(body.amount) : before.additional;
  const saved = { ...before, additional, note: noteOf(body, before) };
  farm.entries = farm.entries.map((item) => (item.id === id ? saved : item));
  return summaryRow(saved);
}

const serverError = (message: string) =>
  Object.assign(new Error(message), {
    isAxiosError: true, response: { status: 400, data: { code: "validation_error", message } },
  });

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

// ── The two pages ───────────────────────────────────────────────────────────

interface PageConfig {
  name: string; Page: ComponentType; model: Model; title: string; daySuffix: string;
  teamView: string; explainer: string; theoreticalHeader: string; toProcessHeader: string;
  additionalHeader: string; additionalTooltip: string; amountHeader: string; download: string;
  /** The article only this page's list holds that Tuesday, its total, and the other page's. */
  ownArticle: ShareArticle; ownTotal: string; otherArticle: ShareArticle;
  /** The roles that may add and correct additional amounts, and the roles that only read. */
  editors: string[]; readers: string[];
}

const WASHING: PageConfig = {
  name: "WashingList", Page: WashingList, model: "washamount",
  title: "commissioning.washing_list", daySuffix: "commissioning.washing_day",
  teamView: "commissioning.wash_team_view", explainer: "explainers.washing_list",
  theoreticalHeader: "commissioning.theoretical_harvest", toProcessHeader: "commissioning.to_wash",
  additionalHeader: "commissioning.additional_theoretical_wash",
  additionalTooltip: "tooltip.additional_theoretical_wash_amount",
  amountHeader: "commissioning.amount_washing_list", download: "download.washing_list",
  ownArticle: LEEKS, ownTotal: "8,00 commissioning.units.kg", otherArticle: CELERIAC,
  editors: ["office", "admin"], readers: ["gardener", "staff", "management", "member"],
};

const CLEANING: PageConfig = {
  name: "CleaningList", Page: CleaningList, model: "cleanamount",
  title: "commissioning.cleaning_list", daySuffix: "commissioning.cleaning_day",
  teamView: "commissioning.clean_team_view", explainer: "explainers.cleaning_list",
  theoreticalHeader: "commissioning.theoretical_clean_amounts", toProcessHeader: "commissioning.to_clean",
  additionalHeader: "commissioning.additional_theoretical_clean",
  additionalTooltip: "tooltip.additional_theoretical_clean_amount",
  amountHeader: "commissioning.amount_cleaning_list", download: "download.cleaning_list",
  ownArticle: CELERIAC, ownTotal: "14,0 commissioning.units.pcs", otherArticle: LEEKS,
  editors: ["gardener", "staff", "office", "admin"], readers: ["management", "member"],
};

const PAGES = [WASHING, CLEANING];

// ── Helpers ─────────────────────────────────────────────────────────────────

const YEAR = "common.year";
const WEEK = "common.week";
const DAY = "common.delivery_day";
const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const SIZE = "commissioning.size";
const STILL_IN_STOCK = "commissioning.still_in_stock";
const NOTE = "commissioning.note";
const OFFICE_VIEW = "commissioning.office_view";
const ADD_ROW = /table\.add_plus_icon/;
const ADD_CARD = /table\.add_record/;
const EDIT = "table.edit";
const SAVE = "table.save";
const PAST_WEEK = "table.past_week_readonly";

/** Matches an accessible name that contains ``key`` (buttons add their icon's name). */
const containing = (key: string) => new RegExp(key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
/** Matches a column header that starts with ``key`` (a tooltip icon adds its own name). */
const startsWith = (key: string) => (name: string) => name.startsWith(key);

function renderPage(Page: ComponentType) {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<Page />)}</QueryClientProvider>);
  return { profiler };
}

const lastListRequest = () => api.summary.mock.lastCall?.[0] as SummaryParams | undefined;

/** The label a selector shows for its current value. */
function selectedIn(name: string): string {
  const select = screen.getByRole("combobox", { name }).closest(".ant-select");
  return select?.querySelector(".ant-select-selection-item")?.textContent ?? "";
}

/** ``element``, or a failure that says what is missing. */
function present<T>(element: T | null | undefined, missing: string): T {
  if (!element) throw new Error(missing);
  return element;
}

function openDropdown(): HTMLElement {
  const open = Array.from(document.querySelectorAll<HTMLElement>(".ant-select-dropdown")).filter(
    (dropdown) => !dropdown.classList.contains("ant-select-dropdown-hidden"),
  );
  return present(open[open.length - 1], "No select dropdown is open");
}

const optionIn = (dropdown: HTMLElement, label: string) =>
  present(
    Array.from(dropdown.querySelectorAll<HTMLElement>(".ant-select-item-option")).find(
      (item) => item.textContent === label,
    ),
    `No option ${label} is offered`,
  );

async function optionsOf(combobox: HTMLElement): Promise<string[]> {
  await userEvent.click(combobox);
  return Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map(
    (option) => option.textContent ?? "",
  );
}

async function pickOption(combobox: HTMLElement, label: string) {
  await userEvent.click(combobox);
  await userEvent.click(await waitFor(() => optionIn(openDropdown(), label)));
}

const choose = (name: string, label: string) =>
  pickOption(screen.getByRole("combobox", { name }), label);

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  return within(present(stepper, `No stepper around ${name}`)).getByRole("button", { name: direction });
}

const tableBody = () =>
  present(document.querySelector<HTMLElement>(".ant-table-tbody"), "The table is not rendered");
const bodyRows = () => Array.from(tableBody().querySelectorAll<HTMLElement>("tr.ant-table-row"));
const rowOf = (text: string) =>
  present(within(tableBody()).getByText(text).closest<HTMLElement>("tr"), `No table row shows ${text}`);

/** The row's cell texts, each under its column header's text. */
function cellsByHeader(row: HTMLElement): Record<string, string> {
  const headers = Array.from(document.querySelectorAll<HTMLElement>(".ant-table-thead > tr > th"));
  const cells = Array.from(row.querySelectorAll<HTMLElement>(":scope > td"));
  return Object.fromEntries(
    headers.map((header, index) => [header.textContent ?? "", cells[index]?.textContent ?? ""]),
  );
}

const editingRow = () =>
  present(screen.getByRole("button", { name: SAVE }).closest<HTMLElement>("tr"), "No row is being edited");

const additionalInput = (page: PageConfig) =>
  within(editingRow()).getByRole("textbox", { name: page.additionalHeader });
const noteInput = () => within(editingRow()).getByRole("textbox", { name: NOTE });
const save = () => userEvent.click(screen.getByRole("button", { name: SAVE }));

async function typeAdditional(page: PageConfig, text: string) {
  await userEvent.clear(additionalInput(page));
  await userEvent.type(additionalInput(page), text);
}

const downloadButton = (page: PageConfig) =>
  screen.getByRole("button", { name: containing(page.download) });

/** The phone card that shows ``text``. */
function cardOf(text: string): HTMLElement {
  const list = present(document.querySelector<HTMLElement>(".mobile-card-list"), "No cards are rendered");
  return present(within(list).getByText(text).closest<HTMLElement>(".mobile-card-item"), `No card shows ${text}`);
}

const isBusy = (container: HTMLElement = document.body) =>
  container.querySelector('[aria-busy="true"]') !== null;
const tableIsBusy = () => {
  const table = document.querySelector<HTMLElement>(".ant-table-wrapper");
  return table !== null && isBusy(table);
};

/** Waits until the day's articles are on screen. */
async function loaded(articleName = "Carrots") {
  await screen.findByText(articleName);
  await waitFor(() => expect(isBusy()).toBe(false));
}

/** No way to add a row or to change one. */
async function expectReadOnly(articleName: string, shownAdditional: string) {
  expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: EDIT })).not.toBeInTheDocument();

  await userEvent.click(within(rowOf(articleName)).getByText(shownAdditional));
  await userEvent.keyboard("+");

  expect(within(tableBody()).queryByRole("textbox")).not.toBeInTheDocument();
  expect(within(tableBody()).queryByRole("combobox")).not.toBeInTheDocument();
  expect(api.update).not.toHaveBeenCalled();
  expect(api.add).not.toHaveBeenCalled();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  auth.roles = ["office"];
  printed.documents = [];
  printed.files = [];
  farm = {
    articles: [
      CARROTS, LETTUCE, BEETROOT, RADISHES, POTATOES, KOHLRABI, PUMPKINS, LEEKS, CELERIAC, APPLES, KALE, HONEY,
    ],
    entries: [
      ...entriesFor("washamount"),
      entry("washamount", LEEKS, { theoretical: 8 }),
      ...entriesFor("cleanamount"),
      entry("cleanamount", CELERIAC, { theoretical: 14 }),
    ],
  };
  api.summary.mockReset().mockImplementation(async (params: SummaryParams) => listed(params));
  api.shareArticles.mockReset().mockImplementation(async (params?: ArticleParams) => offered(params));
  api.add.mockReset().mockImplementation(async (body: SaveBody) => addAdditional(body));
  api.update
    .mockReset()
    .mockImplementation(async (id: string, body: SaveBody) => updateAdditional(id, body));
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ── Loading and rows ────────────────────────────────────────────────────────

describe.each(PAGES)("$name loading and rows", (page) => {
  it("opens on today and lists the day's articles that have an amount", async () => {
    renderPage(page.Page);
    await loaded();

    expect(screen.getByRole("heading", { level: 1, name: page.title })).toBeInTheDocument();
    expect(lastListRequest()).toEqual({
      year: 2026, delivery_week: 41, day_number: TUESDAY, is_past: false, model: page.model,
    });
    expect(selectedIn(DAY)).toBe(`${page.daySuffix} Tuesday, 06.10.2026`);
    // Potatoes are planned at zero for the day.
    expect(bodyRows().map((row) => cellsByHeader(row)[ARTICLE])).toEqual([
      "Carrots", "Lettuce", "Beetroot", "Radishes", page.ownArticle.name,
    ]);
    expect(screen.queryByText(page.otherArticle.name)).not.toBeInTheDocument();
    // The farm doesn't use sizes.
    expect(screen.queryByRole("columnheader", { name: SIZE })).not.toBeInTheDocument();
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText(page.explainer)).toBeInTheDocument();
    expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
  });

  it("shows each article's theoretical, in-stock, to-process, additional and total amounts", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage(page.Page);
    await loaded();

    const { theoreticalHeader, toProcessHeader, amountHeader } = page;
    const headers = [ARTICLE, UNIT, SIZE, theoreticalHeader, STILL_IN_STOCK, toProcessHeader, amountHeader, NOTE];
    for (const header of headers) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(screen.getByRole("columnheader", { name: startsWith(page.additionalHeader) })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: page.additionalTooltip })).toBeInTheDocument();
    expect(cellsByHeader(rowOf("Carrots"))).toMatchObject({
      [UNIT]: "commissioning.units.kg", [SIZE]: "commissioning.medium",
      [page.theoreticalHeader]: "40,00", [STILL_IN_STOCK]: "15,00", [page.toProcessHeader]: "25,00",
      [page.additionalHeader]: "5,00", [page.amountHeader]: "30,00 commissioning.units.kg",
      [NOTE]: "Scrub the soil off",
    });
    expect(cellsByHeader(rowOf("Lettuce"))).toMatchObject({
      [UNIT]: "commissioning.units.pcs", [SIZE]: "commissioning.large",
      [page.theoreticalHeader]: "60,0", [STILL_IN_STOCK]: "0,0", [page.toProcessHeader]: "60,0",
      [page.additionalHeader]: "", [page.amountHeader]: "60,0 commissioning.units.pcs",
    });
    // A negative stock counts as none, and a negative additional amount lowers the total.
    expect(cellsByHeader(rowOf("Beetroot"))).toMatchObject({
      [STILL_IN_STOCK]: "0,00", [page.toProcessHeader]: "20,00",
      [page.additionalHeader]: "-5,00", [page.amountHeader]: "15,00 commissioning.units.kg",
    });
    // The stock already covers the plan.
    expect(cellsByHeader(rowOf("Radishes"))).toMatchObject({
      [UNIT]: "commissioning.units.bunch", [STILL_IN_STOCK]: "30,0",
      [page.toProcessHeader]: "0,0", [page.amountHeader]: "",
    });
  });

  it.each([
    ["the default German format", {}, ["1.300,50", "0,25", "1.300,25", "0,15", "1.300,40", "0,40", "2,50"]],
    ["the tenant's English format", { number_locale: "en-US" }, ["1,300.50", "0.25", "1,300.25", "0.15", "1,300.40", "0.40", "2.50"]],
  ])("writes amounts at the unit's precision in %s, grouped and without float noise", async (_format, settings, shown) => {
    tenantSettings.values = settings;
    farm.entries.push(
      entry(page.model, PUMPKINS, { unit: "KG", theoretical: 1300.5, stock: 0.25, additional: 0.15 }),
      // 0.1 + 0.3 is 0.4000000000000001 in floating point.
      entry(page.model, KALE, { theoretical: 0.1, additional: 0.3 }),
      entry(page.model, APPLES, { theoretical: 2.5 }),
    );
    renderPage(page.Page);
    await loaded("Pumpkins");

    const [theoretical, inStock, toProcess, additional, total, kaleTotal, applesTotal] = shown;
    const kg = (amount: string) => `${amount} commissioning.units.kg`;
    expect(cellsByHeader(rowOf("Pumpkins"))).toMatchObject({
      [page.theoreticalHeader]: theoretical, [STILL_IN_STOCK]: inStock,
      [page.toProcessHeader]: toProcess, [page.additionalHeader]: additional,
      [page.amountHeader]: kg(total),
    });
    // A total under one unit is not rounded away, nor 2.5 up to 3.
    expect(cellsByHeader(rowOf("Kale"))[page.amountHeader]).toBe(kg(kaleTotal));
    expect(cellsByHeader(rowOf("Apples"))[page.amountHeader]).toBe(kg(applesTotal));
  });

  it("says there is nothing to do when the day needs nothing, and keeps the download off", async () => {
    const today = (item: Entry) => item.year === 2026 && item.week === 41 && item.day === TUESDAY;
    farm.entries = farm.entries.filter((item) => !today(item) || item.article === POTATOES);
    renderPage(page.Page);

    await waitFor(() => expect(api.summary).toHaveBeenCalled());
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(downloadButton(page)).toBeDisabled();
  });
});

describe("loading", () => {
  it("shows a spinner over the table while the list loads", async () => {
    const list = pending<Record<string, unknown>[]>();
    api.summary.mockImplementation(() => list.promise);
    renderPage(WashingList);

    await waitFor(() => expect(api.summary).toHaveBeenCalled());
    expect(tableIsBusy()).toBe(true);
    expect(bodyRows()).toHaveLength(0);

    list.answer(listed(lastListRequest()!));

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });

  it("shows no rows when the list cannot be loaded, and loads another day's", async () => {
    api.summary.mockImplementation(async (params: SummaryParams) => {
      if (params.day_number === TUESDAY) throw new Error("Network Error");
      return listed(params);
    });
    renderPage(WashingList);

    await waitFor(() => expect(api.summary).toHaveBeenCalled());
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);
    expect(downloadButton(WASHING)).toBeDisabled();

    await choose(DAY, `${WASHING.daySuffix} Wednesday, 07.10.2026`);

    expect(await within(tableBody()).findByText("Kohlrabi")).toBeInTheDocument();
    expect(downloadButton(WASHING)).toBeEnabled();
  });
});

// ── Week and day ────────────────────────────────────────────────────────────

describe.each(PAGES)("$name choosing the day", (page) => {
  it("offers every day of the week under the page's day label and lists the chosen day", async () => {
    renderPage(page.Page);
    await loaded();

    expect(await optionsOf(screen.getByRole("combobox", { name: DAY }))).toEqual(
      [
        "Monday, 05.10.2026", "Tuesday, 06.10.2026", "Wednesday, 07.10.2026",
        "Thursday, 08.10.2026", "Friday, 09.10.2026", "Saturday, 10.10.2026", "Sunday, 11.10.2026",
      ].map((day) => `${page.daySuffix} ${day}`),
    );
    await userEvent.click(optionIn(openDropdown(), `${page.daySuffix} Wednesday, 07.10.2026`));

    expect(await within(tableBody()).findByText("Kohlrabi")).toBeInTheDocument();
    expect(cellsByHeader(rowOf("Kohlrabi"))[page.amountHeader]).toBe("12,0 commissioning.units.pcs");
    expect(within(tableBody()).queryByText("Carrots")).not.toBeInTheDocument();
    expect(lastListRequest()).toEqual({
      year: 2026, delivery_week: 41, day_number: WEDNESDAY, is_past: false, model: page.model,
    });
  });
});

describe("choosing the week and the year", () => {
  it("loads the next week's list from the week arrow", async () => {
    renderPage(WashingList);
    await loaded();

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await within(tableBody()).findByText("Pumpkins")).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe(`${WASHING.daySuffix} Tuesday, 13.10.2026`);
    expect(lastListRequest()).toEqual({
      year: 2026, delivery_week: 42, day_number: TUESDAY, is_past: false, model: "washamount",
    });
  });

  it("loads the same week and day of another year", async () => {
    renderPage(WashingList);
    await loaded();

    await choose(YEAR, "2027");

    expect(await within(tableBody()).findByText("Potatoes")).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe(`${WASHING.daySuffix} Tuesday, 12.10.2027`);
    expect(lastListRequest()).toMatchObject({ year: 2027, delivery_week: 41, day_number: TUESDAY });
  });
});

// ── Team view ───────────────────────────────────────────────────────────────

describe.each(PAGES)("$name team view", (page) => {
  it("keeps only the article, the total and the note until the office view is back", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage(page.Page);
    await loaded();

    await userEvent.click(screen.getByRole("button", { name: containing(page.teamView) }));

    await waitFor(() =>
      expect(screen.queryByRole("columnheader", { name: page.toProcessHeader })).not.toBeInTheDocument(),
    );
    for (const header of [UNIT, SIZE, page.theoreticalHeader, STILL_IN_STOCK, startsWith(page.additionalHeader)]) {
      expect(screen.queryByRole("columnheader", { name: header })).not.toBeInTheDocument();
    }
    for (const header of [ARTICLE, page.amountHeader, NOTE]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(cellsByHeader(rowOf("Carrots"))).toMatchObject({
      [page.amountHeader]: "30,00 commissioning.units.kg", [NOTE]: "Scrub the soil off",
    });
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(downloadButton(page)).toBeEnabled();
    // The team reads the note but doesn't change it here.
    await userEvent.click(within(rowOf("Carrots")).getByText("Scrub the soil off"));
    expect(within(tableBody()).queryByRole("textbox")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: containing(OFFICE_VIEW) }));

    expect(await screen.findByRole("columnheader", { name: page.toProcessHeader })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: SIZE })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
  });
});

// ── Additional amounts ──────────────────────────────────────────────────────

describe.each(PAGES)("$name additional amounts", (page) => {
  it("corrects a listed article's additional amount and note and recomputes its total", async () => {
    renderPage(page.Page);
    await loaded();

    await userEvent.click(within(rowOf("Carrots")).getByText("5,00"));
    expect(additionalInput(page)).toHaveValue("5");
    // The article, its unit and its size stay as they are.
    expect(within(editingRow()).queryByRole("combobox")).not.toBeInTheDocument();
    await typeAdditional(page, "12");
    await userEvent.clear(noteInput());
    await userEvent.type(noteInput(), "Scrub twice");
    await save();

    await waitFor(() =>
      expect(cellsByHeader(rowOf("Carrots"))).toMatchObject({
        [page.additionalHeader]: "12,00", [page.amountHeader]: "37,00 commissioning.units.kg",
        [NOTE]: "Scrub twice",
      }),
    );
    expect(screen.queryByRole("button", { name: SAVE })).not.toBeInTheDocument();
    expect(api.update).toHaveBeenCalledTimes(1);
    const [id, body] = api.update.mock.lastCall as [string, SaveBody];
    expect(id).toBe(`${page.model}_art-carrots_KG_M_2026_41_1`);
    expect(Number(body.amount)).toBe(12);
    expect(body).toMatchObject({
      model: page.model, year: 2026, delivery_week: 41, day_number: TUESDAY,
      share_article: CARROTS.id, unit: "KG", size: "M", note: "Scrub twice",
    });
    expect(api.add).not.toHaveBeenCalled();
  });

  it("adds an additional amount for an article the day doesn't list yet", async () => {
    renderPage(page.Page);
    await loaded();

    await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
    await pickOption(within(editingRow()).getByRole("combobox", { name: ARTICLE }), "Kohlrabi");
    // The article brings its usual unit.
    expect(within(editingRow()).getByTitle("commissioning.units.pcs")).toBeInTheDocument();
    await typeAdditional(page, "6");
    await save();

    await waitFor(() =>
      expect(cellsByHeader(bodyRows()[0])).toMatchObject({
        [ARTICLE]: "Kohlrabi", [page.additionalHeader]: "6,0",
        [page.amountHeader]: "6,0 commissioning.units.pcs",
      }),
    );
    expect(bodyRows()).toHaveLength(6);
    expect(api.add).toHaveBeenCalledTimes(1);
    const body = api.add.mock.lastCall?.[0] as SaveBody;
    expect(Number(body.amount)).toBe(6);
    expect(body).toMatchObject({
      model: page.model, year: 2026, delivery_week: 41, day_number: TUESDAY,
      share_article: KOHLRABI.id, unit: "PCS", size: "M",
    });
  });
});

describe("entering additional amounts", () => {
  it("lowers what is left to wash with a negative whole number", async () => {
    renderPage(WashingList);
    await loaded();

    await userEvent.click(within(rowOf("Lettuce")).getByRole("button", { name: EDIT }));
    expect(additionalInput(WASHING)).not.toHaveValue();
    await userEvent.type(additionalInput(WASHING), "-2a,5");
    expect(additionalInput(WASHING)).toHaveValue("-25");
    await save();

    await waitFor(() =>
      expect(cellsByHeader(rowOf("Lettuce"))).toMatchObject({
        [WASHING.additionalHeader]: "-25,0", [WASHING.amountHeader]: "35,0 commissioning.units.pcs",
      }),
    );
  });

  it("starts a new row on + and offers the farm's active harvested articles in it", async () => {
    renderPage(WashingList);
    await loaded();

    await userEvent.keyboard("+");

    expect(bodyRows()).toHaveLength(6);
    const names = await optionsOf(within(editingRow()).getByRole("combobox", { name: ARTICLE }));
    // Not the bought-in apples, the inactive kale or the honey.
    expect([...names].sort()).toEqual([
      "Beetroot", "Carrots", "Celeriac", "Kohlrabi", "Leeks", "Lettuce", "Potatoes", "Pumpkins", "Radishes",
    ]);
  });

  it("refuses a second row for an article, unit and size already listed", async () => {
    renderPage(WashingList);
    await loaded();

    await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
    await pickOption(within(editingRow()).getByRole("combobox", { name: ARTICLE }), "Carrots");
    await typeAdditional(WASHING, "3");
    await save();

    const banner = "validation.unique.share_article_unit_size_must_be_unique — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    expect(api.add).not.toHaveBeenCalled();
    expect(editingRow()).toBeInTheDocument();
  });

  it("keeps the row open and shows why when the server refuses the amount", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const refusal = "The washing of this day is already documented.";
    api.update.mockRejectedValue(serverError(refusal));
    renderPage(WashingList);
    await loaded();

    await userEvent.click(within(rowOf("Carrots")).getByText("5,00"));
    await typeAdditional(WASHING, "9");
    await save();

    expect(await screen.findByText("table.save_failed_title")).toBeInTheDocument();
    expect(screen.getByText(`${refusal} — table.save_failed_hint`)).toBeInTheDocument();
    expect(additionalInput(WASHING)).toHaveValue("9");
  });
});

// ── Past weeks and roles ────────────────────────────────────────────────────

describe("past weeks", () => {
  it("shows a week more than a week back read-only", async () => {
    renderPage(WashingList);
    await loaded();

    await userEvent.click(arrow(WEEK, "common.previous"));
    await userEvent.click(arrow(WEEK, "common.previous"));

    await waitFor(() => expect(lastListRequest()).toMatchObject({ delivery_week: 39, is_past: true }));
    expect(await screen.findByText(PAST_WEEK)).toBeInTheDocument();
    await waitFor(() =>
      expect(cellsByHeader(rowOf("Carrots"))[WASHING.amountHeader]).toBe("35,00 commissioning.units.kg"),
    );
    await expectReadOnly("Carrots", "2,00");
  });

  it("still lets last week's amounts be corrected", async () => {
    renderPage(WashingList);
    await loaded();

    await userEvent.click(arrow(WEEK, "common.previous"));

    await waitFor(() =>
      expect(cellsByHeader(rowOf("Carrots"))[WASHING.amountHeader]).toBe("36,00 commissioning.units.kg"),
    );
    expect(lastListRequest()).toMatchObject({ delivery_week: 40, is_past: false });
    expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    await userEvent.click(within(rowOf("Carrots")).getByRole("button", { name: EDIT }));
    expect(additionalInput(WASHING)).toBeInTheDocument();
  });
});

describe.each(PAGES)("$name roles", (page) => {
  it.each(page.editors)("lets the %s role add and correct additional amounts", async (role) => {
    auth.roles = [role];
    renderPage(page.Page);
    await loaded();

    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    await userEvent.click(within(rowOf("Carrots")).getByText("5,00"));
    expect(additionalInput(page)).toHaveValue("5");
  });

  it.each(page.readers)("shows the list read-only to the %s role", async (role) => {
    auth.roles = [role];
    renderPage(page.Page);
    await loaded();

    await expectReadOnly("Carrots", "5,00");
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe.each(PAGES)("$name on a phone", (page) => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each article as a card with its total and note, without the office controls", async () => {
    renderPage(page.Page);
    await loaded();

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".mobile-card-item")).toHaveLength(5);
    expect(cardOf("Carrots")).toHaveTextContent("30,00 commissioning.units.kg");
    expect(cardOf("Carrots")).toHaveTextContent("Scrub the soil off");
    expect(cardOf("Beetroot")).toHaveTextContent("15,00 commissioning.units.kg");
    expect(cardOf(page.ownArticle.name)).toHaveTextContent(page.ownTotal);
    expect(screen.queryByText("Potatoes")).not.toBeInTheDocument();
    expect(selectedIn(DAY)).toBe("Tu, 06.10.");
    // No new row, no office or team view, no download and no explainer.
    for (const button of [ADD_CARD, containing(OFFICE_VIEW), containing(page.teamView), containing(page.download)]) {
      expect(screen.queryByRole("button", { name: button })).not.toBeInTheDocument();
    }
    expect(screen.queryByText(page.explainer)).not.toBeInTheDocument();
  });
});

describe("phone cards", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("names a size other than medium on the washing card and leaves out an empty total", async () => {
    renderPage(WashingList);
    await loaded();

    expect(within(cardOf("Lettuce")).getByText("commissioning.large")).toBeInTheDocument();
    expect(within(cardOf("Lettuce")).getByText("60,0 commissioning.units.pcs")).toBeInTheDocument();
    expect(within(cardOf("Carrots")).queryByText("commissioning.medium")).not.toBeInTheDocument();
    expect(cardOf("Radishes")).not.toHaveTextContent("commissioning.units");
  });

  it("labels the total and the note on the cleaning card", async () => {
    renderPage(CleaningList);
    await loaded();

    expect(cardOf("Carrots")).toHaveTextContent("commissioning.amount_cleaning_list: 30,00 commissioning.units.kg");
    expect(cardOf("Carrots")).toHaveTextContent("commissioning.note: Scrub the soil off");
    expect(cardOf("Radishes")).not.toHaveTextContent("commissioning.amount_cleaning_list");
  });

  it("shows a spinner instead of cards while the list loads", async () => {
    const list = pending<Record<string, unknown>[]>();
    api.summary.mockImplementation(() => list.promise);
    renderPage(WashingList);

    await waitFor(() => expect(isBusy()).toBe(true));
    expect(screen.queryByText("table.no_data")).not.toBeInTheDocument();

    list.answer(listed(lastListRequest()!));

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(isBusy()).toBe(false));
  });
});

// ── Download ────────────────────────────────────────────────────────────────

describe.each(PAGES)("$name worksheet download", (page) => {
  it("prints the day's articles with their totals and notes, named after the week and day", async () => {
    renderPage(page.Page);
    await loaded();

    await userEvent.click(downloadButton(page));

    await waitFor(() =>
      expect(printed.files).toEqual([`${page.title}_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf`]),
    );
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("ArticleAmountTickListPDF");
    expect(props).toMatchObject({
      year: 2026, week: 41, dayName: "COMMON.WEEKDAY_TUESDAY", pillKey: page.title,
    });
    const amountPrinted = props.amountAccessor as (row: Record<string, unknown>) => unknown;
    const lines = (props.data as Record<string, unknown>[]).map((row) => [
      row.computed_article_with_size, amountPrinted(row), row.note,
    ]);
    expect(lines).toEqual(
      expect.arrayContaining([
        ["Carrots", "30,00 commissioning.units.kg", "Scrub the soil off"],
        ["Lettuce (commissioning.large)", "60,0 commissioning.units.pcs", ""],
        ["Beetroot", "15,00 commissioning.units.kg", ""],
        [page.ownArticle.name, page.ownTotal, ""],
      ]),
    );
    expect(lines.map(([name]) => name)).not.toContain("Potatoes");
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe.each(PAGES)("$name render loop", (page) => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage(page.Page);
    await loaded();
    await flushMicrotasks();

    // A setState-in-render loop makes thousands of commits.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});
