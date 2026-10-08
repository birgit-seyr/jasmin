/**
 * CommissioningListPacking: everything to pack for one delivery day, summed
 * over every delivery station. Every share option the farm packs, in bulk or
 * in boxes, gets a table of its own that lists each article needed that day
 * with its unit, size and total amount. Rendered through the real week and day
 * selectors, EditableTable, column hooks and PDF download button. The
 * generated commissioning client is the mocking boundary: its hooks are real
 * TanStack queries around spies that answer from an in-memory farm. The PDF
 * library, the PDF template and the browser download are stubbed, so no real
 * PDF is rendered.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The week state reads "today" when
 * the page mounts.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ShareType,
  ShareTypeVariation,
  SharesDeliveryDay,
} from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// The canonical mock with one `t` for every render, as react-i18next keeps it.
// It appends an interpolated `number`, so the weeks read "… 41".
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => {
    if (typeof fallback === "string") return fallback;
    const number = (fallback as { number?: unknown } | undefined)?.number;
    return number === undefined ? key : `${key} ${String(number)}`;
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
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

const api = vi.hoisted(() => ({
  shareTypes: vi.fn(),
  variations: vi.fn(),
  deliveryDays: vi.fn(),
  shareArticles: vi.fn(),
  planning: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(
      params?: unknown,
      options?: { query?: { enabled?: boolean } },
    ) {
      return useQuery({
        queryKey: queryKey(path, params),
        queryFn: async () => request(params),
        enabled: options?.query?.enabled,
      });
    };
  return {
    useCommissioningShareTypesList: queryHook("share_types", api.shareTypes),
    // The variations of every share type are fetched side by side from the
    // generated query options.
    getCommissioningShareTypeVariationsListQueryKey: (params?: unknown) =>
      queryKey("share_type_variations", params),
    getCommissioningShareTypeVariationsListQueryOptions: (params?: unknown) => ({
      queryKey: queryKey("share_type_variations", params),
      queryFn: async () => api.variations(params),
    }),
    commissioningShareTypeVariationsList: (params?: unknown) => api.variations(params),
    useCommissioningSharesDeliveryDaysList: queryHook(
      "shares_delivery_days",
      api.deliveryDays,
    ),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
    useCommissioningHarvestSharePlanningList: queryHook(
      "harvest_share_planning",
      api.planning,
    ),
  };
});

// The page only needs its download button; the barrel would also load every
// other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  CommissioningListPackingPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/CommissioningListPackingPDFGenerator")
  ).default,
}));
vi.mock("@features/commissioning/pdfs/exports/CommissioningListPackingPDF", () => ({
  default: function CommissioningListPackingPDF() {
    return null;
  },
}));

// The documents handed to the PDF renderer and the files saved, in order.
const printed = vi.hoisted(() => ({
  documents: [] as { template: string; props: Record<string, unknown> }[],
  files: [] as string[],
}));
// Partial: other commissioning modules register fonts with the real library
// when they load.
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

import CommissioningListPacking from "../CommissioningListPacking";
import {
  deliveryDay,
  FRUIT,
  FRUIT_SHARE,
  plan,
  planned,
  planningRequest,
  type PlanningRow,
  shareType,
  variation,
  VEGETABLE_SHARE,
  VEGETABLES,
  WEEK_40_VEGETABLES,
  WEEK_41_FRUIT,
  WEEK_41_VEGETABLES,
  WEEK_42_VEGETABLES,
} from "./commissioningListPacking.fixtures";
import {
  arrow,
  choose,
  optionsOf,
  pending,
  selectNamed,
  shownIn,
} from "./commissioningListPacking.helpers";

// ── Fixtures ────────────────────────────────────────────────────────────────

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  shareTypes: ShareType[];
  variations: ShareTypeVariation[];
  deliveryDays: SharesDeliveryDay[];
  plans: Record<string, PlanningRow[]>;
};

type PlanningParams = { year: number; delivery_week: number; share_option: string };

const answerFromFarm = async ({ year, delivery_week, share_option }: PlanningParams) => [
  ...(farm.plans[plan(share_option, { year, week: delivery_week })] ?? []),
];

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<CommissioningListPacking />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const TITLE = "commissioning.commissioning_list_packing";
const DAY = "placeholder.shares_delivery_day_selector";
const WEEK = "common.week";
const YEAR = "common.year";
const DOWNLOAD = /download\.commissioning_list_packing$/;
const EXPLAINER = "explainers.commissioning_lists_packing";
const VEGETABLES_HEADING = "commissioning.share_option.HARVEST_SHARE";
const FRUIT_HEADING = "commissioning.share_option.HARVEST_SHARE_FRUIT";
const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const SIZE = "commissioning.size";
const TOTAL = "commissioning.total_amount";
const NO_DATA = "table.no_data";
const LOAD_FAILED = "commissioning.share_option_load_failed";
const KG = "commissioning.units.kg";
const PIECES = "commissioning.units.pcs";
const BUNCH = "commissioning.units.bunch";
const SMALL = "commissioning.small";
const MEDIUM = "commissioning.medium";
const LARGE = "commissioning.large";

const dayLabel = (date: string) => `commissioning.delivery_day ${date}`;
const TUESDAY_LABEL = dayLabel("Tuesday, 06.10.2026");
const FRIDAY_LABEL = dayLabel("Friday, 09.10.2026");

/** Every share option's table, top to bottom. */
const tables = () => Array.from(document.querySelectorAll<HTMLElement>("section"));

/** The share options heading the tables, top to bottom. */
const headings = () =>
  screen.queryAllByRole("heading", { level: 3 }).map((heading) => heading.textContent ?? "");

/** The table under a share option's heading. */
function tableOf(heading: string): HTMLElement {
  const table = screen.getByRole("heading", { level: 3, name: heading }).closest("section");
  if (!table) throw new Error(`No table under ${heading}`);
  return table;
}

const textsOf = (cells: Iterable<Element>) =>
  Array.from(cells, (cell) => (cell.textContent ?? "").replace(/\s+/g, " ").trim());

const columnsOf = (table: HTMLElement) => textsOf(table.querySelectorAll(".ant-table-thead th"));

/** The article rows of a table, each as its cells, left to right. */
const rowsOf = (table: HTMLElement) =>
  Array.from(table.querySelectorAll(".ant-table-tbody > tr.ant-table-row"), (row) =>
    textsOf(row.querySelectorAll("td")),
  );

function rowOf(article: string): HTMLElement {
  const row = screen.getByText(article).closest<HTMLElement>("tr");
  if (!row) throw new Error(`No table row shows ${article}`);
  return row;
}

const isBusy = (container: HTMLElement) => container.querySelector('[aria-busy="true"]') !== null;
const anyTableBusy = () => tables().some((table) => isBusy(table));

const downloadButton = () => screen.getByRole("button", { name: DOWNLOAD });

/** The phone card that shows an article. */
function cardOf(article: string): HTMLElement {
  const card = screen.getByText(article).closest<HTMLElement>(".mobile-card-item");
  if (!card) throw new Error(`No card shows ${article}`);
  return card;
}

/** The articles a table shows as phone cards, top to bottom. */
const cardsIn = (table: HTMLElement) =>
  textsOf(table.querySelectorAll(".mobile-card-item .mobile-card-title"));

/** What a phone card lists below its article, as "label: value". */
const detailsOf = (card: HTMLElement) => textsOf(card.querySelectorAll(".mobile-card-detail"));

/** An article row of the printed list; the size only when one is given. */
const onPaper = (name: string, unit: string, total: string, size?: string) =>
  expect.objectContaining({
    share_article_name: name,
    unit_label: unit,
    total_amount_text: total,
    ...(size === undefined ? {} : { size_label: size }),
  });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  printed.documents = [];
  printed.files = [];
  farm = {
    shareTypes: [VEGETABLE_SHARE, FRUIT_SHARE],
    // Vegetables are packed in boxes, fruit in bulk.
    variations: [
      variation("st-veg", "S", "boxes"),
      variation("st-veg", "M", "boxes"),
      variation("st-fruit", "M", "bulk"),
    ],
    deliveryDays: [deliveryDay("day-tue", 1), deliveryDay("day-fri", 4)],
    plans: {
      [plan(VEGETABLES)]: WEEK_41_VEGETABLES,
      [plan(FRUIT)]: WEEK_41_FRUIT,
      [plan(VEGETABLES, { week: 42 })]: WEEK_42_VEGETABLES,
      [plan(VEGETABLES, { week: 40 })]: WEEK_40_VEGETABLES,
    },
  };
  api.shareTypes.mockReset().mockImplementation(async () => [...farm.shareTypes]);
  api.variations
    .mockReset()
    .mockImplementation(async ({ share_type }: { share_type: string }) =>
      farm.variations.filter((each) => each.share_type === share_type),
    );
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.shareArticles.mockReset().mockResolvedValue([]);
  api.planning.mockReset().mockImplementation(answerFromFarm);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("CommissioningListPacking loading", () => {
  it("opens on the week's first delivery day with a table for every share option", async () => {
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeInTheDocument();
    expect(shownIn(selectNamed(YEAR))).toBe("2026");
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 41");
    expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL);
    expect(headings()).toEqual([VEGETABLES_HEADING, FRUIT_HEADING]);
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-10" });
    expect(api.planning).toHaveBeenCalledTimes(2);
    expect(api.planning).toHaveBeenCalledWith(planningRequest(VEGETABLES));
    expect(api.planning).toHaveBeenCalledWith(planningRequest(FRUIT));
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });

  it("shows a spinner over every table and keeps the download disabled while the plans load", async () => {
    const plans = pending<void>();
    api.planning.mockImplementation(async (params: PlanningParams) => {
      await plans.promise;
      return answerFromFarm(params);
    });
    renderPage();

    await waitFor(() => expect(tables()).toHaveLength(2));
    await waitFor(() => expect(tables().every((table) => isBusy(table))).toBe(true));
    expect(tables().map(rowsOf)).toEqual([[], []]);
    expect(downloadButton()).toBeDisabled();

    plans.answer();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.getByText("Apples")).toBeInTheDocument();
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    expect(downloadButton()).toBeEnabled();
  });
});

// ── One table per share option ──────────────────────────────────────────────

describe("CommissioningListPacking share options", () => {
  it("gives every share option packed in bulk or in boxes a table under its own heading", async () => {
    farm.shareTypes = [
      VEGETABLE_SHARE,
      FRUIT_SHARE,
      // No share size of honey is offered, and the eggs belong to no option.
      shareType("st-honey", "Honey", "HONEY_SHARE"),
      shareType("st-eggs", "Eggs", null),
    ];
    farm.variations.push(variation("st-eggs", "M", "boxes"));
    renderPage();
    await screen.findByText("Carrots");

    expect(headings()).toEqual([VEGETABLES_HEADING, FRUIT_HEADING]);
    expect(tables()).toHaveLength(2);
    expect(within(tableOf(VEGETABLES_HEADING)).getByText("Carrots")).toBeInTheDocument();
    expect(within(tableOf(FRUIT_HEADING)).getByText("Apples")).toBeInTheDocument();
    expect(api.planning).toHaveBeenCalledTimes(2);
    expect(api.planning).not.toHaveBeenCalledWith(
      expect.objectContaining({ share_option: "HONEY_SHARE" }),
    );
  });

  it("gives a share option packed partly in bulk and partly in boxes one table, unheaded as the farm's only one", async () => {
    farm.shareTypes = [VEGETABLE_SHARE];
    farm.variations = [variation("st-veg", "S", "bulk"), variation("st-veg", "M", "boxes")];
    renderPage();
    await screen.findByText("Carrots");

    expect(tables()).toHaveLength(1);
    expect(headings()).toEqual([]);
    expect(rowsOf(tables()[0])[0]).toEqual(["Carrots", BUNCH, "18,0"]);
    expect(api.planning).toHaveBeenCalledTimes(1);
    expect(api.planning).toHaveBeenCalledWith(planningRequest(VEGETABLES));
  });

  it("shows no table and offers nothing to download when the farm packs no share option", async () => {
    farm.shareTypes = [shareType("st-honey", "Honey", "HONEY_SHARE")];
    renderPage();

    await waitFor(() => expect(api.variations).toHaveBeenCalled());
    await waitFor(() => expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL));
    await flushMicrotasks();

    expect(tables()).toEqual([]);
    expect(api.planning).not.toHaveBeenCalled();
    expect(downloadButton()).toBeDisabled();
  });
});

// ── The rows ────────────────────────────────────────────────────────────────

describe("CommissioningListPacking rows", () => {
  it("lists each article needed that day with its unit and total amount, in the planned order", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(columnsOf(tableOf(VEGETABLES_HEADING))).toEqual([ARTICLE, UNIT, TOTAL]);
    expect(rowsOf(tableOf(VEGETABLES_HEADING))).toEqual([
      ["Carrots", BUNCH, "18,0"],
      ["Lettuce", PIECES, "30,0"],
      ["Potatoes", KG, "3,00"],
    ]);
    expect(columnsOf(tableOf(FRUIT_HEADING))).toEqual([ARTICLE, UNIT, TOTAL]);
    expect(rowsOf(tableOf(FRUIT_HEADING))).toEqual([["Apples", KG, "30,00"]]);
  });

  it("adds each article's packing buffer to its amount and rounds the total up to whole units", async () => {
    farm.shareTypes = [VEGETABLE_SHARE];
    farm.plans = {
      [plan(VEGETABLES)]: [
        planned("Carrots", "BUNCH", "M", { "day-tue": 12 }, 50),
        planned("Beans", "KG", "M", { "day-tue": 10 }, 25),
        planned("Potatoes", "KG", "M", { "day-tue": "2.500" }),
        planned("Onions", "PCS", "M", { "day-tue": 7 }),
        // A tenth on top of 100 and of 50, exactly 110 and 55.
        planned("Chives", "BUNCH", "M", { "day-tue": 100 }, 10),
        planned("Parsley", "BUNCH", "M", { "day-tue": 50 }, 10),
      ],
    };
    renderPage();
    await screen.findByText("Carrots");

    expect(rowsOf(tables()[0])).toEqual([
      ["Carrots", BUNCH, "18,0"],
      // 12.5 kilos with the buffer.
      ["Beans", KG, "13,00"],
      ["Potatoes", KG, "3,00"],
      ["Onions", PIECES, "7,0"],
      ["Chives", BUNCH, "110,0"],
      ["Parsley", BUNCH, "55,0"],
    ]);
  });

  it("writes the totals on screen and on paper in the farm's number format", async () => {
    tenantSettings.values = { number_locale: "en-US" };
    farm.shareTypes = [VEGETABLE_SHARE];
    farm.plans = {
      [plan(VEGETABLES)]: [
        planned("Potatoes", "KG", "M", { "day-tue": 1250 }),
        planned("Carrots", "BUNCH", "M", { "day-tue": 12 }),
      ],
    };
    renderPage();
    await screen.findByText("Carrots");

    expect(rowsOf(tables()[0])).toEqual([
      ["Potatoes", KG, "1,250.00"],
      ["Carrots", BUNCH, "12.0"],
    ]);

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.documents[0].props.groups).toEqual([
      {
        label: VEGETABLES_HEADING,
        rows: [onPaper("Potatoes", KG, "1,250.00"), onPaper("Carrots", BUNCH, "12.0")],
      },
    ]);
  });

  it("leaves out the articles no share needs that day", async () => {
    farm.shareTypes = [VEGETABLE_SHARE];
    farm.plans = {
      [plan(VEGETABLES)]: [
        planned("Radishes", "BUNCH", "S", { "day-tue": 0 }),
        planned("Carrots", "BUNCH", "M", { "day-tue": 12 }),
        planned("Leeks", "KG", "M", { "day-tue": "0.000" }),
        planned("Kale", "KG", "M", { "day-tue": null }),
        // Planned for Friday only.
        planned("Chard", "KG", "M", { "day-fri": 3 }),
      ],
    };
    renderPage();
    await screen.findByText("Carrots");

    expect(rowsOf(tables()[0])).toEqual([["Carrots", BUNCH, "12,0"]]);
  });

  it("adds the size column, on screen and on paper, when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await screen.findByText("Carrots");

    expect(columnsOf(tableOf(VEGETABLES_HEADING))).toEqual([ARTICLE, UNIT, SIZE, TOTAL]);
    expect(rowsOf(tableOf(VEGETABLES_HEADING))).toEqual([
      ["Carrots", BUNCH, MEDIUM, "18,0"],
      ["Lettuce", PIECES, LARGE, "30,0"],
      ["Potatoes", KG, SMALL, "3,00"],
    ]);

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    const { props } = printed.documents[0];
    expect(props.showSize).toBe(true);
    // The usual medium size goes without a label on paper.
    expect(props.groups).toEqual([
      {
        label: VEGETABLES_HEADING,
        rows: [
          onPaper("Carrots", BUNCH, "18,0", ""),
          onPaper("Lettuce", PIECES, "30,0", LARGE),
          onPaper("Potatoes", KG, "3,00", SMALL),
        ],
      },
      { label: FRUIT_HEADING, rows: [onPaper("Apples", KG, "30,00", "")] },
    ]);
  });

  it("offers no way to add, edit or delete an article", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: /table\.add_plus_icon/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "table.actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

    await userEvent.click(within(rowOf("Carrots")).getByText(BUNCH));

    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(within(rowOf("Carrots")).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(rowOf("Carrots")).queryByRole("textbox")).not.toBeInTheDocument();
  });
});

// ── Day ─────────────────────────────────────────────────────────────────────

describe("CommissioningListPacking choosing the day", () => {
  it("offers the week's delivery days, each with its date", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(await optionsOf(selectNamed(DAY))).toEqual([TUESDAY_LABEL, FRIDAY_LABEL]);
  });

  it("lists another day's amounts from the week's plan when the day changes, without asking again", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const requestsSoFar = api.planning.mock.calls.length;

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    expect(await screen.findByText("Radishes")).toBeInTheDocument();
    expect(rowsOf(tableOf(VEGETABLES_HEADING))).toEqual([
      ["Carrots", BUNCH, "12,0"],
      ["Radishes", BUNCH, "10,0"],
    ]);
    // No fruit is needed on Friday.
    expect(rowsOf(tableOf(FRUIT_HEADING))).toEqual([]);
    expect(within(tableOf(FRUIT_HEADING)).getByText(NO_DATA)).toBeInTheDocument();
    expect(api.planning).toHaveBeenCalledTimes(requestsSoFar);
  });

  it("steps to the next delivery day with the arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(DAY, "common.next"));

    expect(await screen.findByText("Radishes")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(FRIDAY_LABEL);
    expect(screen.queryByText("Lettuce")).not.toBeInTheDocument();
  });

  it("writes the days' dates in the farm's date format", async () => {
    tenantSettings.values = { date_format: "YYYY-MM-DD" };
    renderPage();
    await screen.findByText("Carrots");

    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Tuesday, 2026-10-06"));
  });
});

// ── Week and year ───────────────────────────────────────────────────────────

describe("CommissioningListPacking choosing the week and year", () => {
  it("loads the next week's plan of every share option from the week arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 42");
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Tuesday, 13.10.2026"));
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-17" });
    expect(api.planning).toHaveBeenCalledWith(planningRequest(VEGETABLES, { week: 42 }));
    expect(api.planning).toHaveBeenCalledWith(planningRequest(FRUIT, { week: 42 }));
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    expect(rowsOf(tableOf(VEGETABLES_HEADING))).toEqual([["Beetroot", BUNCH, "6,0"]]);
    expect(within(tableOf(FRUIT_HEADING)).getByText(NO_DATA)).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("keeps the chosen delivery day in the next week", async () => {
    renderPage();
    await screen.findByText("Carrots");
    await choose(selectNamed(DAY), FRIDAY_LABEL);
    await screen.findByText("Radishes");

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Friday, 16.10.2026"));
    expect(rowsOf(tableOf(VEGETABLES_HEADING))).toEqual([["Beetroot", BUNCH, "4,0"]]);
  });

  it("loads the previous week's plan from the week arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));

    expect(await screen.findByText("Spinach")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Tuesday, 29.09.2026"));
    expect(api.planning).toHaveBeenCalledWith(planningRequest(VEGETABLES, { week: 40 }));
    expect(api.planning).toHaveBeenCalledWith(planningRequest(FRUIT, { week: 40 }));
    expect(rowsOf(tableOf(VEGETABLES_HEADING))).toEqual([["Spinach", KG, "4,00"]]);
  });

  it("asks for the stored plan once the week lies more than a week back", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await screen.findByText("Spinach");
    await userEvent.click(arrow(WEEK, "common.previous"));

    await waitFor(() =>
      expect(api.planning).toHaveBeenCalledWith(
        planningRequest(VEGETABLES, { week: 39, isPast: true }),
      ),
    );
    expect(api.planning).toHaveBeenCalledWith(planningRequest(FRUIT, { week: 39, isPast: true }));
  });

  it("gives a table to the share options of the chosen week, not to today's", async () => {
    // The fruit share ends with week 41.
    api.shareTypes.mockImplementation(async ({ active_at_date }: { active_at_date: string }) =>
      active_at_date < "2026-10-12" ? [VEGETABLE_SHARE, FRUIT_SHARE] : [VEGETABLE_SHARE],
    );
    renderPage();
    await screen.findByText("Apples");

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    await waitFor(() => expect(tables()).toHaveLength(1));
    expect(headings()).toEqual([]);
    expect(api.shareTypes).toHaveBeenLastCalledWith({ active_at_date: "2026-10-17" });
    expect(api.planning).not.toHaveBeenCalledWith(planningRequest(FRUIT, { week: 42 }));
  });

  it("asks for the same week of another year when the year changes", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(selectNamed(YEAR), "2027");

    await waitFor(() =>
      expect(api.planning).toHaveBeenCalledWith(planningRequest(VEGETABLES, { year: 2027 })),
    );
    expect(api.planning).toHaveBeenCalledWith(planningRequest(FRUIT, { year: 2027 }));
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2027-10-16" });
    await waitFor(() => expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Tuesday, 12.10.2027")));
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    expect(tables().map(rowsOf)).toEqual([[], []]);
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("shows none of the previous week's articles while the next week loads", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const nextWeek = pending<void>();
    api.planning.mockImplementation(async (params: PlanningParams) => {
      await nextWeek.promise;
      return answerFromFarm(params);
    });

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(tables().every((table) => isBusy(table))).toBe(true));
    expect(tables().map(rowsOf)).toEqual([[], []]);
    expect(downloadButton()).toBeDisabled();

    nextWeek.answer();

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    expect(downloadButton()).toBeEnabled();
  });
});

// ── Nothing to pack, or no plan ─────────────────────────────────────────────

describe("CommissioningListPacking without a plan", () => {
  it("says there is nothing to pack, and offers nothing to download, in a week without a plan", async () => {
    farm.plans = {};
    renderPage();

    await waitFor(() => expect(api.planning).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL));
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    expect(within(tableOf(VEGETABLES_HEADING)).getByText(NO_DATA)).toBeInTheDocument();
    expect(within(tableOf(FRUIT_HEADING)).getByText(NO_DATA)).toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();
  });

  it("shows no day, nothing to pack and nothing to download in a week without delivery days", async () => {
    api.deliveryDays.mockImplementation(async ({ active_at_date }: { active_at_date: string }) =>
      active_at_date === "2026-10-17" ? [] : [...farm.deliveryDays],
    );
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(selectNamed(DAY)).toHaveTextContent("commissioning.no_delivery_days_in_week"));
    expect(shownIn(selectNamed(DAY))).toBe("");
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    expect(tables().map(rowsOf)).toEqual([[], []]);
    expect(downloadButton()).toBeDisabled();
  });

  it("says which share option's plan failed to load, keeps the download disabled and still lists the others", async () => {
    let vegetablesFail = true;
    api.planning.mockImplementation(async (params: PlanningParams) => {
      if (vegetablesFail && params.share_option === VEGETABLES && params.delivery_week === 41) {
        throw new Error("Network Error");
      }
      return answerFromFarm(params);
    });
    renderPage();

    expect(await screen.findByText("Apples")).toBeInTheDocument();
    await waitFor(() => expect(anyTableBusy()).toBe(false));
    const vegetables = tableOf(VEGETABLES_HEADING);
    expect(rowsOf(vegetables)).toEqual([]);
    expect(within(vegetables).getByRole("alert")).toHaveTextContent(LOAD_FAILED);
    expect(within(tableOf(FRUIT_HEADING)).queryByRole("alert")).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    vegetablesFail = false;
    await userEvent.click(within(vegetables).getByRole("button", { name: "table.retry" }));

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(downloadButton()).toBeEnabled());
  });
});

// ── Download ────────────────────────────────────────────────────────────────

describe("CommissioningListPacking download", () => {
  it("prints the day's articles of every share option, named after the list, year and week", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.files).toHaveLength(1));
    expect(printed.files[0]).toBe(
      "commissioning.commissioning_list_packing_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf",
    );
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("CommissioningListPackingPDF");
    expect(props).toMatchObject({
      year: 2026,
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      showSize: false,
    });
    expect(props.groups).toEqual([
      {
        label: VEGETABLES_HEADING,
        rows: [
          onPaper("Carrots", BUNCH, "18,0"),
          onPaper("Lettuce", PIECES, "30,0"),
          onPaper("Potatoes", KG, "3,00"),
        ],
      },
      { label: FRUIT_HEADING, rows: [onPaper("Apples", KG, "30,00")] },
    ]);
  });

  it("prints the chosen day's articles, named after that day, and leaves out a share option with nothing to pack that day", async () => {
    renderPage();
    await screen.findByText("Carrots");
    await choose(selectNamed(DAY), FRIDAY_LABEL);
    await screen.findByText("Radishes");

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.files).toEqual([
      "commissioning.commissioning_list_packing_2026_commissioning.KW41_COMMONWEEKDAYFRIDAY.pdf",
    ]);
    expect(printed.documents[0].props).toMatchObject({ dayName: "COMMON.WEEKDAY_FRIDAY" });
    expect(printed.documents[0].props.groups).toEqual([
      {
        label: VEGETABLES_HEADING,
        rows: [onPaper("Carrots", BUNCH, "12,0"), onPaper("Radishes", BUNCH, "10,0")],
      },
    ]);
  });

  it("offers the download only once every share option's plan is in", async () => {
    const fruit = pending<void>();
    api.planning.mockImplementation(async (params: PlanningParams) => {
      if (params.share_option === FRUIT) await fruit.promise;
      return answerFromFarm(params);
    });
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    fruit.answer();

    expect(await screen.findByText("Apples")).toBeInTheDocument();
    await waitFor(() => expect(downloadButton()).toBeEnabled());
  });

  it("prints the week the list shows", async () => {
    renderPage();
    await screen.findByText("Carrots");
    await userEvent.click(arrow(WEEK, "common.next"));
    await screen.findByText("Beetroot");

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.files).toHaveLength(1));
    expect(printed.files[0]).toMatch(/_2026_commissioning\.KW42(_\w+)?\.pdf$/);
    expect(printed.documents[0].props).toMatchObject({ year: 2026, week: 42 });
    expect(printed.documents[0].props.groups).toEqual([
      { label: VEGETABLES_HEADING, rows: [onPaper("Beetroot", BUNCH, "6,0")] },
    ]);
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("CommissioningListPacking on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each article as a card with its unit and total instead of a table", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(headings()).toEqual([VEGETABLES_HEADING, FRUIT_HEADING]);
    expect(cardsIn(tableOf(VEGETABLES_HEADING))).toEqual(["Carrots", "Lettuce", "Potatoes"]);
    expect(cardsIn(tableOf(FRUIT_HEADING))).toEqual(["Apples"]);
    expect(detailsOf(cardOf("Carrots"))).toEqual([`${UNIT}: ${BUNCH}`, `${TOTAL}: 18,0`]);
    expect(detailsOf(cardOf("Apples"))).toEqual([`${UNIT}: ${KG}`, `${TOTAL}: 30,00`]);
  });

  it("adds the size to the cards when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await screen.findByText("Carrots");

    expect(detailsOf(cardOf("Lettuce"))).toEqual([
      `${UNIT}: ${PIECES}`,
      `${SIZE}: ${LARGE}`,
      `${TOTAL}: 30,0`,
    ]);
  });

  it("shows a spinner instead of cards while the plans load", async () => {
    const plans = pending<void>();
    api.planning.mockImplementation(async (params: PlanningParams) => {
      await plans.promise;
      return answerFromFarm(params);
    });
    renderPage();

    await waitFor(() => expect(tables()).toHaveLength(2));
    await waitFor(() => expect(tables().every((table) => isBusy(table))).toBe(true));
    expect(screen.queryByText(NO_DATA)).not.toBeInTheDocument();

    plans.answer();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(anyTableBusy()).toBe(false));
  });

  it("labels the delivery day in the short phone format", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(shownIn(selectNamed(DAY))).toBe("Tu, 06.10.");
  });

  it("leaves out the download", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: DOWNLOAD })).not.toBeInTheDocument();
  });

  it("offers no add button and opens nothing when a card is tapped", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Carrots"));

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says when a share option has nothing to pack that day", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(selectNamed(DAY), "Fr, 09.10.");

    expect(await screen.findByText("Radishes")).toBeInTheDocument();
    expect(within(tableOf(FRUIT_HEADING)).getByText(NO_DATA)).toBeInTheDocument();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("CommissioningListPacking render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Carrots");
    await flushMicrotasks();

    // A setState-in-render loop makes thousands of commits.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});
