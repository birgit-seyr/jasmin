/**
 * DocumentationPurchase: what the farm bought in during one week for one
 * storage — the purchases the planning expects next to what was actually
 * bought, with seller, price, note and organic status, edited inline. Rendered
 * through the real week and storage selectors, EditableTable, column hooks,
 * bulk action button and CSV export modal. The generated commissioning client
 * is the mocking boundary: its hooks are real TanStack queries around spies
 * that answer from an in-memory farm, and its mutations change that farm the
 * way the backend does, echoing the saved row in summary shape. The article
 * form behind "add article" is a stub, and a download is recorded, not saved.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The page's week state reads
 * "today" when the page mounts.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DocumentationSummaryRow,
  Reseller,
  ShareArticle,
  Storage,
} from "@shared/api/generated/models";
import germanErrors from "@shared/i18n/locales/de/errors.json";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// One ``t`` for every call, as the real hook keeps it stable across renders.
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

// The tenant record and settings, per test; an unset setting falls back to
// the caller's default.
const tenantState = vi.hoisted(() => ({
  record: { organic_control_number: "" } as Record<string, unknown>,
  settings: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    tenant: tenantState.record,
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.settings ? tenantState.settings[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const api = vi.hoisted(() => ({
  summary: vi.fn(), storages: vi.fn(), shareArticles: vi.fn(), sellers: vi.fn(),
  create: vi.fn(), update: vi.fn(), destroy: vi.fn(), setAsExpected: vi.fn(), exportCsv: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) =>
    [`/api/commissioning/${path}/`, ...(params ? [params] : [])];
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
    useCommissioningResellersList: queryHook("resellers", api.sellers),
    commissioningPurchaseCreate: (purchase: unknown) => api.create(purchase),
    commissioningPurchasePartialUpdate: (id: string, purchase: unknown) => api.update(id, purchase),
    commissioningPurchaseDestroy: (id: string) => api.destroy(id),
    commissioningPurchaseBulkSetAsExpectedCreate: (body: unknown) => api.setAsExpected(body),
    commissioningPurchaseExportCsvRetrieve: (params: unknown) => api.exportCsv(params),
  };
});

// What the page handed the article form behind "add article".
const articleForm = vi.hoisted(() => ({ defaultValues: undefined as unknown }));
// The page needs only these two; the barrel would also load every other modal
// of the app. The article form is a stub whose save stands for the article
// the office created in it.
vi.mock("@features/commissioning/modals", async () => ({
  ExportCsvPurchase: (await import("@features/commissioning/modals/csv/ExportCsvPurchase"))
    .default,
  ShareArticleModal: function ShareArticleModal(props: {
    isOpen: boolean; onSuccess?: (saved: object) => void; defaultValues?: object;
  }) {
    articleForm.defaultValues = props.defaultValues;
    if (!props.isOpen) return null;
    return (
      <div role="dialog" aria-label="Article form">
        <button type="button" onClick={() => props.onSuccess?.({ name: "Kale" })}>
          Save article
        </button>
      </div>
    );
  },
}));

const savedFiles = vi.hoisted(() => ({ names: [] as string[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (_blob: Blob, filename: string) => savedFiles.names.push(filename),
}));

import DocumentationPurchase from "../DocumentationPurchase";

// ── Fixtures ────────────────────────────────────────────────────────────────

/** A summary row: the API row plus its ``storage_<id>`` flags. */
type Row = DocumentationSummaryRow & Record<string, unknown>;
type Payload = Record<string, unknown>;

const COLD_STORE: Storage = { id: "storage-cold", name: "Cold store", is_active: true };
const PACKING_SHED: Storage = { id: "storage-shed", name: "Packing shed", is_active: true };

const article = (name: string, unit: ShareArticle["default_movement_unit"]): ShareArticle => ({
  id: `article-${name.toLowerCase()}`, name, default_movement_unit: unit,
  is_active: true, is_purchased: true,
});
const CARROTS = article("Carrots", "KG");
const APPLES = article("Apples", "KG");
const ONIONS = article("Onions", "KG");
const PUMPKINS = article("Pumpkins", "PCS");
const BEETROOT = article("Beetroot", "KG");
const LEEKS = { ...article("Leeks", "PCS"), default_pieces_per_pu_purchase: "12.000" };
const KALE = article("Kale", "BUNCH");

const seller = (id: string, companyName: string, controlNumber: string | null): Reseller => ({
  id, company_name: companyName, organic_control_number: controlNumber,
  is_seller: true, is_active_seller: true,
  address: "Field Lane 1", zip_code: "12345", city: "Greenville",
});
// Sunny Hill holds an organic certificate; Riverside doesn't.
const SUNNY_HILL = seller("seller-sunny-hill", "Sunny Hill Farm", "DE-ECO-006-12345");
const RIVERSIDE = seller("seller-riverside", "Riverside Growers", null);

const soldBy = (reseller: Reseller) => ({
  seller: reseller.id ?? null,
  seller_name: reseller.company_name ?? null,
});

/** A purchase as the week's summary lists it, stored in ``storage``. */
const purchaseRow = (product: ShareArticle, storage: Storage, fields: Partial<Row> = {}): Row => ({
  id: `purchase-${product.name.toLowerCase()}`, share_article: product.id ?? null,
  share_article_name: product.name, unit: product.default_movement_unit, size: "M", note: "",
  purchase_amount: null, theoretical_purchase_amount: 0, additional_theoretical_purchase_amount: 0,
  seller: null, seller_name: null, price_per_unit: null, organic_status: "conventional",
  // Summary fields this page doesn't show.
  theoretical_id: null, additional_id: null, amount_per_pu: null, theoretical_current_stock: null,
  forecast_plot_name: null, forecast_bed_number: null, forecast_note: null,
  harvesting_crate: null, harvesting_crate_name: null,
  ...Object.fromEntries(
    [COLD_STORE, PACKING_SHED].map((each) => [`storage_${each.id}`, each.id === storage.id]),
  ),
  ...fields,
});

// Bought, and expected by the planning: 10 planned plus 5 added by hand.
const CARROTS_BOUGHT = purchaseRow(CARROTS, COLD_STORE, {
  purchase_amount: "12.50", price_per_unit: "1.85", ...soldBy(SUNNY_HILL),
  theoretical_purchase_amount: 10, additional_theoretical_purchase_amount: 5,
  organic_status: "organic", note: "Washed before delivery",
});
// Bought without any expectation.
const APPLES_BOUGHT = purchaseRow(APPLES, COLD_STORE, {
  purchase_amount: "30.00", price_per_unit: "2.40", ...soldBy(RIVERSIDE),
});
// Expected by the planning, not bought yet: no seller, amount or price.
const ONIONS_EXPECTED = purchaseRow(ONIONS, COLD_STORE, { theoretical_purchase_amount: 20 });
// Only an amount added by hand is expected.
const PUMPKINS_EXPECTED = purchaseRow(PUMPKINS, COLD_STORE, {
  additional_theoretical_purchase_amount: 6,
});
// A leftover row with nothing expected and nothing bought.
const BEETROOT_EMPTY = purchaseRow(BEETROOT, COLD_STORE);
const LEEKS_IN_SHED = purchaseRow(LEEKS, PACKING_SHED, {
  purchase_amount: "40.00", price_per_unit: "0.90", ...soldBy(SUNNY_HILL),
});
const CARROTS_WEEK_39 = purchaseRow(CARROTS, COLD_STORE, {
  id: "purchase-carrots-week-39", purchase_amount: "8.00", price_per_unit: "1.70",
  ...soldBy(SUNNY_HILL),
});

/** What the in-memory farm holds; purchases by delivery week of 2026. */
let farm: {
  storages: Storage[]; articles: ShareArticle[]; sellers: Reseller[];
  purchases: Record<number, Row[]>;
};

const decimal = (value: unknown) =>
  value === null || value === undefined || value === "" ? null : Number(value).toFixed(2);

const httpError = (status: number, data: Record<string, unknown>) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

/** The backend's rule: an organic label needs a seller with a certificate. */
function refuseUncertifiedOrganic(purchase: Payload) {
  const labelled = ["organic", "in_conversion"].includes(purchase.organic_status as string);
  const supplier = farm.sellers.find((each) => each.id === purchase.seller);
  if (labelled && !supplier?.organic_control_number) {
    throw httpError(400, {
      code: "purchase.organic_certificate_required", field: "organic_status",
      message: "The seller has no organic certificate valid for this purchase's delivery week.",
    });
  }
}

/** The fields of a saved purchase as its echoed summary row carries them. */
function echoedFields(purchase: Payload): Partial<Row> {
  const supplier = farm.sellers.find((each) => each.id === purchase.seller);
  return {
    purchase_amount: decimal(purchase.amount),
    price_per_unit: decimal(purchase.price_per_unit),
    ...(supplier ? soldBy(supplier) : { seller: null, seller_name: null }),
    note: (purchase.note as string | undefined) ?? "",
    ...(purchase.organic_status ? { organic_status: purchase.organic_status as string } : {}),
  };
}

/** Replaces the rows of ``week`` that ``change`` returns a new row for. */
function changeRows(week: number, change: (row: Row) => Row | undefined) {
  farm.purchases[week] = farm.purchases[week].map((row) => change(row) ?? row);
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<DocumentationPurchase />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const SIZE = "commissioning.size";
const EXPECTED = "commissioning.expected_purchase";
const ACTUAL = "commissioning.actual_purchase";
const SELLER = "commissioning.seller";
const ORGANIC = "commissioning.organic_status";
const PRICE = "commissioning.price_per_unit";
const NOTE = "commissioning.note";
const STORAGE = "placeholder.storage_selector";
const TAKE_OVER = "commissioning.set_as_expected_purchase_for";
const ADD_ROW = /table\.add_plus_icon/;
const ADD_ARTICLE = /commissioning\.add_share_article/;
const EDIT_OR_DELETE = /table\.(edit|delete)/;

/** The summary request of a week of 2026 that isn't past. */
const weekRequest = (delivery_week: number) =>
  ({ year: 2026, delivery_week, is_past: false, model: "purchase" });

/** Waits until the week's purchases of the cold store are listed. */
const listed = () => screen.findByText("Carrots");

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

function rowAround(element: HTMLElement, what: string): HTMLElement {
  const row = element.closest("tr");
  if (!row) throw new Error(`No table row ${what}`);
  return row;
}
const rowOf = (text: string) => rowAround(screen.getByText(text), `shows ${text}`);
const editingRow = () =>
  rowAround(screen.getByRole("button", { name: "table.save" }), "is being edited");

const headerTexts = () => screen.getAllByRole("columnheader").map((header) => header.textContent);

/** The cell of ``row`` under the column titled ``title``. */
function cellOf(row: HTMLElement, title: string): HTMLElement {
  const index = headerTexts().indexOf(title);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No ${title} cell`);
  return cell;
}

/** A select or an input of the row being edited, by its column title. */
const field = (title: string) => within(editingRow()).getByRole("combobox", { name: title });
const input = (title: string) => within(editingRow()).getByLabelText(title);

function openPopup(selector: string): HTMLElement {
  const popups = Array.from(document.querySelectorAll<HTMLElement>(selector));
  const popup = popups.filter((each) => !/-hidden\b/.test(each.className)).pop();
  if (!popup) throw new Error(`Nothing open matches ${selector}`);
  return popup;
}

async function choose(select: HTMLElement, option: string) {
  await userEvent.click(select);
  await userEvent.click(within(openPopup(".ant-select-dropdown")).getByText(option));
}

async function optionsOf(select: HTMLElement): Promise<string[]> {
  await userEvent.click(select);
  const options = openPopup(".ant-select-dropdown").querySelectorAll(".ant-select-item-option-content");
  return Array.from(options).map((option) => option.textContent ?? "");
}

/** The label a select shows for its current value. */
const selectedIn = (select: HTMLElement) =>
  select.closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent ?? "";

async function typeInto(title: string, text: string) {
  await userEvent.clear(input(title));
  await userEvent.type(input(title), text);
}

/** Starts a new purchase, of ``product`` from ``supplier`` when given. */
async function startNewPurchase(product?: string, supplier?: string) {
  await userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
  if (product) await choose(field(ARTICLE), product);
  if (supplier) await choose(field(SELLER), supplier);
}

const save = () => userEvent.click(screen.getByRole("button", { name: "table.save" }));
const edit = (text: string) =>
  userEvent.click(within(rowOf(text)).getByRole("button", { name: "table.edit" }));
const tick = (text: string) => userEvent.click(within(rowOf(text)).getByRole("checkbox"));
const takeOverButton = () => screen.getByRole("button", { name: TAKE_OVER });
const editingDone = () =>
  waitFor(() => expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument());
const createdOnce = () => waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));

function weekArrow(direction: "common.previous" | "common.next") {
  const week = screen.getByRole("combobox", { name: "common.week" });
  const stepper = week.closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error("No week stepper");
  return within(stepper).getByRole("button", { name: direction });
}

const tableIsBusy = () =>
  document.querySelector('.ant-table-wrapper [aria-busy="true"]') !== null;

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

const lastSummaryRequest = () => api.summary.mock.lastCall?.[0];
const created = () => api.create.mock.lastCall?.[0] as Payload | undefined;
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantState.record.organic_control_number = "";
  tenantState.settings = {};
  auth.roles = ["office"];
  articleForm.defaultValues = undefined;
  savedFiles.names = [];
  farm = {
    storages: [COLD_STORE, PACKING_SHED],
    articles: [CARROTS, APPLES, ONIONS, PUMPKINS, BEETROOT, LEEKS],
    sellers: [SUNNY_HILL, RIVERSIDE],
    purchases: { 39: [CARROTS_WEEK_39], 41: [CARROTS_BOUGHT, APPLES_BOUGHT, ONIONS_EXPECTED] },
  };
  farm.purchases[41].push(PUMPKINS_EXPECTED, BEETROOT_EMPTY, LEEKS_IN_SHED);
  api.summary.mockReset().mockImplementation(async (params: Payload) =>
    params.year === 2026 ? [...(farm.purchases[params.delivery_week as number] ?? [])] : [],
  );
  api.storages.mockReset().mockImplementation(async () => [...farm.storages]);
  api.shareArticles.mockReset().mockImplementation(async () => [...farm.articles]);
  api.sellers.mockReset().mockImplementation(async () => [...farm.sellers]);
  let createdCount = 0;
  api.create.mockReset().mockImplementation(async (purchase: Payload) => {
    refuseUncertifiedOrganic(purchase);
    const product = farm.articles.find((each) => each.id === purchase.share_article);
    const storage = farm.storages.find((each) => each.id === purchase.storage);
    if (!product || !storage) throw httpError(400, { message: "Unknown article or storage" });
    createdCount += 1;
    const row = purchaseRow(product, storage, {
      id: `purchase-new-${createdCount}`, unit: purchase.unit as string, size: purchase.size as string,
      ...echoedFields(purchase),
    });
    const week = purchase.delivery_week as number;
    farm.purchases[week] = [...(farm.purchases[week] ?? []), row];
    return row;
  });
  api.update.mockReset().mockImplementation(async (id: string, purchase: Payload) => {
    refuseUncertifiedOrganic(purchase);
    const week = purchase.delivery_week as number;
    changeRows(week, (row) => (row.id === id ? { ...row, ...echoedFields(purchase) } : undefined));
    return farm.purchases[week].find((row) => row.id === id);
  });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    farm.purchases[41] = farm.purchases[41].filter((row) => row.id !== id);
  });
  // The expected amount becomes the bought one, matched by article, unit,
  // size and storage.
  api.setAsExpected.mockReset().mockImplementation(async (body: { selectedData: Payload[] }) => {
    for (const item of body.selectedData) {
      const amount = decimal(item.theoretical_purchase_amount);
      changeRows(item.delivery_week as number, (row) =>
        row.share_article === item.id && row[`storage_${item.storage}`] &&
        row.unit === item.theoretical_purchase_unit && row.size === item.theoretical_purchase_size
          ? { ...row, purchase_amount: amount }
          : undefined,
      );
    }
  });
  api.exportCsv.mockReset().mockResolvedValue("article;amount\nCarrots;12,50\n");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DocumentationPurchase loading and listing", () => {
  it("opens on this week and the first storage, offering only active storages, purchased articles and sellers", async () => {
    renderPage();
    await listed();
    const title = screen.getByRole("heading", { name: "commissioning.documentation_purchase" });
    expect(title).toBeInTheDocument();
    expect(selectedIn(screen.getByRole("combobox", { name: STORAGE }))).toBe("Cold store");
    expect(selectedIn(screen.getByRole("combobox", { name: "common.year" }))).toBe("2026");
    expect(api.summary).toHaveBeenCalledWith(weekRequest(41));
    expect(api.storages).toHaveBeenCalledWith({ is_active: true });
    expect(api.shareArticles).toHaveBeenCalledWith({ is_active: true, is_purchased: true });
    expect(api.sellers).toHaveBeenCalledWith({ is_active_seller: true, is_seller: true });
    expect(screen.getByText("explainers.purchase")).toBeInTheDocument();
  });

  it("asks for no purchases and offers no take-over until it knows the storages", async () => {
    const storages = pending<Storage[]>();
    api.storages.mockImplementation(() => storages.promise);
    renderPage();
    await waitFor(() => expect(api.storages).toHaveBeenCalled());
    expect(api.summary).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: TAKE_OVER })).not.toBeInTheDocument();
    storages.answer([COLD_STORE, PACKING_SHED]);
    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(takeOverButton()).toBeInTheDocument();
  });

  it("shows a spinner over the table while the week's purchases load", async () => {
    const purchases = pending<Row[]>();
    api.summary.mockImplementation(() => purchases.promise);
    renderPage();
    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);
    purchases.answer([CARROTS_BOUGHT]);
    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });

  it("lists the storage's rows that carry an expected or an actual purchase, and no others", async () => {
    renderPage();
    await listed();
    expect(headerTexts()).toEqual(
      expect.arrayContaining([ARTICLE, UNIT, EXPECTED, ACTUAL, SELLER, PRICE, NOTE]),
    );
    expect(headerTexts()).not.toContain(SIZE);
    const articles = bodyRows().map((row) => cellOf(row, ARTICLE).textContent);
    expect(articles).toEqual(["Carrots", "Apples", "Onions", "Pumpkins"]);
    expect(screen.queryByText("Beetroot")).not.toBeInTheDocument();
    expect(screen.queryByText("Leeks")).not.toBeInTheDocument();
  });

  it("shows each purchase's unit, expected and actual amount, seller, price and note", async () => {
    renderPage();
    await listed();

    const carrots = rowOf("Carrots");
    expect(cellOf(carrots, UNIT)).toHaveTextContent("commissioning.units.kg");
    expect(cellOf(carrots, EXPECTED)).toHaveTextContent("15,00");
    expect(cellOf(carrots, ACTUAL)).toHaveTextContent("12,50");
    expect(cellOf(carrots, SELLER)).toHaveTextContent("Sunny Hill Farm");
    expect(cellOf(carrots, PRICE)).toHaveTextContent("1,85 €/commissioning.units.kg");
    expect(cellOf(carrots, NOTE)).toHaveTextContent("Washed before delivery");
    const apples = rowOf("Apples");
    expect(cellOf(apples, EXPECTED).textContent).toBe("");
    expect(cellOf(apples, ACTUAL)).toHaveTextContent("30,00");
    expect(cellOf(apples, SELLER)).toHaveTextContent("Riverside Growers");
  });

  it("shows an expected purchase that has no seller, amount or price yet with those cells empty", async () => {
    renderPage();
    await listed();
    const onions = rowOf("Onions");
    expect(cellOf(onions, EXPECTED)).toHaveTextContent("20,00");
    for (const title of [ACTUAL, SELLER, PRICE]) {
      expect(cellOf(onions, title).textContent).toBe("");
    }
    expect(cellOf(rowOf("Pumpkins"), EXPECTED).textContent).toBe("6,0");
  });

  it("shows amounts at their unit's precision, and prices, in the tenant's number format and currency", async () => {
    tenantState.settings = { currency: "USD", number_locale: "en-US" };
    farm.purchases[41] = [{
      ...CARROTS_BOUGHT, purchase_amount: "1250.00",
      theoretical_purchase_amount: 1000, additional_theoretical_purchase_amount: 250.5,
    }, purchaseRow(KALE, COLD_STORE, { purchase_amount: "1250.00" })];
    renderPage();
    await listed();

    const carrots = rowOf("Carrots");
    expect(cellOf(carrots, EXPECTED)).toHaveTextContent("1,250.50");
    expect(cellOf(carrots, ACTUAL)).toHaveTextContent("1,250.00");
    expect(cellOf(carrots, PRICE)).toHaveTextContent("$1.85/commissioning.units.kg");
    expect(cellOf(rowOf("Kale"), ACTUAL).textContent).toBe("1,250.0");
  });

  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await listed();
    await flushMicrotasks();
    // About 15 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});

describe("DocumentationPurchase choosing the week and storage", () => {
  it("shows another storage's purchases when the storage changes", async () => {
    renderPage();
    await listed();
    await choose(screen.getByRole("combobox", { name: STORAGE }), "Packing shed");
    expect(await screen.findByText("Leeks")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(cellOf(rowOf("Leeks"), ACTUAL).textContent).toBe("40,0");
    expect(cellOf(rowOf("Leeks"), PRICE)).toHaveTextContent("0,90 €/commissioning.units.pcs");
  });

  it("loads the next week from the week arrow and says when nothing was bought", async () => {
    renderPage();
    await listed();
    await userEvent.click(weekArrow("common.next"));
    await waitFor(() => expect(lastSummaryRequest()).toEqual(weekRequest(42)));
    await waitFor(() => expect(bodyRows()).toHaveLength(0));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
  });

  it("shows a week more than a week back read-only", async () => {
    renderPage();
    await listed();

    await userEvent.click(weekArrow("common.previous"));
    await waitFor(() => expect(lastSummaryRequest()).toEqual(weekRequest(40)));
    expect(screen.queryByText("table.past_week_readonly")).not.toBeInTheDocument();
    await userEvent.click(weekArrow("common.previous"));

    expect(await screen.findByText("8,00")).toBeInTheDocument();
    expect(lastSummaryRequest()).toEqual({ ...weekRequest(39), is_past: true });
    expect(screen.getByText("table.past_week_readonly")).toBeInTheDocument();
    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: TAKE_OVER })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EDIT_OR_DELETE })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ARTICLE })).toBeDisabled();

    await userEvent.click(screen.getByText("8,00"));

    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });

  it("shows no rows for a week that fails to load, and lists purchases again once a week loads", async () => {
    renderPage();
    await listed();
    api.summary.mockRejectedValueOnce(new Error("Network Error"));
    await userEvent.click(weekArrow("common.next"));
    await waitFor(() => expect(lastSummaryRequest()).toEqual(weekRequest(42)));
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);
    await userEvent.click(weekArrow("common.previous"));
    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(lastSummaryRequest()).toEqual(weekRequest(41));
  });
});

describe("DocumentationPurchase recording a purchase", () => {
  it("records a purchase for the storage and week, sending the amount and price as decimal strings", async () => {
    renderPage();
    await listed();

    await startNewPurchase("Leeks");
    expect(selectedIn(field(UNIT))).toBe("commissioning.units.pcs");
    await typeInto(ACTUAL, "25,5");
    await choose(field(SELLER), "Sunny Hill Farm");
    await typeInto(PRICE, "0,95");
    expect(within(cellOf(editingRow(), PRICE)).getByText("€")).toBeInTheDocument();
    expect(input(PRICE)).toHaveValue("0,95");
    await typeInto(NOTE, "For the market boxes");
    await save();

    await createdOnce();
    expect(created()).toEqual(
      expect.objectContaining({
        share_article: LEEKS.id, unit: "PCS", size: "M", amount_per_pu: "12.000",
        amount: "25.5", price_per_unit: "0.95", seller: SUNNY_HILL.id,
        note: "For the market boxes", storage: COLD_STORE.id, year: 2026, delivery_week: 41,
      }),
    );
    await editingDone();
    const leeks = rowOf("Leeks");
    expect(cellOf(leeks, ACTUAL).textContent).toBe("25,5");
    expect(cellOf(leeks, SELLER)).toHaveTextContent("Sunny Hill Farm");
    expect(cellOf(leeks, PRICE)).toHaveTextContent("0,95 €/commissioning.units.pcs");
    expect(cellOf(leeks, NOTE)).toHaveTextContent("For the market boxes");
  });

  it("asks for the article, unit and seller before it saves a new purchase", async () => {
    silenceConsoleErrors();
    renderPage();
    await listed();
    await startNewPurchase();
    await save();
    const banner = "table.save_failed_generic — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    for (const title of [ARTICLE, UNIT, SELLER]) {
      expect(within(cellOf(editingRow(), title)).getByText("table.required")).toBeInTheDocument();
    }
    expect(within(cellOf(editingRow(), ACTUAL)).queryByText("table.required")).toBeNull();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("records a purchase without an amount as zero", async () => {
    renderPage();
    await listed();
    await startNewPurchase("Leeks", "Sunny Hill Farm");
    await save();
    await createdOnce();
    expect(created()).toMatchObject({ share_article: LEEKS.id, amount: 0 });
  });

  it("refuses a repeat of a purchase: same article, unit, size and seller", async () => {
    renderPage();
    await listed();
    await startNewPurchase("Apples", "Riverside Growers");
    await typeInto(ACTUAL, "5");
    await save();
    const banner = "validation.unique.documentation_purchase — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    expect(editingRow()).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("records the same article in another unit as a purchase of its own", async () => {
    renderPage();
    await listed();
    await startNewPurchase("Apples", "Riverside Growers");
    await choose(field(UNIT), "commissioning.units.pcs");
    await typeInto(ACTUAL, "40");
    await save();
    await createdOnce();
    expect(created()).toMatchObject({ share_article: APPLES.id, unit: "PCS", size: "M", amount: "40" });
  });

  it("starts a new purchase at medium size and keeps other sizes apart when the farm shows sizes", async () => {
    tenantState.settings = { show_size_column: true };
    renderPage();
    await listed();
    expect(cellOf(rowOf("Apples"), SIZE)).toHaveTextContent("commissioning.medium");
    await startNewPurchase("Apples", "Riverside Growers");
    expect(selectedIn(field(SIZE))).toBe("commissioning.medium");
    await choose(field(SIZE), "commissioning.large");
    await save();
    await createdOnce();
    expect(created()).toMatchObject({ share_article: APPLES.id, unit: "KG", size: "L" });
  });

  it("starts a new purchase from the + key", async () => {
    renderPage();
    await listed();
    await userEvent.keyboard("+");
    expect(field(ARTICLE)).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(5);
  });

  it("opens the article form for a purchased article and offers the saved article for a purchase", async () => {
    renderPage();
    await listed();
    const articleRequests = api.shareArticles.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: ADD_ARTICLE }));
    expect(screen.getByRole("dialog", { name: "Article form" })).toBeInTheDocument();
    expect(articleForm.defaultValues).toEqual({ is_purchased: true });
    farm.articles = [...farm.articles, KALE];
    await userEvent.click(screen.getByRole("button", { name: "Save article" }));

    expect(screen.queryByRole("dialog", { name: "Article form" })).not.toBeInTheDocument();
    await waitFor(() => expect(api.shareArticles.mock.calls.length).toBeGreaterThan(articleRequests));
    expect(api.shareArticles).toHaveBeenLastCalledWith({ is_active: true, is_purchased: true });
    await startNewPurchase();
    await waitFor(async () => expect(await optionsOf(field(ARTICLE))).toContain("Kale"));
  });
});

describe("DocumentationPurchase correcting a purchase", () => {
  it("keeps the article, unit and size and starts from the recorded amount and price", async () => {
    renderPage();
    await listed();

    await edit("Apples");

    expect(within(editingRow()).queryByRole("combobox", { name: ARTICLE })).toBeNull();
    expect(within(editingRow()).queryByRole("combobox", { name: UNIT })).toBeNull();
    expect(input(ACTUAL)).toHaveValue("30,00");
    expect(input(PRICE)).toHaveValue("2,40");
    expect(selectedIn(field(SELLER))).toBe("Riverside Growers");
    await typeInto(ACTUAL, "32,5");
    await typeInto(PRICE, "2,45");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      APPLES_BOUGHT.id,
      expect.objectContaining({
        share_article: APPLES.id, unit: "KG", size: "M", seller: RIVERSIDE.id,
        amount: "32.5", price_per_unit: "2.45",
        storage: COLD_STORE.id, year: 2026, delivery_week: 41,
      }),
    );
    await waitFor(() => expect(cellOf(rowOf("Apples"), ACTUAL)).toHaveTextContent("32,50"));
    expect(cellOf(rowOf("Apples"), PRICE)).toHaveTextContent("2,45 €/commissioning.units.kg");
  });

  it("records what was bought for an expected purchase once a seller is chosen", async () => {
    silenceConsoleErrors();
    renderPage();
    await listed();

    await edit("Onions");
    expect(input(ACTUAL)).toHaveValue("");
    await typeInto(ACTUAL, "20");
    await save();

    const sellerCell = cellOf(editingRow(), SELLER);
    expect(await within(sellerCell).findByText("table.required")).toBeInTheDocument();
    expect(api.update).not.toHaveBeenCalled();

    await choose(field(SELLER), "Sunny Hill Farm");
    await save();

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith(
        ONIONS_EXPECTED.id,
        expect.objectContaining({ share_article: ONIONS.id, amount: "20", seller: SUNNY_HILL.id }),
      ),
    );
    await waitFor(() => expect(cellOf(rowOf("Onions"), ACTUAL)).toHaveTextContent("20,00"));
    expect(cellOf(rowOf("Onions"), SELLER)).toHaveTextContent("Sunny Hill Farm");
  });
});

describe("DocumentationPurchase deleting a purchase", () => {
  const deleteApples = async () => {
    await userEvent.click(within(rowOf("Apples")).getByRole("button", { name: "table.delete" }));
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));
  };

  it("deletes a purchase nobody expected after confirmation and reloads the week", async () => {
    renderPage();
    await listed();
    await deleteApples();
    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith(APPLES_BOUGHT.id));
    await waitFor(() => expect(api.summary).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Apples")).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);
  });

  it("offers no delete for a row that carries an expected purchase", async () => {
    renderPage();
    await listed();
    for (const name of ["Carrots", "Onions", "Pumpkins"]) {
      const row = rowOf(name);
      expect(within(row).getByRole("button", { name: "table.edit" })).toBeEnabled();
      expect(within(row).queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    }
  });

  it("keeps the purchase and says why when the backend refuses the delete", async () => {
    silenceConsoleErrors();
    const message = "The purchase is in a stock count.";
    api.destroy.mockRejectedValue(httpError(400, { code: "validation_error", message }));
    renderPage();
    await listed();
    await deleteApples();
    expect(await screen.findByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(rowOf("Apples")).toBeInTheDocument();
  });
});

describe("DocumentationPurchase organic status", () => {
  const certifyFarm = () => {
    tenantState.record.organic_control_number = "DE-ECO-006";
  };

  it("leaves the organic status out when the farm holds no organic certificate", async () => {
    renderPage();
    await listed();
    expect(headerTexts()).not.toContain(ORGANIC);
    await startNewPurchase("Leeks", "Riverside Growers");
    await save();
    await createdOnce();
    expect(created()).not.toHaveProperty("organic_status");
  });

  it("shows each purchase's organic status and starts a new purchase as organic on a certified farm", async () => {
    certifyFarm();
    renderPage();
    await listed();
    expect(cellOf(rowOf("Carrots"), ORGANIC)).toHaveTextContent("commissioning.organic.organic");
    expect(cellOf(rowOf("Apples"), ORGANIC)).toHaveTextContent("commissioning.organic.conventional");
    await startNewPurchase();
    expect(selectedIn(field(ORGANIC))).toBe("commissioning.organic.organic");
    await choose(field(ARTICLE), "Leeks");
    await choose(field(SELLER), "Sunny Hill Farm");
    await save();
    await createdOnce();
    expect(created()).toMatchObject({ organic_status: "organic", seller: SUNNY_HILL.id });
  });

  it("shows why an organic purchase from a seller without a certificate is refused, and saves it as conventional", async () => {
    silenceConsoleErrors();
    certifyFarm();
    renderPage();
    await listed();
    await startNewPurchase("Leeks", "Riverside Growers");
    await typeInto(ACTUAL, "12");

    await save();

    const refusal = germanErrors.purchase.organic_certificate_required;
    expect(await screen.findByText(`${refusal} — table.save_failed_hint`)).toBeInTheDocument();
    expect(selectedIn(field(ORGANIC))).toBe("commissioning.organic.organic");

    await choose(field(ORGANIC), "commissioning.organic.conventional");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(2));
    expect(created()).toMatchObject({ organic_status: "conventional", seller: RIVERSIDE.id });
    await editingDone();
    expect(cellOf(rowOf("Leeks"), ORGANIC)).toHaveTextContent("commissioning.organic.conventional");
  });
});

describe("DocumentationPurchase taking over expected purchases", () => {
  it("records the expected amount as bought for the selected rows", async () => {
    renderPage();
    await listed();
    expect(screen.getByText("commissioning.for_selected")).toBeInTheDocument();
    expect(takeOverButton()).toBeDisabled();

    await tick("Onions");
    await userEvent.click(takeOverButton());

    await waitFor(() => expect(api.setAsExpected).toHaveBeenCalledTimes(1));
    expect(api.setAsExpected).toHaveBeenCalledWith({
      selectedData: [{
        id: ONIONS.id, theoretical_purchase_amount: "20", theoretical_purchase_unit: "KG",
        theoretical_purchase_size: "M", year: 2026, delivery_week: 41, storage: COLD_STORE.id,
      }],
    });
    await waitFor(() => expect(cellOf(rowOf("Onions"), ACTUAL)).toHaveTextContent("20,00"));
    expect(takeOverButton()).toBeDisabled();
  });

  it.each([
    ["is bought already", "Carrots"],
    ["was never expected", "Apples"],
  ])("keeps the take-over disabled while a selected row %s", async (_why, name) => {
    renderPage();
    await listed();
    await tick("Onions");
    expect(takeOverButton()).toBeEnabled();
    await tick(name);
    expect(takeOverButton()).toBeDisabled();
  });

  it("tells the office why taking over the expected purchases failed", async () => {
    silenceConsoleErrors();
    const message = "The storage takes no purchases.";
    api.setAsExpected.mockRejectedValue(httpError(400, { code: "validation_error", message }));
    renderPage();
    await listed();
    await tick("Onions");
    await userEvent.click(takeOverButton());
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(cellOf(rowOf("Onions"), ACTUAL).textContent).toBe("");
  });
});

describe("DocumentationPurchase CSV export", () => {
  async function openExport() {
    await userEvent.click(screen.getByRole("button", { name: "commissioning.csv_export_purchase" }));
    return screen.findByRole("dialog");
  }

  async function pickPreset(dialog: HTMLElement, preset: string) {
    await userEvent.click(within(dialog).getAllByRole("textbox")[0]);
    await userEvent.click(within(openPopup(".ant-picker-dropdown")).getByText(preset));
  }

  const downloadIn = (dialog: HTMLElement) =>
    within(dialog).getByRole("button", { name: /common\.download/ });

  it("exports last month's purchases summed by article, once a range is picked", async () => {
    renderPage();
    await listed();
    const dialog = await openExport();
    expect(downloadIn(dialog)).toBeDisabled();

    await pickPreset(dialog, "common.last_month");
    const [from, to] = within(dialog).getAllByRole("textbox");
    expect(from).toHaveValue("01.09.2026");
    expect(to).toHaveValue("30.09.2026");
    const summed = within(dialog).getByRole("checkbox", { name: "commissioning.sum_by_share_article" });
    await userEvent.click(summed);
    await userEvent.click(downloadIn(dialog));

    await waitFor(() => expect(savedFiles.names).toHaveLength(1));
    const range = { date_from: "2026-09-01", date_to: "2026-09-30" };
    expect(api.exportCsv).toHaveBeenCalledWith({ ...range, summed: true });
    // The prefix and the summed suffix are the shipped German file words.
    expect(savedFiles.names[0]).toMatch(/^[a-z]+_2026-09-01_2026-09-30_[a-z]+\.csv$/);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("exports this month's purchases line by line", async () => {
    renderPage();
    await listed();
    const dialog = await openExport();
    await pickPreset(dialog, "common.this_month");
    await userEvent.click(downloadIn(dialog));
    await waitFor(() => expect(savedFiles.names).toHaveLength(1));
    const range = { date_from: "2026-10-01", date_to: "2026-10-31" };
    expect(api.exportCsv).toHaveBeenCalledWith({ ...range, summed: false });
    expect(savedFiles.names[0]).toMatch(/^[a-z]+_2026-10-01_2026-10-31\.csv$/);
  });
});

describe("DocumentationPurchase roles", () => {
  it("shows the purchases read-only to a user without a staff role", async () => {
    auth.roles = ["member"];
    renderPage();
    await listed();
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EDIT_OR_DELETE })).not.toBeInTheDocument();
    await userEvent.click(within(rowOf("Apples")).getByText("30,00"));
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(within(rowOf("Apples")).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("lets a gardener record and correct purchases", async () => {
    auth.roles = ["gardener"];
    renderPage();
    await listed();
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    await userEvent.click(within(rowOf("Apples")).getByText("30,00"));
    expect(input(ACTUAL)).toHaveValue("30,00");
  });
});
