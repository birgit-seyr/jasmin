/**
 * ExportCsvAllArticles: the one-stop CSV of every share article (extras
 * included) and every crate, each with the price it has on a date the office
 * picks. Rendered the way the share article list hosts it: mounted closed,
 * opened from a button and closed again when it reports a close. The real
 * export, its date shell, the price-column, tier, currency, date-format and
 * CSV helpers run; the generated commissioning client is the mocking boundary,
 * its list hooks real TanStack queries around spies that answer from an
 * in-memory farm, and the browser download is recorded instead of saved.
 *
 * The farm's crate prices come as the backend lists them, newest first, every
 * price a crate ever had; the export keeps the one that is valid on the date.
 *
 * The clock is frozen on Monday 5 October 2026, the date the export starts on.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CrateNetPrice, ShareArticle } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders, type ProfileRendersHandle } from "@/test/profileRenders";

// One `t` for every render, as react-i18next keeps it. It shows the values a
// label is interpolated with after its key (`key name=value …`), so the
// currency symbol and tier numbers in the CSV's headers can be read; the
// language decides the words for yes and no.
const i18nMock = vi.hoisted(() => {
  const state = { language: "de" };
  const t = (key: string, options?: unknown) => {
    if (typeof options === "string") return options;
    if (options && typeof options === "object") {
      const values = Object.entries(options as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, value]) => `${name}=${String(value)}`);
      if (values.length > 0) return `${key} ${values.join(" ")}`;
    }
    return key;
  };
  return { state, t };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: i18nMock.state.language, changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Per-test tenant settings; anything unset falls back to the caller's default.
const tenantState = vi.hoisted(() => ({ settings: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.settings ? tenantState.settings[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

const api = vi.hoisted(() => ({
  listArticles: vi.fn<(params?: unknown) => Promise<ShareArticle[]>>(),
  listCratePrices: vi.fn<(params?: unknown) => Promise<CrateNetPrice[]>>(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  type Options = { query?: { enabled?: boolean } };
  return {
    useCommissioningShareArticlesList: (params: unknown, options?: Options) =>
      useQuery({
        queryKey: ["/api/commissioning/share_articles/", params],
        queryFn: () => api.listArticles(params),
        enabled: options?.query?.enabled,
      }),
    useCommissioningCrateNetPricesList: (params: unknown, options?: Options) =>
      useQuery({
        queryKey: ["/api/commissioning/crate_net_prices/", params],
        queryFn: () => api.listCratePrices(params),
        enabled: options?.query?.enabled,
      }),
  };
});

// The files the browser was handed to save.
const downloads = vi.hoisted(() => ({ files: [] as { name: string; blob: Blob }[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (blob: Blob, filename: string) => {
    downloads.files.push({ name: filename, blob });
  },
}));

import ExportCsvAllArticles from "../ExportCsvAllArticles";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);

const NO_PRICES = {
  tax_rate: null,
  net_price_for_boxes_kg: null, net_price_for_boxes_pieces: null, net_price_for_boxes_bunch: null,
  net_price_for_orders_kg_1: null, net_price_for_orders_kg_2: null, net_price_for_orders_kg_3: null,
  net_price_for_orders_pieces_1: null, net_price_for_orders_pieces_2: null, net_price_for_orders_pieces_3: null,
  net_price_for_orders_bunch_1: null, net_price_for_orders_bunch_2: null, net_price_for_orders_bunch_3: null,
};

/** An article as the data list carries it with the prices valid on the date asked for. */
function article(fields: Partial<ShareArticle> & Pick<ShareArticle, "id" | "name" | "default_movement_unit">) {
  return {
    is_active: true, is_extra: false, is_purchased: false, is_sold_to_resellers: false,
    share_option: null, share_option2: null, share_option3: null, can_be_deleted: true,
    ...NO_PRICES,
    ...fields,
  } as ShareArticle;
}

// In the harvest share and sold to resellers, with a box price and three
// reseller tiers per kg. The backend sends money as decimal strings.
const CARROTS = article({
  id: "article-carrots", name: "Carrots", default_movement_unit: "KG",
  is_sold_to_resellers: true, share_option: "HARVEST_SHARE",
  tax_rate: "10.00", net_price_for_boxes_kg: "2.50",
  net_price_for_orders_kg_1: "2.20", net_price_for_orders_kg_2: "2.00", net_price_for_orders_kg_3: "1.80",
});
// Bought in, in two shares; its name holds the English CSV's delimiter.
const LEMONS = article({
  id: "article-lemons", name: "Lemons, organic", default_movement_unit: "PCS",
  is_purchased: true, share_option: "HARVEST_SHARE", share_option2: "HARVEST_SHARE_FRUIT",
  tax_rate: "10.00", net_price_for_boxes_pieces: "0.45", net_price_for_orders_pieces_1: "0.40",
});
// No longer grown, and without a price on the date.
const RADISHES = article({
  id: "article-radishes", name: "Radishes", default_movement_unit: "BUNCH", is_active: false,
});
// An extra, a farm tour, with a price per piece.
const FARM_TOUR = article({
  id: "article-tour", name: "Farm tour", default_movement_unit: "PCS", is_extra: true,
  tax_rate: "20.00", net_price_for_boxes_pieces: "15.00",
});

function cratePrice(
  id: string,
  crate: { id: string; name: string },
  validFrom: string,
  validUntil: string | null,
  price: string,
): CrateNetPrice {
  return {
    id, crate: crate.id, name: crate.name, short_name: crate.name.slice(0, 3),
    valid_from: validFrom, valid_until: validUntil, price, tax_rate: "20.00", can_be_deleted: true,
  };
}

const EURO_CRATE = { id: "crate-e2", name: "Euro crate E2" };
const HARVEST_BIN = { id: "crate-bin", name: "Harvest bin" };
const BANANA_BOX = { id: "crate-banana", name: "Banana box" };

// Every crate price, newest first as the backend lists them.
const CRATE_PRICES: CrateNetPrice[] = [
  // The Euro crate gets dearer from November.
  cratePrice("price-e2-nov", EURO_CRATE, "2026-11-02", null, "1.50"),
  // The harvest bin is priced only from next week.
  cratePrice("price-bin", HARVEST_BIN, "2026-10-12", null, "3.00"),
  cratePrice("price-e2-2026", EURO_CRATE, "2026-01-05", "2026-11-01", "1.20"),
  cratePrice("price-banana", BANANA_BOX, "2025-06-02", null, "0.80"),
  cratePrice("price-e2-2025", EURO_CRATE, "2025-01-06", "2026-01-04", "1.00"),
];

// The articles the backend answers with for the date asked for.
let articlesOn: (date: string) => ShareArticle[] = () => [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  i18nMock.state.language = "de";
  tenantState.settings = {};
  downloads.files = [];
  // Carrots get a new reseller price from November.
  articlesOn = (date) =>
    date >= "2026-11-02"
      ? [{ ...CARROTS, net_price_for_orders_kg_1: "2.40" }, LEMONS, RADISHES, FARM_TOUR]
      : [CARROTS, LEMONS, RADISHES, FARM_TOUR];
  api.listArticles.mockReset().mockImplementation(async (params) => {
    const { price_date: date } = params as { price_date: string };
    return articlesOn(date);
  });
  api.listCratePrices.mockReset().mockImplementation(async () => [...CRATE_PRICES]);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Helpers ─────────────────────────────────────────────────────────────────

const OPEN_EXPORT = "Export everything";

/** The share article list, as far as this export goes: a button opens it. */
function ArticleListPage({ onClose, profiler }: { onClose: () => void; profiler: ProfileRendersHandle }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        {OPEN_EXPORT}
      </button>
      {profiler.wrap(
        <ExportCsvAllArticles
          open={open}
          onClose={() => {
            onClose();
            setOpen(false);
          }}
        />,
      )}
    </>
  );
}

let queryClient: QueryClient;

function renderPage() {
  const user = userEvent.setup();
  const onClose = vi.fn();
  const profiler = profileRenders();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ArticleListPage onClose={onClose} profiler={profiler} />
    </QueryClientProvider>,
  );
  return { user, onClose, profiler };
}

type User = ReturnType<typeof userEvent.setup>;

const dialog = () => screen.getByRole("dialog");
const queryDialog = () => screen.queryByRole("dialog");
const dateInput = () => within(dialog()).getByRole("textbox");
// Each of these buttons carries an icon whose label joins the button's name.
const loadButton = () => within(dialog()).getByRole("button", { name: /common\.load/ });
const downloadButton = () => within(dialog()).getByRole("button", { name: /common\.download/ });
const spinner = () => dialog().querySelector(".ant-spin");

async function openExport(user: User) {
  await user.click(screen.getByRole("button", { name: OPEN_EXPORT }));
  return screen.findByRole("dialog");
}

/** Loads the rows for the date in the picker and waits until they are in. */
async function load(user: User) {
  const requests = api.listArticles.mock.calls.length;
  await user.click(loadButton());
  await waitFor(() => {
    expect(api.listArticles.mock.calls.length).toBeGreaterThan(requests);
    expect(queryClient.isFetching()).toBe(0);
    expect(spinner()).not.toBeInTheDocument();
  });
}

async function renderLoaded() {
  const rendered = renderPage();
  await openExport(rendered.user);
  await load(rendered.user);
  return rendered;
}

function openCalendar(): HTMLElement {
  const open = Array.from(document.querySelectorAll<HTMLElement>(".ant-picker-dropdown")).filter(
    (dropdown) => !dropdown.classList.contains("ant-picker-dropdown-hidden"),
  );
  const calendar = open[open.length - 1];
  if (!calendar) throw new Error("No date picker is open");
  return calendar;
}

async function pickDate(user: User, isoDate: string) {
  await user.click(dateInput());
  const cell = await waitFor(() => {
    const found = openCalendar().querySelector<HTMLElement>(`td[title="${isoDate}"]`);
    if (!found) throw new Error(`No calendar cell for ${isoDate}`);
    return found;
  });
  await user.click(cell);
}

/** Reads a file as the bytes the browser saves, a byte order mark included. */
function readFile(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(new TextDecoder("utf-8", { ignoreBOM: true }).decode(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

/** Downloads the CSV and returns the one file the browser was handed. */
async function download(user: User) {
  await user.click(downloadButton());
  expect(downloads.files).toHaveLength(1);
  const [file] = downloads.files;
  const content = await readFile(file.blob);
  return { name: file.name, type: file.blob.type, content };
}

/** Splits CSV text into lines of cells; a quoted cell may hold the delimiter. */
function parseCsv(content: string, delimiter: string): string[][] {
  return content
    .replace(/^\uFEFF/, "")
    .split("\n")
    .map((line) => {
      const cells: string[] = [];
      let cell = "";
      let quoted = false;
      for (let index = 0; index < line.length; index += 1) {
        const char = line[index];
        if (quoted) {
          if (char === '"' && line[index + 1] === '"') {
            cell += '"';
            index += 1;
          } else if (char === '"') {
            quoted = false;
          } else {
            cell += char;
          }
        } else if (char === '"') {
          quoted = true;
        } else if (char === delimiter) {
          cells.push(cell);
          cell = "";
        } else {
          cell += char;
        }
      }
      cells.push(cell);
      return cells;
    });
}

/** The CSV's lines as records keyed by their header. */
function recordsOf(content: string, delimiter: string): Record<string, string>[] {
  const [headers, ...rows] = parseCsv(content, delimiter);
  return rows.map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index]])));
}

// Headers, as the mocked `t` writes them.
const ROW_TYPE = "commissioning.row_type_label";
const NAME = "commissioning.name";
const UNIT = "commissioning.unit";
const EXTRA = "commissioning.is_extra";
const PURCHASED = "commissioning.is_purchased";
const ACTIVE = "commissioning.is_active";
const FOR_RESELLERS = "commissioning.for_resellers";
const SHARE_OPTION = "commissioning.share_option_label";
const SHARE_OPTION_2 = "commissioning.share_option_2_label";
const SHARE_OPTION_3 = "commissioning.share_option_3_label";
const TAX_RATE = "commissioning.tax_rate";
const boxPrice = (unit: string, symbol = "€") => `commissioning.box_price_${unit} currencySymbol=${symbol}`;
const resellerPrice = (unit: string, index: number, tier: number, symbol = "€") =>
  `commissioning.reseller_${unit}_tier${index} currencySymbol=${symbol} tier=${tier}`;
const cratePriceHeader = (symbol = "€") => `commissioning.crate_price (${symbol})`;

const ARTICLE = "commissioning.row_type_article";
const CRATE = "commissioning.row_type_crate";

const ARTICLE_COLUMNS = [
  ROW_TYPE, NAME, UNIT, EXTRA, PURCHASED, ACTIVE, FOR_RESELLERS, SHARE_OPTION, SHARE_OPTION_2, SHARE_OPTION_3,
];
// Where the reseller prices start: after the article details, the tax rate
// and the three box prices.
const FIRST_RESELLER_PRICE = ARTICLE_COLUMNS.length + 4;

/** The columns besides the prices, for the rows in `records`. */
const describedBy = (records: Record<string, string>[], columns: string[]) =>
  records.map((record) => columns.map((column) => record[column]));

// ── Loading ─────────────────────────────────────────────────────────────────

describe("ExportCsvAllArticles loading", () => {
  it("fetches nothing until a date is loaded, and offers no download before", async () => {
    const { user } = renderPage();
    expect(queryDialog()).not.toBeInTheDocument();

    await openExport(user);

    expect(within(dialog()).getByText("commissioning.export_all_articles_combined")).toBeInTheDocument();
    expect(dateInput()).toHaveValue("05.10.2026");
    expect(downloadButton()).toBeDisabled();
    await flushMicrotasks();
    expect(api.listArticles).not.toHaveBeenCalled();
    expect(api.listCratePrices).not.toHaveBeenCalled();
  });

  it("shows the date in the tenant's date format", async () => {
    tenantState.settings = { date_format: "YYYY-MM-DD" };
    const { user } = renderPage();

    await openExport(user);

    expect(dateInput()).toHaveValue("2026-10-05");
  });

  it("loads every article, extras included, with its prices on the date, and every crate price", async () => {
    await renderLoaded();

    expect(api.listArticles).toHaveBeenCalledTimes(1);
    expect(api.listArticles).toHaveBeenCalledWith({
      include_extra: true,
      get_price_info: true,
      is_data_list: true,
      price_date: "2026-10-05",
    });
    expect(api.listCratePrices).toHaveBeenCalledTimes(1);
    expect(api.listCratePrices).toHaveBeenCalledWith({});
    // Four articles and the two crates priced today.
    expect(within(dialog()).getByText("commissioning.articles_loaded count=6")).toBeVisible();
    expect(downloadButton()).toBeEnabled();
  });

  it("shows a spinner while the rows load and offers no download until they are in", async () => {
    let deliver: (rows: ShareArticle[]) => void = () => {};
    api.listArticles.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    const { user } = renderPage();
    await openExport(user);

    await user.click(loadButton());

    await waitFor(() => expect(spinner()).toBeInTheDocument());
    expect(loadButton()).toHaveClass("ant-btn-loading");
    expect(downloadButton()).toBeDisabled();

    deliver([CARROTS]);

    expect(await within(dialog()).findByText("commissioning.articles_loaded count=3")).toBeVisible();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(downloadButton()).toBeEnabled();
  });

  it("says there is nothing to export when no article or crate has a row", async () => {
    articlesOn = () => [];
    api.listCratePrices.mockResolvedValue([]);
    const { user } = renderPage();
    await openExport(user);

    await load(user);

    expect(within(dialog()).getByText("common.no_data")).toBeVisible();
    expect(downloadButton()).toBeDisabled();
  });

  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});

// ── The file ────────────────────────────────────────────────────────────────

describe("ExportCsvAllArticles file", () => {
  it("saves a CSV named after the date, with a byte order mark, and closes", async () => {
    const { user, onClose } = await renderLoaded();

    const file = await download(user);

    expect(file.name).toBe("all_articles_with_prices_2026-10-05.csv");
    expect(file.type).toBe("text/csv;charset=utf-8;");
    expect(file.content.startsWith("\uFEFF")).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(queryDialog()).not.toBeInTheDocument());
  });

  it("heads the columns with the article details, the tax rate, the box and reseller prices and the crate price", async () => {
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const [headers] = parseCsv(content, ";");
    expect(headers).toEqual([
      ...ARTICLE_COLUMNS,
      TAX_RATE,
      boxPrice("kg"), boxPrice("pieces"), boxPrice("bunch"),
      resellerPrice("kg", 1, 1), resellerPrice("pieces", 1, 1), resellerPrice("bunch", 1, 1),
      cratePriceHeader(),
    ]);
  });

  it("writes one line per article, then one per crate priced on the date", async () => {
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const records = recordsOf(content, ";");
    expect(describedBy(records, ARTICLE_COLUMNS)).toEqual([
      [ARTICLE, "Carrots", "KG", "nein", "nein", "ja", "ja", "HARVEST_SHARE", "", ""],
      [ARTICLE, "Lemons, organic", "PCS", "nein", "ja", "ja", "nein", "HARVEST_SHARE", "HARVEST_SHARE_FRUIT", ""],
      [ARTICLE, "Radishes", "BUNCH", "nein", "nein", "nein", "nein", "", "", ""],
      [ARTICLE, "Farm tour", "PCS", "ja", "nein", "ja", "nein", "", "", ""],
      [CRATE, "Euro crate E2", "", "", "", "", "", "", "", ""],
      [CRATE, "Banana box", "", "", "", "", "", "", "", ""],
    ]);
  });

  it("writes yes and no in English for an English-speaking office", async () => {
    i18nMock.state.language = "en";
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const carrots = recordsOf(content, ";")[0];
    expect([carrots[EXTRA], carrots[PURCHASED], carrots[ACTIVE], carrots[FOR_RESELLERS]]).toEqual([
      "no", "no", "yes", "yes",
    ]);
  });

  it("writes the English CSV dialect when the tenant asks for it, quoting a name that holds a comma", async () => {
    tenantState.settings = { csv_format: "en" };
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const lines = content.replace(/^\uFEFF/, "").split("\n");
    expect(lines).toHaveLength(7);
    expect(lines[0].split(",").slice(0, 3)).toEqual([ROW_TYPE, NAME, UNIT]);
    expect(lines[2]).toContain('"Lemons, organic"');
    const records = recordsOf(content, ",");
    expect(records.map((record) => record[NAME])).toEqual([
      "Carrots", "Lemons, organic", "Radishes", "Farm tour", "Euro crate E2", "Banana box",
    ]);
  });

  it("writes each article's prices on the date and each crate's tax rate and price", async () => {
    tenantState.settings = { csv_format: "en" };
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const prices = [TAX_RATE, boxPrice("kg"), boxPrice("pieces"), boxPrice("bunch"),
      resellerPrice("kg", 1, 1), resellerPrice("pieces", 1, 1), resellerPrice("bunch", 1, 1), cratePriceHeader()];
    expect(describedBy(recordsOf(content, ","), prices)).toEqual([
      ["10.00", "2.50", "", "", "2.20", "", "", ""],
      ["10.00", "", "0.45", "", "", "0.40", "", ""],
      ["", "", "", "", "", "", "", ""],
      ["20.00", "", "15.00", "", "", "", "", ""],
      ["20.00", "", "", "", "", "", "", "1.20"],
      ["20.00", "", "", "", "", "", "", "0.80"],
    ]);
  });

  it("writes the prices and tax rates with the decimal comma of the tenant's German format", async () => {
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const prices = [TAX_RATE, boxPrice("kg"), resellerPrice("kg", 1, 1), cratePriceHeader()];
    const records = describedBy(recordsOf(content, ";"), prices);
    expect(records[0]).toEqual(["10,00", "2,50", "2,20", ""]);
    expect(records[4]).toEqual(["20,00", "", "", "1,20"]);
  });

  it("writes a reseller price column for each of the tenant's offer tiers", async () => {
    tenantState.settings = { csv_format: "en", used_tiers_for_offers: [1, 5, 10] };
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const [headers] = parseCsv(content, ",");
    const resellerColumns = [
      resellerPrice("kg", 1, 1), resellerPrice("kg", 2, 5), resellerPrice("kg", 3, 10),
      resellerPrice("pieces", 1, 1), resellerPrice("pieces", 2, 5), resellerPrice("pieces", 3, 10),
      resellerPrice("bunch", 1, 1), resellerPrice("bunch", 2, 5), resellerPrice("bunch", 3, 10),
    ];
    expect(headers.slice(FIRST_RESELLER_PRICE)).toEqual([...resellerColumns, cratePriceHeader()]);
    const carrots = recordsOf(content, ",")[0];
    expect(resellerColumns.slice(0, 3).map((column) => carrots[column])).toEqual(["2.20", "2.00", "1.80"]);
  });

  it("names prices in the tenant's currency", async () => {
    tenantState.settings = { currency: "CHF" };
    const { user } = await renderLoaded();

    const { content } = await download(user);

    const [headers] = parseCsv(content, ";");
    expect(headers).toContain(boxPrice("kg", "CHF"));
    expect(headers).toContain(resellerPrice("bunch", 1, 1, "CHF"));
    expect(headers[headers.length - 1]).toBe(cratePriceHeader("CHF"));
    expect(headers.join("|")).not.toContain("€");
  });
});

// ── Dates ───────────────────────────────────────────────────────────────────

describe("ExportCsvAllArticles dates", () => {
  it("exports the prices of another date once that date is loaded, and names the file after it", async () => {
    tenantState.settings = { csv_format: "en" };
    const { user } = await renderLoaded();

    await pickDate(user, "2026-11-02");
    expect(dateInput()).toHaveValue("02.11.2026");
    await load(user);

    expect(api.listArticles).toHaveBeenLastCalledWith(expect.objectContaining({ price_date: "2026-11-02" }));
    expect(within(dialog()).getByText("commissioning.articles_loaded count=7")).toBeVisible();
    const file = await download(user);
    expect(file.name).toBe("all_articles_with_prices_2026-11-02.csv");
    const records = recordsOf(file.content, ",");
    expect(records[0][resellerPrice("kg", 1, 1)]).toBe("2.40");
    expect(records.slice(4).map((record) => [record[NAME], record[cratePriceHeader()]])).toEqual([
      ["Euro crate E2", "1.50"],
      ["Harvest bin", "3.00"],
      ["Banana box", "0.80"],
    ]);
  });

  it("counts a crate price as valid through its last day", async () => {
    tenantState.settings = { csv_format: "en" };
    const { user } = await renderLoaded();

    await pickDate(user, "2026-11-01");
    await load(user);

    const records = recordsOf((await download(user)).content, ",");
    expect(records.slice(4).map((record) => [record[NAME], record[cratePriceHeader()]])).toEqual([
      ["Harvest bin", "3.00"],
      ["Euro crate E2", "1.20"],
      ["Banana box", "0.80"],
    ]);
  });

  it("forgets the loaded rows when closed without a download", async () => {
    const { user, onClose } = await renderLoaded();

    await user.click(within(dialog()).getByRole("button", { name: "common.cancel" }));
    await waitFor(() => expect(queryDialog()).not.toBeInTheDocument());
    await openExport(user);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(downloadButton()).toBeDisabled();
    expect(within(dialog()).queryByText(/commissioning\.articles_loaded/)).not.toBeInTheDocument();
    expect(downloads.files).toHaveLength(0);
  });
});
