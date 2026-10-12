/**
 * PlanningShareContentLongTermBase: the long-term share-content plan of one
 * share option and year. Each row is one article, unit and size with its
 * delivery weeks, a per-share amount for every share size, the total the season
 * needs and, for a bought-in article, its seller.
 *
 * Rendered the way the office reaches it: through PlanningShareContentPage on
 * the planning routes, which takes the share option from the URL and reads from
 * the option's share type whether it is planned in detail (which offers the
 * target-total mode) and whether it is an additional share (which titles the
 * article column generically). The real EditableTable, column hooks, year
 * selector and add-article entry render; the generated commissioning client is
 * the mocking boundary, its list hooks real TanStack queries around spies that
 * answer from an in-memory server. The per-week planner and the new-article
 * dialog are stubs.
 *
 * The clock is frozen on Monday 5 October 2026: the page opens on 2026, 2025 is
 * a past season and read-only, 2027 lies ahead.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareType } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

import {
  APPLES,
  ARTICLES,
  article,
  CARROTS,
  CARROTS_2025,
  HARVEST,
  HARVEST_SHARE_TYPE,
  HONEY,
  HONEY_SHARE_TYPE,
  KOHLRABI,
  planRow,
  type PlanRow,
  SELLERS,
  SUBSCRIBERS,
  VARIATIONS,
} from "./planningShareContentLongTerm.fixtures";

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
  // Founded in 2024, so the year selector can step back into past seasons.
  const tenant = makeUseTenantMock({
    tenant: { created_at: "2024-02-01T09:00:00Z" },
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
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
  shareTypes: vi.fn(), variations: vi.fn(), shareArticles: vi.fn(), sellers: vi.fn(),
  planList: vi.fn(), subscriberCounts: vi.fn(), create: vi.fn(), update: vi.fn(), destroy: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  type Options = { query?: { enabled?: boolean } };
  const listKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const useListQuery = (
    path: string,
    params: unknown,
    fetch: (params: unknown) => unknown,
    options?: Options,
  ) =>
    useQuery({
      queryKey: listKey(path, params),
      queryFn: () => fetch(params),
      enabled: options?.query?.enabled,
    });
  return {
    useCommissioningShareTypesList: (params: unknown) =>
      useListQuery("share_types", params, api.shareTypes),
    useCommissioningShareTypeVariationsList: (params: unknown, options?: Options) =>
      useListQuery("share_type_variations", params, api.variations, options),
    useCommissioningShareArticlesList: (params: unknown) =>
      useListQuery("share_articles", params, api.shareArticles),
    getCommissioningShareArticlesListQueryKey: (params?: unknown) =>
      listKey("share_articles", params),
    useCommissioningResellersList: (params: unknown) =>
      useListQuery("resellers", params, api.sellers),
    getCommissioningDefaultShareContentsBulkListListQueryKey: (params?: unknown) =>
      listKey("default_share_contents/bulk_list", params),
    useCommissioningDefaultShareContentsBulkListList: (params: unknown) =>
      useListQuery("default_share_contents/bulk_list", params, api.planList),
    useCommissioningDefaultShareContentsSubscriberCountsRetrieve: (params: unknown, options?: Options) =>
      useListQuery("default_share_contents/subscriber_counts", params, api.subscriberCounts, options),
    commissioningDefaultShareContentsBulkCreateCreate: (payload: unknown) => api.create(payload),
    commissioningDefaultShareContentsBulkUpdatePartialUpdate: (id: string, payload: unknown) =>
      api.update(id, payload),
    commissioningDefaultShareContentsBulkDeleteDestroy: (id: string) => api.destroy(id),
  };
});

// The props the new-article dialog received on its last render.
type ArticleDialogProps = {
  isOpen: boolean;
  defaultValues?: Record<string, unknown>;
  onSuccess: (saved: Record<string, unknown>) => void;
};
const articleDialog = vi.hoisted(() => ({ props: null as ArticleDialogProps | null }));
vi.mock("@features/commissioning/modals", () => ({
  ShareArticleModal: (props: ArticleDialogProps) => {
    articleDialog.props = props;
    return props.isOpen ? <div role="dialog" aria-label="commissioning.add_share_article" /> : null;
  },
}));

vi.mock("../PlanningShareContentBase", () => ({
  default: () => <div data-testid="per-week-planner" />,
}));

// Imported under the frozen clock (in beforeAll below), so nothing the page or
// its imports read from the clock while loading depends on the real date.
type PlanningPage = (typeof import("../PlanningShareContentPage"))["default"];
let PlanningShareContentPage: PlanningPage;

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);
// What the server currently holds; the requests answer from it.
let serverPlans: PlanRow[] = [];
let serverShareTypes: ShareType[] = [];

/** Saves a slot the way the backend does: an update keeps the year, article,
 *  unit and size its id names. */
function saveSlot(id: string | null, payload: Record<string, unknown>): PlanRow {
  const [year, shareArticle, unit, size] = id
    ? id.split("_")
    : [payload.year, payload.share_article, payload.unit, payload.size].map(String);
  const amounts = Object.fromEntries(
    Object.entries(payload)
      .filter(([key]) => key.startsWith("amount_"))
      .map(([key, value]) => [key, Number(value).toFixed(3)]),
  );
  const row = planRow({
    ...amounts,
    year: Number(year), share_article: shareArticle, unit, size,
    share_option: String(payload.share_option),
    range_1: Number(payload.range_1), range_2: Number(payload.range_2),
    only_odd_weeks: Boolean(payload.only_odd_weeks),
    only_even_weeks: Boolean(payload.only_even_weeks),
    only_every_three_weeks: Boolean(payload.only_every_three_weeks),
    note: (payload.note as string | null) || null,
    seller: (payload.seller as string | null) ?? null,
  });
  serverPlans = [row, ...serverPlans.filter((stored) => stored.id !== row.id)];
  return row;
}

const serverError = (message: string) =>
  Object.assign(new Error(message), {
    isAxiosError: true,
    response: { status: 400, data: { code: "validation_error", message } },
  });

// ── Helpers ─────────────────────────────────────────────────────────────────

const ARTICLE = /commissioning\.vegetables_and_fruits/;
const SMALL = "commissioning.S";
const LARGE = "commissioning.L";
const FROM = "commissioning.from";
const UNTIL = "commissioning.until";
const ONLY_ODD = "commissioning.only_odd_weeks";
const ONLY_EVEN = "commissioning.only_even_weeks";
const SELLER = "commissioning.seller";
const TARGET = "commissioning.planning_long_term.target_total";
const MODE_TOTAL = "commissioning.planning_long_term.mode_total";
const ADD_ROW = /table\.add_record/;
const ADD_ARTICLE = /commissioning\.add_share_article/;

function renderPlanner({
  slug = "harvest-shares",
  mode = "long-term",
}: { slug?: string; mode?: "complex" | "long-term" } = {}) {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const path = `/commissioning/planning/${slug}${mode === "long-term" ? "/long-term" : ""}`;
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/commissioning/planning/:slug" element={profiler.wrap(<PlanningShareContentPage mode="complex" />)} />
          <Route path="/commissioning/planning/:slug/long-term" element={profiler.wrap(<PlanningShareContentPage mode="long-term" />)} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { profiler };
}

function tableBody(): HTMLElement {
  const body = document.querySelector<HTMLElement>(".ant-table-tbody");
  if (!body) throw new Error("The planning table is not rendered");
  return body;
}

function rowOf(articleName: string): HTMLElement {
  const row = within(tableBody()).getByText(articleName).closest("tr");
  if (!row) throw new Error(`No planning row shows ${articleName}`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

const bodyRows = () => Array.from(tableBody().querySelectorAll<HTMLElement>("tr.ant-table-row"));

/** The blocks the row's timeline draws, one per delivery week. */
const timelineBlocks = (row: HTMLElement) =>
  Array.from(row.querySelectorAll<HTMLElement>("div")).filter(
    (block) => block.style.position === "absolute" && block.style.left !== "",
  );

const field = (label: string) => within(editingRow()).getByLabelText(label);
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const isSpinning = () => document.querySelector(".ant-table-wrapper .ant-spin-spinning") !== null;
const button = (name: string | RegExp) => screen.getByRole("button", { name });

async function pickOption(combobox: HTMLElement, label: string) {
  await userEvent.click(combobox);
  const option = await waitFor(() => {
    const match = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => item.getAttribute("title") === label);
    if (!match) throw new Error(`No option ${label} is offered`);
    return match;
  });
  await userEvent.click(option);
}

async function pickArticle(name: string) {
  await pickOption(within(editingRow()).getByRole("combobox", { name: ARTICLE }), name);
}

async function typeInto(label: string, text: string) {
  await userEvent.clear(field(label));
  await userEvent.type(field(label), text);
}

const save = () => userEvent.click(button("table.save"));

async function deleteRow(articleName: string) {
  await userEvent.click(within(rowOf(articleName)).getByRole("button", { name: "table.delete" }));
  await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function loaded() {
  await within(await screen.findByRole("table")).findByText("Carrots");
}

/** Opens the planner on 2026 and starts a new row. */
async function plannerWithNewRow() {
  renderPlanner();
  await loaded();
  await userEvent.click(button(ADD_ROW));
}

/** Opens the planner in the target-total mode with a new row for ``name``
 *  planned over weeks 20 to 29. */
async function targetTotalRow(name: string) {
  renderPlanner();
  await loaded();
  await userEvent.click(button(MODE_TOTAL));
  await screen.findByRole("columnheader", { name: TARGET });
  await waitFor(() => expect(api.subscriberCounts).toHaveBeenCalled());
  await userEvent.click(button(ADD_ROW));
  await pickArticle(name);
  await typeInto(FROM, "20");
  await typeInto(UNTIL, "29");
}

/** Waits until the row of ``articleName`` shows ``text``. */
const rowShows = (articleName: string, text: string) =>
  waitFor(() => expect(within(rowOf(articleName)).getByText(text)).toBeInTheDocument());

const lastPayload = (spy: typeof api.create) =>
  spy.mock.calls[spy.mock.calls.length - 1].at(-1) as Record<string, unknown>;

beforeAll(async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  ({ default: PlanningShareContentPage } = await import("../PlanningShareContentPage"));
}, 60_000);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  auth.roles = ["office"];
  articleDialog.props = null;
  serverPlans = [CARROTS, APPLES, KOHLRABI, CARROTS_2025];
  serverShareTypes = [HARVEST_SHARE_TYPE, HONEY_SHARE_TYPE];
  type Filter = { share_option?: string; year?: number };
  api.shareTypes.mockReset().mockImplementation(async ({ share_option }: Filter) =>
    serverShareTypes.filter((type) => type.share_option === share_option),
  );
  api.variations.mockReset().mockImplementation(async ({ share_option }: Filter) =>
    share_option === HARVEST
      ? VARIATIONS
      : [{ id: "var-jar", size: "ONE_SIZE", share_type: "st-HONEY_SHARE", valid_from: "2026-01-05" }],
  );
  api.shareArticles.mockReset().mockImplementation(async ({ share_option }: Filter) =>
    ARTICLES.filter((item) => !share_option || item.share_option_list?.includes(share_option)),
  );
  api.sellers.mockReset().mockResolvedValue(SELLERS);
  api.planList.mockReset().mockImplementation(async ({ year, share_option }: Filter) =>
    serverPlans.filter((row) => row.year === year && row.share_option === share_option),
  );
  api.subscriberCounts.mockReset().mockResolvedValue(
    Object.fromEntries(Object.entries(SUBSCRIBERS).map(([id, count]) => [id, String(count)])),
  );
  api.create.mockReset().mockImplementation(async (payload: Record<string, unknown>) =>
    saveSlot(null, payload),
  );
  api.update.mockReset().mockImplementation(async (id: string, payload: Record<string, unknown>) =>
    saveSlot(id, payload),
  );
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    serverPlans = serverPlans.filter((row) => row.id !== id);
    return { message: "Deleted", deleted_count: 2 };
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── The plan and its figures ────────────────────────────────────────────────

describe("PlanningShareContentLongTermBase plan", () => {
  it("opens on this year's plan of the share option the route names", async () => {
    renderPlanner();
    await loaded();

    expect(
      screen.getByRole("heading", { name: "commissioning.planning_long_term_harvest_share_vegs" }),
    ).toBeInTheDocument();
    expect(api.planList).toHaveBeenCalledWith({ year: 2026, share_option: HARVEST });
    expect(bodyRows()).toHaveLength(3);
    expect(screen.getByText("explainers.planning_long_term_harvest_shares")).toBeInTheDocument();
  });

  it("shows a row's weeks, per-share amounts by size and the total the season needs", async () => {
    renderPlanner();
    await loaded();

    const carrots = rowOf("Carrots");
    expect(within(carrots).getByText("commissioning.units.kg")).toBeInTheDocument();
    expect(within(carrots).getByText("20")).toBeInTheDocument();
    expect(within(carrots).getByText("29")).toBeInTheDocument();
    expect(within(carrots).getByText("3,000")).toBeInTheDocument();
    expect(within(carrots).getByText("5,500")).toBeInTheDocument();
    expect(within(carrots).getByText("1.150 commissioning.units.kg")).toBeInTheDocument();
    expect(within(carrots).getByText("Sow under fleece")).toBeInTheDocument();
  });

  it("shows piece-counted amounts and totals in whole pieces", async () => {
    renderPlanner();
    await loaded();

    const kohlrabi = rowOf("Kohlrabi");
    expect(within(kohlrabi).getByText("4")).toBeInTheDocument();
    expect(within(kohlrabi).getByText("6")).toBeInTheDocument();
    expect(within(kohlrabi).getByText("560 commissioning.units.pcs")).toBeInTheDocument();
  });

  it("shows a fractional piece amount as planned", async () => {
    // Twelve weeks of 20 × 1.5 + 10 × 2 lettuces: 600 pieces.
    serverPlans = [
      CARROTS,
      planRow({
        share_article: "art-lettuce", unit: "PCS", range_1: 20, range_2: 31,
        "amount_var-small": "1.500", "amount_var-large": "2.000",
      }),
    ];
    renderPlanner();
    await loaded();

    const lettuce = rowOf("Lettuce");
    expect(within(lettuce).getByText("1,5")).toBeInTheDocument();
    expect(within(lettuce).getByText("2")).toBeInTheDocument();
    expect(within(lettuce).getByText("600 commissioning.units.pcs")).toBeInTheDocument();
  });

  it("opens on the year of the day the page is opened, not the day it was loaded", async () => {
    vi.setSystemTime(new Date(2027, 0, 4, 12, 0));
    serverPlans = [{ ...CARROTS, year: 2027 } as PlanRow];
    renderPlanner();
    await loaded();

    expect(api.planList).toHaveBeenCalledWith({ year: 2027, share_option: HARVEST });
    expect(api.planList).not.toHaveBeenCalledWith({ year: 2026, share_option: HARVEST });
  });

  it("names the seller of a bought-in article", async () => {
    renderPlanner();
    await loaded();

    expect(within(rowOf("Apples")).getByText("Orchard Co")).toBeInTheDocument();
    expect(within(rowOf("Apples")).getByText("300 commissioning.units.kg")).toBeInTheDocument();
  });

  it("gives every physical share size of the option its own amount column", async () => {
    renderPlanner();
    await loaded();

    expect(screen.getByRole("columnheader", { name: "commissioning.amount" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: SMALL })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: LARGE })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "commissioning.needed_amount" })).toBeInTheDocument();
    // The sizes the share option offers late in the planned year.
    expect(api.variations).toHaveBeenCalledWith({
      physical: true,
      active_at_date: "2026-12-12",
      share_option: HARVEST,
    });
  });

  it("marks each delivery week of a row on its timeline", async () => {
    renderPlanner();
    await loaded();

    // Weeks 20 to 29; the even weeks 36 to 44; every third week from 24 to 35.
    expect(timelineBlocks(rowOf("Carrots"))).toHaveLength(10);
    expect(timelineBlocks(rowOf("Apples"))).toHaveLength(5);
    expect(timelineBlocks(rowOf("Kohlrabi"))).toHaveLength(4);
  });

  it("shows a spinner in the table while the plan loads", async () => {
    let answer: (rows: PlanRow[]) => void = () => {};
    api.planList.mockImplementation(() => new Promise<PlanRow[]>((resolve) => (answer = resolve)));
    renderPlanner();

    await screen.findByRole("table");
    await waitFor(() => expect(api.planList).toHaveBeenCalled());
    expect(isSpinning()).toBe(true);

    answer([CARROTS]);

    await within(tableBody()).findByText("Carrots");
    await waitFor(() => expect(isSpinning()).toBe(false));
  });

  it("says so when the year has no plan yet", async () => {
    serverPlans = [];
    renderPlanner();

    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderPlanner();
    await loaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Seasons and who may plan ────────────────────────────────────────────────

describe("PlanningShareContentLongTermBase seasons and roles", () => {
  /** No way to add, change or remove a row. */
  async function expectReadOnly() {
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();

    await userEvent.click(within(rowOf("Carrots")).getByText("commissioning.units.kg"));
    await userEvent.keyboard("+");

    expect(within(tableBody()).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(tableBody()).queryByRole("combobox")).not.toBeInTheDocument();
  }

  it("loads the plan of the season the office steps back to", async () => {
    renderPlanner();
    await loaded();

    await userEvent.click(button("common.previous"));

    expect(await within(tableBody()).findByText("1.040 commissioning.units.kg")).toBeInTheDocument();
    expect(api.planList).toHaveBeenLastCalledWith({ year: 2025, share_option: HARVEST });
    expect(bodyRows()).toHaveLength(1);
  });

  it("shows a past season's plan read-only", async () => {
    renderPlanner();
    await loaded();
    await userEvent.click(button("common.previous"));
    await within(tableBody()).findByText("1.040 commissioning.units.kg");

    await expectReadOnly();
    expect(button(ADD_ARTICLE)).toBeDisabled();
  });

  it("lets the office plan next season ahead", async () => {
    renderPlanner();
    await loaded();

    await userEvent.click(button("common.next"));

    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    expect(api.planList).toHaveBeenLastCalledWith({ year: 2027, share_option: HARVEST });
    expect(button(ADD_ROW)).toBeInTheDocument();
  });

  it("shows the plan read-only to a user without office rights", async () => {
    auth.roles = ["staff"];
    renderPlanner();
    await loaded();

    await expectReadOnly();
  });

  it("lets an admin plan like the office", async () => {
    auth.roles = ["admin"];
    renderPlanner();
    await loaded();

    expect(button(ADD_ROW)).toBeInTheDocument();
    expect(within(rowOf("Carrots")).getByRole("button", { name: "table.edit" })).toBeInTheDocument();
  });
});

// ── Planning a new article ──────────────────────────────────────────────────

describe("PlanningShareContentLongTermBase new row", () => {
  it("plans an article for the season and shows the total the server works out", async () => {
    await plannerWithNewRow();

    await pickArticle("Beetroot");
    // The unit comes from the article's default unit.
    expect(within(editingRow()).getByTitle("commissioning.units.kg")).toBeInTheDocument();
    await typeInto(FROM, "30");
    await typeInto(UNTIL, "39");
    await typeInto(SMALL, "0,5");
    await typeInto(LARGE, "1");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const payload = lastPayload(api.create);
    expect(payload).toEqual(
      expect.objectContaining({
        year: 2026, share_option: HARVEST, share_article: "art-beet", unit: "KG",
        // The tenant hides the size column; a new row plans the medium size.
        size: "M",
        range_1: "30", range_2: "39",
        only_odd_weeks: false, only_even_weeks: false, only_every_three_weeks: false,
        seller: null, "amount_var-small": "0.5", "amount_var-large": "1",
      }),
    );
    expect(payload).not.toHaveProperty("needed_amount");
    // 20 × 0.5 kg + 10 × 1 kg a week for ten weeks.
    await rowShows("Beetroot", "200 commissioning.units.kg");
    expect(within(rowOf("Beetroot")).getByText("0,500")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
  });

  it("offers only the articles of this share option", async () => {
    await plannerWithNewRow();

    await userEvent.click(within(editingRow()).getByRole("combobox", { name: ARTICLE }));

    const offered = await waitFor(() => {
      const titles = Array.from(
        document.querySelectorAll(".ant-select-dropdown .ant-select-item-option"),
      ).map((option) => option.getAttribute("title"));
      expect(titles).toContain("Carrots");
      return titles;
    });
    expect(offered).toEqual(
      expect.arrayContaining(["Apples", "Kohlrabi", "Beetroot", "Pears", "Lettuce"]),
    );
    expect(offered).not.toContain("Forest honey");
  });

  it("offers an article added from the new-article dialog right away", async () => {
    renderPlanner();
    await loaded();
    const fennel = article("art-fennel", "Fennel", "KG");
    api.shareArticles.mockImplementation(async ({ share_option }: { share_option?: string }) =>
      [...ARTICLES, fennel].filter(
        (item) => !share_option || item.share_option_list?.includes(share_option),
      ),
    );

    await userEvent.click(button(ADD_ARTICLE));
    act(() => articleDialog.props?.onSuccess({ id: "art-fennel", name: "Fennel" }));
    await userEvent.click(button(ADD_ROW));
    await pickArticle("Fennel");

    expect(within(editingRow()).getAllByText("Fennel")).not.toHaveLength(0);
  });

  it("takes a seller only for a bought-in article", async () => {
    await plannerWithNewRow();
    const sellerSelect = () => within(editingRow()).queryByRole("combobox", { name: SELLER });

    await pickArticle("Beetroot");
    expect(sellerSelect()).not.toBeInTheDocument();

    await pickArticle("Pears");
    await pickOption(sellerSelect()!, "Orchard Co");
    await typeInto(FROM, "38");
    await typeInto(UNTIL, "40");
    await typeInto(SMALL, "1");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(lastPayload(api.create)).toEqual(
      expect.objectContaining({ share_article: "art-pear", seller: "seller-orchard" }),
    );
    await within(tableBody()).findByText("Pears");
    expect(within(rowOf("Pears")).getByText("Orchard Co")).toBeInTheDocument();
  });

  it("keeps only one week pattern ticked", async () => {
    await plannerWithNewRow();
    const odd = field(ONLY_ODD);
    const even = field(ONLY_EVEN);
    const everyThird = field("commissioning.only_every_three_weeks");

    await userEvent.click(odd);
    expect(odd).toBeChecked();

    await userEvent.click(even);
    expect(even).toBeChecked();
    expect(odd).not.toBeChecked();

    await userEvent.click(everyThird);
    expect(everyThird).toBeChecked();
    expect(even).not.toBeChecked();

    await userEvent.click(odd);
    expect(odd).toBeChecked();
    expect(everyThird).not.toBeChecked();
  });

  it("refuses a second row for an article, unit and size already planned", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await plannerWithNewRow();

    await pickArticle("Carrots");
    await typeInto(FROM, "40");
    await typeInto(UNTIL, "44");
    await save();

    expect(
      await screen.findByText(
        "validation.unique.share_article_unit_size_must_be_unique — table.save_failed_hint",
      ),
    ).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
    expect(editingRow()).toBeInTheDocument();
  });

  it("plans an article again in another size when the tenant plans by size", async () => {
    tenantSettings.values = { show_size_column: true };
    await plannerWithNewRow();

    await pickArticle("Carrots");
    expect(within(editingRow()).getByTitle("commissioning.medium")).toBeInTheDocument();
    await pickOption(within(editingRow()).getByRole("combobox", { name: "commissioning.size" }), "commissioning.large");
    await typeInto(FROM, "40");
    await typeInto(UNTIL, "44");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(lastPayload(api.create)).toEqual(
      expect.objectContaining({ share_article: "art-carrot", unit: "KG", size: "L" }),
    );
    await waitFor(() => expect(within(tableBody()).getAllByText("Carrots")).toHaveLength(2));
  });

  it("needs the article and both weeks before it saves", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await plannerWithNewRow();

    await save();

    expect(
      await screen.findByText("table.save_failed_generic — table.save_failed_hint"),
    ).toBeInTheDocument();
    expect(field(FROM)).toHaveAttribute("aria-invalid", "true");
    expect(field(UNTIL)).toHaveAttribute("aria-invalid", "true");
    expect(within(editingRow()).getByRole("combobox", { name: ARTICLE })).toHaveAttribute("aria-invalid", "true");
    expect(api.create).not.toHaveBeenCalled();
  });

  it("starts a new row when the office presses +", async () => {
    renderPlanner();
    await loaded();

    await userEvent.keyboard("+");

    expect(within(editingRow()).getByRole("combobox", { name: ARTICLE })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
  });

  it("keeps the row open and shows why when the server refuses it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.create.mockRejectedValue(serverError("The share article is not active."));
    await plannerWithNewRow();

    await pickArticle("Beetroot");
    await typeInto(FROM, "30");
    await typeInto(UNTIL, "39");
    await save();

    expect(await screen.findByText("table.save_failed_title")).toBeInTheDocument();
    expect(
      screen.getByText("The share article is not active. — table.save_failed_hint"),
    ).toBeInTheDocument();
    expect(field(FROM)).toHaveValue("30");
    expect(bodyRows()).toHaveLength(4);
  });
});

// ── Changing and removing planned articles ──────────────────────────────────

describe("PlanningShareContentLongTermBase planned rows", () => {
  it("opens a row from one of its cells with its article, unit and size locked", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPlanner();
    await loaded();

    await userEvent.click(within(rowOf("Carrots")).getByText("20"));

    const row = editingRow();
    expect(within(row).getByText("Carrots")).toBeInTheDocument();
    // They make up the row's slot; another unit or size is another row.
    for (const name of [ARTICLE, "commissioning.unit", "commissioning.size"]) {
      expect(within(row).queryByRole("combobox", { name })).not.toBeInTheDocument();
    }
    expect(field(FROM)).toHaveValue("20");
    expect(field(SMALL)).toHaveValue("3,000");
    // Carrots are grown on the farm, so there is no seller to pick.
    expect(within(row).queryByRole("combobox", { name: SELLER })).not.toBeInTheDocument();
  });

  it("saves changed amounts for the row's slot and shows the new total", async () => {
    renderPlanner();
    await loaded();

    await userEvent.click(within(rowOf("Carrots")).getByRole("button", { name: "table.edit" }));
    await typeInto(SMALL, "2,5");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "2026_art-carrot_KG_M",
      expect.objectContaining({
        year: 2026, share_option: HARVEST, share_article: "art-carrot", unit: "KG", size: "M",
        range_1: 20, range_2: 29, note: "Sow under fleece", seller: null,
        "amount_var-small": "2.5", "amount_var-large": "5.500",
      }),
    );
    // 20 × 2.5 kg + 10 × 5.5 kg a week for ten weeks.
    await rowShows("Carrots", "1.050 commissioning.units.kg");
    expect(within(rowOf("Carrots")).getByText("2,500")).toBeInTheDocument();
  });

  it("moves a row to the odd weeks and shows the smaller total and timeline", async () => {
    renderPlanner();
    await loaded();

    await userEvent.click(within(rowOf("Carrots")).getByText("29"));
    await userEvent.click(field(ONLY_ODD));
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(lastPayload(api.update)).toEqual(
      expect.objectContaining({ only_odd_weeks: true, only_even_weeks: false }),
    );
    // Weeks 21, 23, 25, 27 and 29 only.
    await rowShows("Carrots", "575 commissioning.units.kg");
    expect(timelineBlocks(rowOf("Carrots"))).toHaveLength(5);
  });

  it("removes a row after confirmation and reloads the plan", async () => {
    renderPlanner();
    await loaded();

    await deleteRow("Carrots");

    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith("2026_art-carrot_KG_M"));
    await waitFor(() => expect(within(tableBody()).queryByText("Carrots")).not.toBeInTheDocument());
    await waitFor(() => expect(api.planList).toHaveBeenCalledTimes(2));
    expect(bodyRows()).toHaveLength(2);
  });

  it("keeps a row the server refuses to remove and shows why", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.destroy.mockRejectedValue(serverError("Share article not found."));
    renderPlanner();
    await loaded();

    await deleteRow("Carrots");

    expect(await screen.findByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("Share article not found.")).toBeInTheDocument();
    expect(rowOf("Carrots")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);
  });
});

// ── Planning from a target total ────────────────────────────────────────────

describe("PlanningShareContentLongTermBase target total", () => {
  it("adds the target column and loads the subscriber counts once the office switches to it", async () => {
    renderPlanner();
    await loaded();
    expect(button("commissioning.planning_long_term.mode_per_share")).toHaveAttribute("aria-pressed", "true");
    expect(api.subscriberCounts).not.toHaveBeenCalled();

    await userEvent.click(button(MODE_TOTAL));

    expect(await screen.findByRole("columnheader", { name: TARGET })).toBeInTheDocument();
    expect(button(MODE_TOTAL)).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("columnheader", { name: "commissioning.planning_long_term.actual_total" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(api.subscriberCounts).toHaveBeenCalledWith({ year: 2026, share_option: HARVEST }),
    );
    // A saved row keeps the total the server worked out.
    await rowShows("Carrots", "1.150 commissioning.units.kg");
  });

  it("splits a target total over the sizes by weight and previews what it hands out", async () => {
    await targetTotalRow("Beetroot");

    await typeInto(TARGET, "999");

    // 99.9 kg a week over 20 small (2 kg) and 10 large (4 kg) shares, floored
    // to 100 g, hands out 970 of the 999 kg.
    expect(field(SMALL)).toHaveValue("2,4");
    expect(field(LARGE)).toHaveValue("4,9");
    expect(within(editingRow()).getByText("970 commissioning.units.kg")).toBeInTheDocument();

    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const payload = lastPayload(api.create);
    expect(payload).toEqual(
      expect.objectContaining({ share_article: "art-beet", "amount_var-small": 2.4, "amount_var-large": 4.9 }),
    );
    expect(payload).not.toHaveProperty("_target_total");
    await rowShows("Beetroot", "970 commissioning.units.kg");
  });

  it("splits the target again when the week pattern changes", async () => {
    await targetTotalRow("Beetroot");
    await typeInto(TARGET, "999");

    await userEvent.click(field(ONLY_EVEN));

    // The five even weeks now carry the whole 999 kg.
    expect(field(SMALL)).toHaveValue("4,9");
    expect(field(LARGE)).toHaveValue("9,9");
    expect(within(editingRow()).getByText("985 commissioning.units.kg")).toBeInTheDocument();
  });

  it("splits the target again when another article changes the unit to pieces", async () => {
    await targetTotalRow("Beetroot");
    await typeInto(TARGET, "1000");
    expect(field(SMALL)).toHaveValue("2,5");

    await pickArticle("Lettuce");

    expect(field(SMALL)).toHaveValue("2");
    expect(field(LARGE)).toHaveValue("5");
    expect(within(editingRow()).getByText("900 commissioning.units.pcs")).toBeInTheDocument();
  });

  it("suggests whole pieces for an article counted in pieces", async () => {
    await targetTotalRow("Lettuce");

    await typeInto(TARGET, "1000");

    expect(field(SMALL)).toHaveValue("2");
    expect(field(LARGE)).toHaveValue("5");
    expect(within(editingRow()).getByText("900 commissioning.units.pcs")).toBeInTheDocument();
  });
});

// ── Share options and the add-article entry ─────────────────────────────────

describe("PlanningShareContentLongTermBase share options", () => {
  it("plans an additional share with a generic article column and no target total", async () => {
    serverPlans = [
      planRow({
        share_option: HONEY, share_article: "art-honey", unit: "PCS", range_1: 10, range_2: 40,
        "amount_var-jar": "1.000",
      }),
    ];
    renderPlanner({ slug: "honey-shares" });

    await within(await screen.findByRole("table")).findByText("Forest honey");
    expect(
      screen.getByRole("heading", { name: "commissioning.planning_additional_honey_shares" }),
    ).toBeInTheDocument();
    expect(api.planList).toHaveBeenCalledWith({ year: 2026, share_option: HONEY });
    expect(screen.getByRole("columnheader", { name: /commissioning\.share_articles/ })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: ARTICLE })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "commissioning.ONE_SIZE" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: MODE_TOTAL })).not.toBeInTheDocument();
  });

  it("shows the long-term plan on the per-week route of a share type not planned per week", async () => {
    serverShareTypes = [{ ...HARVEST_SHARE_TYPE, needs_complex_planning: false }];
    renderPlanner({ mode: "complex" });
    await loaded();

    expect(
      screen.getByRole("heading", { name: "commissioning.planning_long_term_harvest_share_vegs" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("per-week-planner")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: MODE_TOTAL })).not.toBeInTheDocument();
  });

  it("opens the new-article dialog preset to a bought-in article", async () => {
    renderPlanner();
    await loaded();

    await userEvent.click(button(ADD_ARTICLE));

    expect(screen.getByRole("dialog", { name: "commissioning.add_share_article" })).toBeInTheDocument();
    expect(articleDialog.props?.defaultValues).toEqual({ is_purchased: true });
  });
});
