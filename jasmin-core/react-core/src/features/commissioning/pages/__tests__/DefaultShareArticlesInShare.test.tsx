/**
 * DefaultShareArticlesInShare: how much of each share article goes into each
 * size of a share by default — one row per active article that belongs to a
 * share, one column per physical share-type variation running today, grouped
 * by share type. The office edits a row and saves all of its amounts at once;
 * every other role only reads them. Rendered with the real EditableTable and
 * column hooks. The generated commissioning client is the mocking boundary: its
 * list hooks are real TanStack queries around spies that answer from an
 * in-memory farm, and its bulk upsert stores and removes amounts the way the
 * backend does.
 *
 * The clock is frozen at noon local time, which falls on the same date in UTC
 * wherever the offset from UTC is under twelve hours.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DefaultShareArticleInShare,
  DefaultShareArticleInShareBulkEntry,
  DefaultShareArticleInShareBulkUpsertRequest,
  ShareTypeVariation,
  UnitEnum,
} from "@shared/api/generated/models";
import germanErrors from "@shared/i18n/locales/de/errors.json";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

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

// The tenant's settings, per test; an unset setting falls back to the caller's default.
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the signed-in user's roles from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", roles: auth.roles } }),
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }));
vi.mock("@shared/utils/notify", () => ({ default: notify }));

const api = vi.hoisted(() => ({
  listArticles: vi.fn(), listVariations: vi.fn(), listDefaults: vi.fn(), bulkUpsert: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) =>
    [`/api/commissioning/${path}/`, ...(params ? [params] : [])];
  const queryHook = (path: string, request: (params?: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      return useQuery({
        queryKey: queryKey(path, params),
        queryFn: async () => request(params),
        enabled: options?.query?.enabled,
      });
    };
  return {
    useCommissioningShareArticlesList: queryHook("share_articles", api.listArticles),
    useCommissioningShareTypeVariationsList: queryHook("share_type_variations", api.listVariations),
    useCommissioningDefaultShareArticlesInShareList: queryHook("default_share_articles_in_share", api.listDefaults),
    getCommissioningDefaultShareArticlesInShareListQueryKey: (params?: unknown) =>
      queryKey("default_share_articles_in_share", params),
    commissioningDefaultShareArticlesInShareBulkUpsertCreate: (payload: unknown) => api.bulkUpsert(payload),
  };
});

import DefaultShareArticlesInShare from "../DefaultShareArticlesInShare";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Wednesday 7 October 2026.
const NOW = new Date(2026, 9, 7, 12, 0);
const TODAY = "2026-10-07";

const VEGETABLE_SHARE = "Vegetable share";
const FRUIT_SHARE = "Fruit share";
const SHARE_TYPE_NAMES: Record<string, string> = {
  "share-type-vegetables": VEGETABLE_SHARE,
  "share-type-fruit": FRUIT_SHARE,
  "share-type-mixed": "Mixed share",
};

/** A share-type variation, which the server always lists with its id. */
type Variation = ShareTypeVariation & { id: string };

function variation(
  id: string,
  shareType: string,
  size: ShareTypeVariation["size"],
  sortOrder: number,
  fields: Partial<ShareTypeVariation> = {},
): Variation {
  return {
    id, share_type: shareType, share_type_name: SHARE_TYPE_NAMES[shareType], size, sort_order: sortOrder,
    variation_type: "physical", valid_from: "2026-01-05", valid_until: null, ...fields,
  };
}

const VEGETABLES_S = variation("variation-vegetables-s", "share-type-vegetables", "S", 1);
// Ends this Sunday; the M taking over from it starts next Monday.
const VEGETABLES_M = variation("variation-vegetables-m", "share-type-vegetables", "M", 2, {
  valid_until: "2026-10-11",
});
const VEGETABLES_M_NEXT = variation("variation-vegetables-m-next", "share-type-vegetables", "M", 2, {
  valid_from: "2026-10-12",
});
// Started this Monday.
const VEGETABLES_L = variation("variation-vegetables-l", "share-type-vegetables", "L", 3, {
  valid_from: "2026-10-05",
});
// Ended last Sunday.
const VEGETABLES_XL = variation("variation-vegetables-xl", "share-type-vegetables", "XL", 4, {
  valid_from: "2025-01-06", valid_until: "2026-10-04",
});
const FRUIT_S = variation("variation-fruit-s", "share-type-fruit", "S", 1);
const FRUIT_L = variation("variation-fruit-l", "share-type-fruit", "L", 2);
// Made up of a vegetable and a fruit share, so it has no contents of its own.
const MIXED = variation("variation-mixed", "share-type-mixed", "M", 1, { variation_type: "virtual" });

const VARIATIONS = [
  VEGETABLES_S, VEGETABLES_M, VEGETABLES_M_NEXT, VEGETABLES_L, VEGETABLES_XL, FRUIT_S, FRUIT_L, MIXED,
];

/** A share article as the data list carries it, with up to three share options. */
interface Article {
  id: string;
  name: string;
  default_movement_unit: UnitEnum;
  is_active: boolean;
  share_option: string | null;
  share_option2: string | null;
  share_option3: string | null;
}

const article = (id: string, name: string, unit: UnitEnum, options: string[], isActive = true): Article => ({
  id, name, default_movement_unit: unit, is_active: isActive,
  share_option: options[0] ?? null, share_option2: options[1] ?? null, share_option3: options[2] ?? null,
});

const APPLES = article("article-apples", "Apples", "PCS", ["HARVEST_SHARE_FRUIT"]);
// No amounts yet.
const BEETROOT = article("article-beetroot", "Beetroot", "KG", ["HARVEST_SHARE"]);
const CARROTS = article("article-carrots", "Carrots", "KG", ["HARVEST_SHARE"]);
const PARSLEY = article("article-parsley", "Parsley", "BUNCH", ["HARVEST_SHARE", "HARVEST_SHARE_FRUIT"]);
// Sold to resellers only, in no share.
const POTATO_SACK = article("article-potato-sack", "Potato sack", "PCS", []);
// No longer grown.
const RADISHES = article("article-radishes", "Radishes", "BUNCH", ["HARVEST_SHARE"], false);

const ARTICLES = [APPLES, BEETROOT, CARROTS, PARSLEY, POTATO_SACK, RADISHES];

let storedCount = 0;

/** An amount as the server keeps it: with three decimals, in the article's unit. */
function stored(articleId: string, variationId: string, quantity: string): DefaultShareArticleInShare {
  storedCount += 1;
  const owner = ARTICLES.find((each) => each.id === articleId);
  const shareTypeVariation = VARIATIONS.find((each) => each.id === variationId);
  return {
    id: `default-${storedCount}`, share_article: articleId, share_article_name: owner?.name,
    share_type_variation: variationId, share_type_variation_size: shareTypeVariation?.size,
    share_type_id: shareTypeVariation?.share_type, quantity: Number(quantity).toFixed(3),
    unit: owner?.default_movement_unit ?? null,
  };
}

// What the server currently holds; the requests answer from it.
let serverArticles: Article[] = [];
let serverVariations: Variation[] = [];
let serverDefaults: DefaultShareArticleInShare[] = [];

type Params = Record<string, unknown> | undefined;

/** Running on `date`: from its Monday through its Sunday, both included. */
const runsOn = (each: Variation, date: string) =>
  each.valid_from <= date && (each.valid_until == null || each.valid_until >= date);

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: unknown, message = `Request failed with status code ${status}`) =>
  Object.assign(new Error(message), { isAxiosError: true, response: { status, data } });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  tenantSettings.values = {};
  Object.values(notify).forEach((fn) => fn.mockReset());
  serverArticles = [...ARTICLES];
  serverVariations = [...VARIATIONS];
  serverDefaults = [
    stored(CARROTS.id, VEGETABLES_S.id, "0.5"),
    stored(CARROTS.id, VEGETABLES_M.id, "1"),
    stored(CARROTS.id, VEGETABLES_L.id, "1.25"),
    stored(CARROTS.id, VEGETABLES_XL.id, "2"),
    stored(APPLES.id, FRUIT_S.id, "2"),
    stored(APPLES.id, FRUIT_L.id, "3.5"),
    stored(PARSLEY.id, VEGETABLES_S.id, "1"),
    // Already set for the M that takes over next Monday.
    stored(PARSLEY.id, VEGETABLES_M_NEXT.id, "1"),
    stored(PARSLEY.id, FRUIT_L.id, "0.75"),
    stored(RADISHES.id, VEGETABLES_S.id, "1"),
  ];
  api.listArticles.mockReset().mockImplementation(async (params: Params) =>
    serverArticles
      .filter((each) => params?.is_active === undefined || each.is_active === params.is_active)
      .sort((a, b) => a.name.localeCompare(b.name)),
  );
  // Newest first, as the backend lists them.
  api.listVariations.mockReset().mockImplementation(async (params: Params) =>
    serverVariations
      .filter((each) => !params?.active_at_date || runsOn(each, String(params.active_at_date)))
      .filter((each) => !params?.physical || each.variation_type === "physical")
      .sort((a, b) => b.valid_from.localeCompare(a.valid_from) || (a.sort_order ?? 0) - (b.sort_order ?? 0)),
  );
  api.listDefaults.mockReset().mockImplementation(async () => [...serverDefaults]);
  // Stores each entry's amount and removes the ones without an amount.
  api.bulkUpsert.mockReset().mockImplementation(
    async ({ share_article: articleId, entries }: DefaultShareArticleInShareBulkUpsertRequest) => {
      if (!serverArticles.some((each) => each.id === articleId)) {
        throw httpError(404, { code: "share_article.not_found", message: `ShareArticle ${articleId} not found` });
      }
      for (const { share_type_variation: variationId, quantity } of entries) {
        const others = serverDefaults.filter(
          (row) => row.share_article !== articleId || row.share_type_variation !== variationId,
        );
        const keep = quantity !== null && Number(quantity) > 0;
        serverDefaults = keep ? [...others, stored(articleId, variationId, quantity)] : others;
      }
      return serverDefaults.filter((row) => row.share_article === articleId);
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const defaultOptions = { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } };
  const queryClient = new QueryClient({ defaultOptions });
  render(
    <QueryClientProvider client={queryClient}>{profiler.wrap(<DefaultShareArticlesInShare />)}</QueryClientProvider>,
  );
  return { user, profiler };
}

const ACTIONS = "table.actions";
const ARTICLE = "commissioning.share_articles";
const UNIT = "commissioning.default_movement_unit";

/** The title of a variation's column: its share type, then its size. */
const column = (shareType: string, size: string) => `${shareType} commissioning.${size}`;

const FRUIT_S_COLUMN = column(FRUIT_SHARE, "S");
const FRUIT_L_COLUMN = column(FRUIT_SHARE, "L");
const VEGETABLES_S_COLUMN = column(VEGETABLE_SHARE, "S");
const VEGETABLES_M_COLUMN = column(VEGETABLE_SHARE, "M");
const VEGETABLES_L_COLUMN = column(VEGETABLE_SHARE, "L");

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

/**
 * The title of each column the body cells line up with. A variation's column
 * sits under its share type's header, so it goes by both.
 */
function columnTitles(): string[] {
  const [top, sizes] = Array.from(document.querySelectorAll(".ant-table-thead > tr"));
  if (!top) return [];
  const text = (cell: Element) => cell.textContent?.trim() ?? "";
  const sizeTitles = Array.from(sizes?.querySelectorAll(":scope > th") ?? [], text);
  return Array.from(top.querySelectorAll<HTMLTableCellElement>(":scope > th")).flatMap((cell) =>
    !sizes || cell.rowSpan > 1
      ? [text(cell)]
      : sizeTitles.splice(0, cell.colSpan).map((size) => `${text(cell)} ${size}`),
  );
}

function rowAround(element: HTMLElement, what: string): HTMLElement {
  const row = element.closest("tr");
  if (!row) throw new Error(`No table row ${what}`);
  return row;
}
const rowOf = (name: string) => rowAround(screen.getByText(name), `shows ${name}`);
/** The row being edited — the one offering a save button. */
const editingRow = () => rowAround(screen.getByRole("button", { name: "table.save" }), "is being edited");

function cellOf(row: HTMLElement, title: string): HTMLElement {
  const index = columnTitles().indexOf(title);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${title}`);
  return cell;
}

const shownNames = () => bodyRows().map((row) => cellOf(row, ARTICLE).textContent);

/** What an article's row shows under each variation, in column order. */
const amountsOf = (name: string) =>
  columnTitles()
    .filter((title) => ![ACTIONS, ARTICLE, UNIT].includes(title))
    .map((title) => cellOf(rowOf(name), title).textContent);

// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");

/** Renders the page and waits until the articles, variations and amounts are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await waitFor(() => expect(cellOf(rowOf("Carrots"), VEGETABLES_S_COLUMN)).toHaveTextContent("0,5"));
  await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  return rendered;
}

type User = ReturnType<typeof userEvent.setup>;

const startedEditing = () => screen.findByRole("button", { name: "table.save" });

async function editRow(user: User, name: string) {
  await user.click(within(rowOf(name)).getByRole("button", { name: "table.edit" }));
  await startedEditing();
}
const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));
/** The input of a variation's amount in the row being edited. */
const amountInput = (title: string) => within(cellOf(editingRow(), title)).getByRole("textbox");

async function typeAmount(user: User, title: string, text: string) {
  const input = amountInput(title);
  await user.clear(input);
  if (text) await user.type(input, text);
}

/** A bulk upsert of an article's changed amounts, a null for an amount cleared. */
const upsert = (articleId: string, amounts: [Variation, string | null][]) => ({
  share_article: articleId,
  entries: amounts
    .map(([shareTypeVariation, quantity]) => ({ share_type_variation: shareTypeVariation.id, quantity }))
    .sort((a, b) => a.share_type_variation.localeCompare(b.share_type_variation)),
});

/** The last bulk upsert sent, its entries in the order `upsert` puts them. */
function lastUpsert() {
  const payload = api.bulkUpsert.mock.lastCall?.[0] as DefaultShareArticleInShareBulkUpsertRequest | undefined;
  if (!payload) throw new Error("Nothing was saved");
  const entries: DefaultShareArticleInShareBulkEntry[] = [...payload.entries].sort((a, b) =>
    a.share_type_variation.localeCompare(b.share_type_variation),
  );
  return { ...payload, entries };
}

const savedOnce = () => waitFor(() => expect(api.bulkUpsert).toHaveBeenCalledTimes(1));
const reloaded = () => waitFor(() => expect(api.listDefaults).toHaveBeenCalledTimes(2));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

// ── Loading and layout ──────────────────────────────────────────────────────

describe("DefaultShareArticlesInShare loading and layout", () => {
  it("asks for the active articles, today's physical variations and the stored amounts, once each", async () => {
    await renderLoaded();

    expect(api.listArticles).toHaveBeenCalledTimes(1);
    expect(api.listArticles).toHaveBeenCalledWith({ is_data_list: true, is_active: true });
    expect(api.listVariations).toHaveBeenCalledTimes(1);
    expect(api.listVariations).toHaveBeenCalledWith({ active_at_date: TODAY, physical: true });
    expect(api.listDefaults).toHaveBeenCalledTimes(1);
  });

  it("keeps a spinner over the table until the stored amounts are there", async () => {
    const amounts = pending<DefaultShareArticleInShare[]>();
    api.listDefaults.mockImplementation(() => amounts.promise);
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(spinner()).toBeInTheDocument();

    amounts.answer([...serverDefaults]);

    await waitFor(() => expect(cellOf(rowOf("Carrots"), VEGETABLES_S_COLUMN)).toHaveTextContent("0,5"));
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the article and unit columns, a column per variation and the explainer", async () => {
    await renderLoaded();

    expect(
      screen.getByRole("heading", { level: 1, name: "commissioning.default_share_articles_in_share" }),
    ).toBeVisible();
    expect(columnTitles()).toEqual([
      ACTIONS, ARTICLE, UNIT, FRUIT_S_COLUMN, FRUIT_L_COLUMN, VEGETABLES_S_COLUMN, VEGETABLES_M_COLUMN,
      VEGETABLES_L_COLUMN,
    ]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.default_share_articles_in_share")).toBeInTheDocument();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Rows ────────────────────────────────────────────────────────────────────

describe("DefaultShareArticlesInShare rows", () => {
  it("lists the active articles that belong to a share, by name, each with its unit", async () => {
    await renderLoaded();

    expect(shownNames()).toEqual(["Apples", "Beetroot", "Carrots", "Parsley"]);
    expect(cellOf(rowOf("Apples"), UNIT)).toHaveTextContent("commissioning.units.pcs");
    expect(cellOf(rowOf("Carrots"), UNIT)).toHaveTextContent("commissioning.units.kg");
    expect(cellOf(rowOf("Parsley"), UNIT)).toHaveTextContent("commissioning.units.bunch");
  });

  it("shows each stored amount under its variation in the tenant's number format and leaves the rest empty", async () => {
    await renderLoaded();

    // Fruit S, fruit L, vegetables S, M and L.
    expect(amountsOf("Apples")).toEqual(["2", "3,5", "", "", ""]);
    expect(amountsOf("Beetroot")).toEqual(["", "", "", "", ""]);
    expect(amountsOf("Carrots")).toEqual(["", "", "0,5", "1", "1,25"]);
    expect(amountsOf("Parsley")).toEqual(["", "0,75", "1", "", ""]);
  });

  it("writes the amounts the way the tenant's number locale does", async () => {
    tenantSettings.values = { number_locale: "en-US" };
    renderPage();

    await waitFor(() => expect(amountsOf("Carrots")).toEqual(["", "", "0.5", "1", "1.25"]));
    expect(amountsOf("Parsley")).toEqual(["", "0.75", "1", "", ""]);
  });

  it("finds the articles whose name holds what the office searches for", async () => {
    const { user } = await renderLoaded();

    await user.type(screen.getByRole("searchbox", { name: "table.search_placeholder" }), "AR");

    expect(shownNames()).toEqual(["Carrots", "Parsley"]);
  });
});

// ── Variation columns ───────────────────────────────────────────────────────

describe("DefaultShareArticlesInShare variations", () => {
  it("gives each physical variation running today a column, grouped by share type in the sizes' sort order", async () => {
    await renderLoaded();

    // The vegetable L, started this Monday, comes newest-first from the server
    // but still goes last; the M ending this Sunday still runs, while the M
    // after it, the XL that ended last Sunday and the mixed share don't.
    const variationColumns = columnTitles().filter((title) => ![ACTIONS, ARTICLE, UNIT].includes(title));
    expect(variationColumns).toEqual([
      FRUIT_S_COLUMN, FRUIT_L_COLUMN, VEGETABLES_S_COLUMN, VEGETABLES_M_COLUMN, VEGETABLES_L_COLUMN,
    ]);
    expect(screen.queryByText("Mixed share")).not.toBeInTheDocument();
    expect(screen.queryByText(/commissioning\.XL/)).not.toBeInTheDocument();
  });

  // Carrots have an amount for the M ending on Sunday, parsley one for the M
  // taking over on Monday.
  it.each([
    ["Sunday", new Date(2026, 9, 11, 12, 0), "2026-10-11", VEGETABLES_M, { carrots: "1", parsley: "" }],
    ["Monday", new Date(2026, 9, 12, 12, 0), "2026-10-12", VEGETABLES_M_NEXT, { carrots: "", parsley: "1" }],
  ])("on %s, shows and saves the amounts of the M running that day", async (_day, now, date, runningM, inM) => {
    vi.setSystemTime(now);
    const { user } = await renderLoaded();

    expect(api.listVariations).toHaveBeenCalledWith({ active_at_date: date, physical: true });
    expect(cellOf(rowOf("Carrots"), VEGETABLES_M_COLUMN).textContent).toBe(inM.carrots);
    expect(cellOf(rowOf("Parsley"), VEGETABLES_M_COLUMN).textContent).toBe(inM.parsley);

    await editRow(user, "Beetroot");
    await typeAmount(user, VEGETABLES_M_COLUMN, "3");
    await saveRow(user);

    await savedOnce();
    expect(lastUpsert().entries).toEqual([{ share_type_variation: runningM.id, quantity: "3" }]);
  });

  it("takes the local date as today, also just after midnight", async () => {
    // In Berlin the UTC date is still Sunday's until 02:00 on a summer Monday.
    vi.setSystemTime(new Date(2026, 9, 12, 0, 30));
    await renderLoaded();

    expect(api.listVariations).toHaveBeenCalledWith({ active_at_date: "2026-10-12", physical: true });
  });

  it("still lists the articles, without amount columns, when no variation is running today", async () => {
    serverVariations = [];
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(columnTitles()).toEqual([ACTIONS, ARTICLE, UNIT]);
    expect(shownNames()).toEqual(["Apples", "Beetroot", "Carrots", "Parsley"]);
  });
});

// ── Editing ─────────────────────────────────────────────────────────────────

describe("DefaultShareArticlesInShare editing", () => {
  it("saves a new article's amounts in one bulk upsert and shows them after reloading", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Beetroot");
    await typeAmount(user, VEGETABLES_S_COLUMN, "1");
    await typeAmount(user, VEGETABLES_L_COLUMN, "2,5");
    await saveRow(user);

    await savedOnce();
    expect(lastUpsert()).toEqual(upsert(BEETROOT.id, [[VEGETABLES_S, "1"], [VEGETABLES_L, "2.5"]]));
    await reloaded();
    await waitFor(() => expect(amountsOf("Beetroot")).toEqual(["", "", "1", "", "2,5"]));
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(serverDefaults.filter((row) => row.share_article === BEETROOT.id)).toHaveLength(2);
  });

  it("sends only the amounts the office changed or cleared, leaving the rest as stored", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Carrots");
    await typeAmount(user, VEGETABLES_M_COLUMN, "1,75");
    await typeAmount(user, VEGETABLES_L_COLUMN, "");
    await saveRow(user);

    await savedOnce();
    expect(lastUpsert()).toEqual(upsert(CARROTS.id, [[VEGETABLES_M, "1.75"], [VEGETABLES_L, null]]));
    await reloaded();
    await waitFor(() => expect(amountsOf("Carrots")).toEqual(["", "", "0,5", "1,75", ""]));
    // The amount for the XL, which no longer runs, stays as it was.
    expect(serverDefaults).toContainEqual(
      expect.objectContaining({ share_article: CARROTS.id, share_type_variation: VEGETABLES_XL.id, quantity: "2.000" }),
    );
  });

  it("sends nothing for a row saved unchanged, and shows a 0 typed into an empty cell as empty", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Beetroot");
    await typeAmount(user, VEGETABLES_S_COLUMN, "0");
    await saveRow(user);

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument(),
    );
    expect(api.bulkUpsert).not.toHaveBeenCalled();
    expect(amountsOf("Beetroot")).toEqual(["", "", "", "", ""]);
  });

  it("treats an amount of 0 as no amount", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Apples");
    await typeAmount(user, FRUIT_S_COLUMN, "0");
    await saveRow(user);

    await savedOnce();
    expect(lastUpsert().entries).toContainEqual({ share_type_variation: FRUIT_S.id, quantity: null });
    await reloaded();
    await waitFor(() => expect(amountsOf("Apples")).toEqual(["", "3,5", "", "", ""]));
  });

  it("opens a row by a click on one of its amounts and saves it with Enter", async () => {
    const { user } = await renderLoaded();

    await user.click(cellOf(rowOf("Parsley"), VEGETABLES_M_COLUMN));
    await startedEditing();
    await typeAmount(user, VEGETABLES_M_COLUMN, "2{Enter}");

    await savedOnce();
    expect(lastUpsert()).toEqual(upsert(PARSLEY.id, [[VEGETABLES_M, "2"]]));
  });

  it("offers inputs only for the amounts, keeping the article and its unit as they are", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Carrots");

    const row = editingRow();
    expect(within(row).getAllByRole("textbox")).toHaveLength(5);
    expect(within(cellOf(row, ARTICLE)).queryByRole("combobox")).not.toBeInTheDocument();
    expect(cellOf(row, ARTICLE)).toHaveTextContent("Carrots");
    expect(within(cellOf(row, UNIT)).queryByRole("combobox")).not.toBeInTheDocument();
    expect(cellOf(row, UNIT)).toHaveTextContent("commissioning.units.kg");
  });

  it("shows a spinner while it saves", async () => {
    const response = pending<DefaultShareArticleInShare[]>();
    const { user } = await renderLoaded();
    api.bulkUpsert.mockImplementationOnce(() => response.promise);

    await editRow(user, "Beetroot");
    await typeAmount(user, VEGETABLES_S_COLUMN, "1");
    await saveRow(user);

    await waitFor(() => expect(spinner()).toBeInTheDocument());
    response.answer([]);
    await reloaded();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });
});

// ── What the amount inputs take ─────────────────────────────────────────────

describe("DefaultShareArticlesInShare amount inputs", () => {
  it("takes positive amounts with up to two decimals and nothing else", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Beetroot");
    await typeAmount(user, VEGETABLES_S_COLUMN, "-1,257");
    await typeAmount(user, VEGETABLES_M_COLUMN, "2,5,1x");

    expect(amountInput(VEGETABLES_S_COLUMN)).toHaveValue("1,25");
    expect(amountInput(VEGETABLES_M_COLUMN)).toHaveValue("2,51");
    await saveRow(user);

    await savedOnce();
    expect(lastUpsert()).toEqual(
      upsert(BEETROOT.id, [[VEGETABLES_S, "1.25"], [VEGETABLES_M, "2.51"]]),
    );
  });

  it("takes a point as the decimal separator as well", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Beetroot");
    await typeAmount(user, FRUIT_L_COLUMN, "0.5");
    await saveRow(user);

    await savedOnce();
    expect(lastUpsert().entries).toContainEqual({ share_type_variation: FRUIT_L.id, quantity: "0.5" });
  });
});

// ── Refused saves ───────────────────────────────────────────────────────────

describe("DefaultShareArticlesInShare refused saves", () => {
  it("shows the server's reason, keeps the typed amounts open and doesn't reload", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    // Deleted on another screen while this one was open.
    serverArticles = serverArticles.filter((each) => each.id !== BEETROOT.id);

    await editRow(user, "Beetroot");
    await typeAmount(user, VEGETABLES_S_COLUMN, "1");
    await saveRow(user);

    const reason = germanErrors.share_article.not_found;
    await waitFor(() => expect(notify.error).toHaveBeenCalledWith(reason));
    expect(await screen.findByText(`${reason} — table.save_failed_hint`)).toBeVisible();
    expect(amountInput(VEGETABLES_S_COLUMN)).toHaveValue("1");
    expect(api.listDefaults).toHaveBeenCalledTimes(1);
  });

  it("names the failure in its own words when the server gives no reason", async () => {
    silenceConsoleErrors();
    // A gateway failure with neither a body nor a message.
    api.bulkUpsert.mockRejectedValueOnce(httpError(502, "", ""));
    const { user } = await renderLoaded();

    await editRow(user, "Carrots");
    await typeAmount(user, VEGETABLES_S_COLUMN, "0,6");
    await saveRow(user);

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("commissioning.default_share_articles_save_failed"),
    );
    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(amountInput(VEGETABLES_S_COLUMN)).toHaveValue("0,6");
    expect(serverDefaults).toContainEqual(
      expect.objectContaining({ share_article: CARROTS.id, share_type_variation: VEGETABLES_S.id, quantity: "0.500" }),
    );
  });
});

// ── Empty and error states ──────────────────────────────────────────────────

describe("DefaultShareArticlesInShare empty and error states", () => {
  it("shows a hint instead of rows when no article belongs to a share", async () => {
    serverArticles = [POTATO_SACK, RADISHES];
    renderPage();

    await waitFor(() => expect(api.listArticles).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("keeps the amounts read-only and offers a retry when they fail to load", async () => {
    api.listDefaults.mockRejectedValueOnce(httpError(503, { message: "Down" }));
    const { user } = renderPage();

    expect(await screen.findByText("table.load_failed_title")).toBeInTheDocument();
    await waitFor(() => expect(rowOf("Carrots")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "table.retry" }));

    await waitFor(() => expect(amountsOf("Carrots")).toEqual(["", "", "0,5", "1", "1,25"]));
    expect(within(rowOf("Carrots")).getByRole("button", { name: "table.edit" })).toBeEnabled();
    expect(screen.queryByText("table.load_failed_title")).not.toBeInTheDocument();
  });

  it("keeps the page up when the articles fail to load", async () => {
    api.listArticles.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listArticles).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(
      screen.getByRole("heading", { level: 1, name: "commissioning.default_share_articles_in_share" }),
    ).toBeVisible();
    expect(screen.getByText("explainers.default_share_articles_in_share")).toBeInTheDocument();
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("DefaultShareArticlesInShare roles", () => {
  it.each(["office", "admin"])("lets the %s edit each row's amounts but not add or delete articles", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    for (const name of ["Apples", "Beetroot", "Carrots", "Parsley"]) {
      expect(within(rowOf(name)).getByRole("button", { name: "table.edit" })).toBeEnabled();
    }
    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
  });

  it.each(["gardener", "staff", "management"])("shows the amounts to the %s read-only", async (role) => {
    auth.roles = [role];
    const { user } = await renderLoaded();

    expect(columnTitles()).not.toContain(ACTIONS);
    expect(amountsOf("Carrots")).toEqual(["", "", "0,5", "1", "1,25"]);
    expect(screen.queryByRole("button", { name: /table\.(edit|save|delete|add_record)/ })).not.toBeInTheDocument();

    await user.click(cellOf(rowOf("Carrots"), VEGETABLES_S_COLUMN));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(api.bulkUpsert).not.toHaveBeenCalled();
  });
});
