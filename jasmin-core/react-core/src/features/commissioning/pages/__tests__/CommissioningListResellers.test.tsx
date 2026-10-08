/**
 * CommissioningListResellers: the packing list of the resellers' orders on one
 * delivery day, one card per reseller with something to pack. Rendered through
 * the real week and day selectors, number and label hooks and PDF download
 * button. The generated commissioning client is the mocking boundary: its
 * hooks are real TanStack queries around spies that answer from an in-memory
 * farm. The PDF library, the PDF template and the browser download are
 * stubbed, so no real PDF is rendered.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The page reads "today" when it
 * mounts, so a test that moves the clock before rendering opens on that day.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommissioningListResellersEntry,
  CommissioningListResellersOrderContent,
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

const api = vi.hoisted(() => ({
  orders: vi.fn(),
  daysWithOrders: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(
      params?: unknown,
      options?: { query?: { enabled?: boolean } },
    ) {
      return useQuery({
        queryKey: [`/api/commissioning/${path}/`, ...(params ? [params] : [])],
        queryFn: async () => request(params),
        enabled: options?.query?.enabled,
      });
    };
  return {
    useCommissioningCommissioningListsResellersList: queryHook(
      "commissioning_lists_resellers",
      api.orders,
    ),
    useCommissioningDaysWithOrdersRetrieve: queryHook("days_with_orders", api.daysWithOrders),
  };
});

// The page only needs its download button; the barrel would also load every
// other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  CommissioningListResellersPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/CommissioningListResellersPDFGenerator")
  ).default,
}));
vi.mock("@features/commissioning/pdfs/exports/CommissioningListResellersPDF", () => ({
  default: function CommissioningListResellersPDF() {
    return null;
  },
}));

// The documents handed to the PDF renderer and the files saved, in order.
const printed = vi.hoisted(() => ({
  documents: [] as { template: string; props: Record<string, unknown> }[],
  files: [] as string[],
}));
// Nothing on this page loads the PDF library before the download is clicked,
// and the download only calls `pdf()`.
vi.mock("@react-pdf/renderer", () => ({
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

import CommissioningListResellers from "../CommissioningListResellers";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Backend day numbers: 0 = Monday … 6 = Sunday.
const TUESDAY = 1;
const WEDNESDAY = 2;
const THURSDAY = 3;

type OrderLine = CommissioningListResellersOrderContent;

/** One line of an order: an article, how much of it, and how much fills one PU. */
const line = (
  article: string,
  amount: number,
  amountPerPu: number,
  {
    unit = "KG",
    size = "M",
    sort = null,
    note = "",
  }: Partial<Pick<OrderLine, "unit" | "size" | "sort" | "note">> = {},
): OrderLine => ({
  id: `oc-${article}-${unit}-${size}`,
  share_article_id: `sa-${article}`,
  share_article_name: article,
  amount,
  amount_per_pu: amountPerPu,
  size,
  unit,
  sort,
  note,
});

/** A reseller with its order on the day. */
const orderOf = (
  reseller: string,
  lines: OrderLine[],
  note = "",
): CommissioningListResellersEntry => ({
  id: `res-${reseller}`,
  name: reseller,
  address: "",
  order: { id: `order-${reseller}`, number: null, note, contents: lines },
});

const WASH = "Wash before packing";
const EARLY = "Deliver before 8 am";

const GREEN_GROCER = orderOf(
  "Green Grocer",
  [
    line("Carrots", 12, 2.5, { size: "L", sort: "Nantaise", note: WASH }),
    line("Lettuce", 30, 12, { unit: "PCS" }),
  ],
  EARLY,
);
const CORNER_CAFE = orderOf("Corner Café", [
  line("Radishes", 10, 3, { unit: "BUNCH", size: "S", sort: "Cherry Belle" }),
  line("Potatoes", 1250, 12.5),
]);
/** An order with nothing in it to pack. */
const VILLAGE_SHOP = orderOf("Village Shop", []);

const TUESDAY_ORDERS = [GREEN_GROCER, VILLAGE_SHOP, CORNER_CAFE];
const THURSDAY_ORDERS = [orderOf("Green Grocer", [line("Pumpkins", 8, 4, { unit: "PCS" })])];
const NEXT_TUESDAY_ORDERS = [
  orderOf("Corner Café", [line("Beetroot", 6, 2, { unit: "BUNCH" })]),
];

const weekOf = (year: number, week: number) => `${year}/${week}`;
const slot = (year: number, week: number, day: number) => `${weekOf(year, week)}/${day}`;

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  orders: Record<string, CommissioningListResellersEntry[]>;
  daysWithOrders: Record<string, number[]>;
};

type OrdersParams = { year: number; delivery_week: number; day_number: number };
type DaysParams = { year: number; delivery_week: number };

/** The orders request for a day of week 41 of 2026 unless told otherwise. */
const ordersRequest = (day: number, { year = 2026, week = 41 } = {}): OrdersParams => ({
  year,
  delivery_week: week,
  day_number: day,
});
const daysRequest = ({ year = 2026, week = 41 } = {}): DaysParams => ({
  year,
  delivery_week: week,
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<CommissioningListResellers />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const DAY = "common.delivery_day";
const WEEK = "common.week";
const YEAR = "common.year";
const TITLE = "commissioning.commissioning_list_reseller";
const NO_ORDERS = "commissioning.no_orders_title";
const LOAD_FAILED = "table.load_failed_title";
const EXPLAINER = "explainers.commissioning_lists";
const DOWNLOAD = /download\.commissioning_list$/;
const PU = "commissioning.pu";
const KG = "commissioning.units.kg";
const PIECES = "commissioning.units.pcs";
const BUNCHES = "commissioning.units.bunch";
const LARGE = "commissioning.large";
const SMALL = "commissioning.small";
const MEDIUM = "commissioning.medium";

const dayLabel = (date: string) => `commissioning.delivery_day ${date}`;
const TUESDAY_LABEL = dayLabel("Tuesday, 06.10.2026");
const THURSDAY_LABEL = dayLabel("Thursday, 08.10.2026");

function selectNamed(name: string): HTMLElement {
  const select = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-select");
  if (!select) throw new Error(`No select named ${name}`);
  return select;
}

/** The label a select shows for its current value. */
const shownIn = (select: HTMLElement) =>
  select.querySelector(".ant-select-selection-item")?.textContent ?? "";

function openDropdown(): HTMLElement {
  const open = Array.from(
    document.querySelectorAll<HTMLElement>(".ant-select-dropdown"),
  ).filter((dropdown) => !dropdown.classList.contains("ant-select-dropdown-hidden"));
  const dropdown = open[open.length - 1];
  if (!dropdown) throw new Error("No select dropdown is open");
  return dropdown;
}

/** Picks an option by its visible label. The select's hidden accessibility
 * list repeats an option's value, which for a year is its label too. */
async function choose(select: HTMLElement, option: string) {
  await userEvent.click(within(select).getByRole("combobox"));
  const item = Array.from(
    openDropdown().querySelectorAll<HTMLElement>(".ant-select-item-option-content"),
  ).find((content) => content.textContent === option);
  if (!item) throw new Error(`No option ${option}`);
  await userEvent.click(item);
}

/** The days the open day picker offers, each with whether it shows as a day
 * with orders (the green ``with-orders`` option). */
const offeredDays = () =>
  Array.from(openDropdown().querySelectorAll(".ant-select-item-option"), (option) => ({
    day: option.querySelector(".ant-select-item-option-content")?.textContent ?? "",
    hasOrders: option.classList.contains("with-orders"),
  }));

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

/** Cell text as it reads on screen, with runs of whitespace collapsed. */
const readable = (text: string | null) => (text ?? "").replace(/\s+/g, " ").trim();

/** The card of a reseller. */
function cardOf(reseller: string): HTMLElement {
  const card = screen.getByText(reseller).closest<HTMLElement>(".ant-card");
  if (!card) throw new Error(`No card for ${reseller}`);
  return card;
}

/** The heading of a reseller's card: its name and the order's note. */
function headingOf(reseller: string): HTMLElement {
  const heading = cardOf(reseller).querySelector<HTMLElement>(".ant-card-head-title");
  if (!heading) throw new Error(`The card of ${reseller} has no heading`);
  return heading;
}

/** The resellers that have a card, top to bottom. */
const cardNames = () =>
  Array.from(
    document.querySelectorAll(".ant-card-head-title"),
    (heading) => heading.querySelector("span")?.textContent ?? "",
  );

const columnsOf = (reseller: string) =>
  Array.from(cardOf(reseller).querySelectorAll(".ant-table-thead th"), (cell) =>
    readable(cell.textContent),
  );

/** The article rows of a reseller's card, each as its cells, left to right. */
const rowsOf = (reseller: string) =>
  Array.from(cardOf(reseller).querySelectorAll(".ant-table-tbody > tr.ant-table-row"), (row) =>
    Array.from(row.querySelectorAll("td"), (cell) => readable(cell.textContent)),
  );

/** The phone block that shows an article. */
function blockOf(article: string): HTMLElement {
  const block = screen.getByText(article).closest<HTMLElement>(".mobile-card-item");
  if (!block) throw new Error(`No block shows ${article}`);
  return block;
}

/** What a phone block shows under each of its small labels. */
const figuresOf = (block: HTMLElement): Record<string, string> =>
  Object.fromEntries(
    Array.from(block.querySelectorAll(".text-muted-xs"), (label) => [
      label.textContent ?? "",
      Array.from(label.nextElementSibling?.children ?? [], (part) => part.textContent ?? "").join(
        " ",
      ),
    ]),
  );

const downloadButton = () => screen.getByRole("button", { name: DOWNLOAD });

const isBusy = () => document.querySelector('[aria-busy="true"]') !== null;

/** An order with carrots both by the bunch and by the kilo, and beetroot. */
const FARM_SHOP_LINES = [
  line("Beetroot", 6, 2, { unit: "BUNCH" }),
  line("Carrots", 10, 5, { unit: "BUNCH" }),
  line("Carrots", 20, 10),
];

/** Takes the beetroot out of the farm shop's order, and the office comes back
 *  to the tab, so the page fetches the orders again. */
async function beetrootTakenOut() {
  farm.orders[slot(2026, 41, TUESDAY)] = [orderOf("Farm Shop", FARM_SHOP_LINES.slice(1))];
  await act(async () => {
    window.dispatchEvent(new Event("visibilitychange"));
  });
}

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => {
    answer = resolve;
  });
  return { promise, answer };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  printed.documents = [];
  printed.files = [];
  farm = {
    orders: {
      [slot(2026, 41, TUESDAY)]: TUESDAY_ORDERS,
      [slot(2026, 41, THURSDAY)]: THURSDAY_ORDERS,
      [slot(2026, 42, TUESDAY)]: NEXT_TUESDAY_ORDERS,
    },
    daysWithOrders: {
      [weekOf(2026, 41)]: [TUESDAY, THURSDAY],
      [weekOf(2026, 42)]: [TUESDAY],
    },
  };
  api.orders
    .mockReset()
    .mockImplementation(async ({ year, delivery_week, day_number }: OrdersParams) => [
      ...(farm.orders[slot(year, delivery_week, day_number)] ?? []),
    ]);
  api.daysWithOrders
    .mockReset()
    .mockImplementation(async ({ year, delivery_week }: DaysParams) => ({
      days: [...(farm.daysWithOrders[weekOf(year, delivery_week)] ?? [])],
    }));
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("CommissioningListResellers loading", () => {
  it("opens on today's delivery day with a card for every reseller with something to pack", async () => {
    renderPage();

    expect(await screen.findByText("Green Grocer")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: TITLE })).toBeInTheDocument();
    expect(shownIn(selectNamed(YEAR))).toBe("2026");
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 41");
    expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL);
    expect(api.orders).toHaveBeenLastCalledWith(ordersRequest(TUESDAY));
    expect(api.daysWithOrders).toHaveBeenLastCalledWith(daysRequest());
    // In the server's order, without the reseller whose order is empty.
    expect(cardNames()).toEqual(["Green Grocer", "Corner Café"]);
    expect(screen.queryByText(NO_ORDERS)).not.toBeInTheDocument();
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });

  it("shows no card and does not claim there are no orders while the orders load", async () => {
    const orders = pending<CommissioningListResellersEntry[]>();
    api.orders.mockImplementation(() => orders.promise);
    renderPage();

    await waitFor(() => expect(api.orders).toHaveBeenCalled());
    expect(cardNames()).toEqual([]);
    expect(screen.queryByText(NO_ORDERS)).not.toBeInTheDocument();
    expect(isBusy()).toBe(true);
    expect(downloadButton()).toBeDisabled();

    orders.answer(TUESDAY_ORDERS);

    expect(await screen.findByText("Green Grocer")).toBeInTheDocument();
    expect(cardNames()).toEqual(["Green Grocer", "Corner Café"]);
    expect(isBusy()).toBe(false);
    expect(downloadButton()).toBeEnabled();
  });

  it("says the orders could not be loaded, not that there are none, and loads them on retry", async () => {
    api.orders.mockRejectedValueOnce(new Error("Network Error"));
    renderPage();

    expect(await screen.findByText(LOAD_FAILED)).toBeInTheDocument();
    expect(screen.queryByText(NO_ORDERS)).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "table.retry" }));

    expect(await screen.findByText("Green Grocer")).toBeInTheDocument();
    expect(screen.queryByText(LOAD_FAILED)).not.toBeInTheDocument();
  });
});

// ── Opening day ─────────────────────────────────────────────────────────────

describe("CommissioningListResellers opening day", () => {
  /** Opens the page on the given day and waits for its first orders request. */
  async function openOn(date: Date) {
    vi.setSystemTime(date);
    renderPage();
    await waitFor(() => expect(api.orders).toHaveBeenCalled());
  }

  it.each([
    ["Monday", new Date(2026, 9, 5, 12, 0), "Monday, 05.10.2026", 0],
    ["Tuesday", new Date(2026, 9, 6, 12, 0), "Tuesday, 06.10.2026", TUESDAY],
    ["Wednesday", new Date(2026, 9, 7, 12, 0), "Wednesday, 07.10.2026", WEDNESDAY],
    ["Thursday", new Date(2026, 9, 8, 12, 0), "Thursday, 08.10.2026", THURSDAY],
  ])("opens on today on a %s", async (_weekday, today, label, day) => {
    await openOn(today);

    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 41");
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel(label));
    expect(api.orders.mock.calls).toEqual([[ordersRequest(day)]]);
  });

  // The module loaded on Tuesday of week 41, so these also show that the
  // page reads the date when it opens.
  it.each([
    ["Friday", new Date(2026, 9, 9, 12, 0)],
    ["Saturday", new Date(2026, 9, 10, 12, 0)],
    ["Sunday", new Date(2026, 9, 11, 12, 0)],
  ])("opens on next week's Monday on a %s, without asking for this week", async (_weekday, today) => {
    await openOn(today);

    expect(shownIn(selectNamed(YEAR))).toBe("2026");
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 42");
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Monday, 12.10.2026"));
    expect(api.orders.mock.calls).toEqual([[ordersRequest(0, { week: 42 })]]);
    expect(api.daysWithOrders.mock.calls).toEqual([[daysRequest({ week: 42 })]]);
  });

  it("opens on the Monday of week 53 on the Friday of week 52 of a year with 53 weeks", async () => {
    await openOn(new Date(2026, 11, 25, 12, 0));

    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 53");
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Monday, 28.12.2026"));
    expect(api.orders.mock.calls).toEqual([[ordersRequest(0, { week: 53 })]]);
  });

  it("opens on week 1 of the next year on the Friday of a year's last week", async () => {
    // 1 January 2027 still belongs to ISO week 53 of 2026.
    await openOn(new Date(2027, 0, 1, 12, 0));

    expect(shownIn(selectNamed(YEAR))).toBe("2027");
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 1");
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Monday, 04.01.2027"));
    expect(api.orders.mock.calls).toEqual([[ordersRequest(0, { year: 2027, week: 1 })]]);
    expect(api.daysWithOrders.mock.calls).toEqual([[daysRequest({ year: 2027, week: 1 })]]);
  });
});

// ── The cards ───────────────────────────────────────────────────────────────

describe("CommissioningListResellers cards", () => {
  it("heads each card with the reseller's name and the order's note", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    expect(headingOf("Green Grocer")).toHaveTextContent(EARLY);
    expect(readable(headingOf("Corner Café").textContent)).toBe("Corner Café");
  });

  it("lists each article with its PU count and amount, sort and size, amount per PU and note", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    expect(columnsOf("Green Grocer")).toEqual([
      "commissioning.amount",
      "commissioning.share_article",
      "commissioning.per_pu",
      "commissioning.note",
    ]);
    // PU counts and amounts to one decimal, amounts per PU to two, in the
    // farm's default German format; the medium size goes without a label.
    expect(rowsOf("Green Grocer")).toEqual([
      [`4,8 ${PU} (12,0 ${KG})`, `Carrots Nantaise, ${LARGE}`, `(2,50 ${KG}/${PU})`, WASH],
      [`2,5 ${PU} (30,0 ${PIECES})`, "Lettuce", `(12,00 ${PIECES}/${PU})`, ""],
    ]);
    expect(rowsOf("Corner Café")).toEqual([
      [
        `3,3 ${PU} (10,0 ${BUNCHES})`,
        `Radishes Cherry Belle, ${SMALL}`,
        `(3,00 ${BUNCHES}/${PU})`,
        "",
      ],
      [`100,0 ${PU} (1.250,0 ${KG})`, "Potatoes", `(12,50 ${KG}/${PU})`, ""],
    ]);
  });

  it("writes the numbers on screen and on paper in the farm's number format", async () => {
    tenantSettings.values = { number_locale: "en-US" };
    renderPage();
    await screen.findByText("Green Grocer");

    expect(rowsOf("Green Grocer")[0]).toEqual([
      `4.8 ${PU} (12.0 ${KG})`,
      `Carrots Nantaise, ${LARGE}`,
      `(2.50 ${KG}/${PU})`,
      WASH,
    ]);
    expect(rowsOf("Corner Café")[1]).toEqual([
      `100.0 ${PU} (1,250.0 ${KG})`,
      "Potatoes",
      `(12.50 ${KG}/${PU})`,
      "",
    ]);

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.documents[0].props).toMatchObject({ locale: "en-US" });
  });

  it("lists an article ordered in two units as two lines, also once the order is fetched again", async () => {
    farm.orders[slot(2026, 41, TUESDAY)] = [orderOf("Farm Shop", FARM_SHOP_LINES)];
    renderPage();
    await screen.findByText("Farm Shop");
    expect(rowsOf("Farm Shop")).toHaveLength(3);

    await beetrootTakenOut();

    await waitFor(() => expect(rowsOf("Farm Shop")).toHaveLength(2));
    expect(rowsOf("Farm Shop").map(([amount]) => amount)).toEqual([
      `2,0 ${PU} (10,0 ${BUNCHES})`,
      `2,0 ${PU} (20,0 ${KG})`,
    ]);
  });

  it("leaves out a reseller whose order holds nothing to pack", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    expect(screen.queryByText("Village Shop")).not.toBeInTheDocument();
  });

  it("names an article without a sort by its name and size alone", async () => {
    farm.orders[slot(2026, 41, TUESDAY)] = [
      orderOf("Farm Shop", [line("Carrots", 12, 2.5, { size: "L" })]),
    ];
    renderPage();
    await screen.findByText("Farm Shop");

    expect(rowsOf("Farm Shop")[0][1]).toBe(`Carrots, ${LARGE}`);
  });

  it("says there are no orders, and offers nothing to download, on a day whose orders are all empty", async () => {
    farm.orders[slot(2026, 41, TUESDAY)] = [VILLAGE_SHOP];
    renderPage();

    expect(await screen.findByText(NO_ORDERS)).toBeInTheDocument();
    expect(cardNames()).toEqual([]);
    expect(downloadButton()).toBeDisabled();
  });

  it("says there are no orders, and offers nothing to download, on a day without orders", async () => {
    farm.orders = {};
    renderPage();

    expect(await screen.findByText(NO_ORDERS)).toBeInTheDocument();
    expect(cardNames()).toEqual([]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();
  });
});

// ── Day ─────────────────────────────────────────────────────────────────────

describe("CommissioningListResellers choosing the day", () => {
  it("offers every day of the week with its date and shows which days have orders", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    await userEvent.click(screen.getByRole("combobox", { name: DAY }));

    await waitFor(() =>
      expect(offeredDays()).toEqual([
        { day: dayLabel("Monday, 05.10.2026"), hasOrders: false },
        { day: TUESDAY_LABEL, hasOrders: true },
        { day: dayLabel("Wednesday, 07.10.2026"), hasOrders: false },
        { day: THURSDAY_LABEL, hasOrders: true },
        { day: dayLabel("Friday, 09.10.2026"), hasOrders: false },
        { day: dayLabel("Saturday, 10.10.2026"), hasOrders: false },
        { day: dayLabel("Sunday, 11.10.2026"), hasOrders: false },
      ]),
    );
  });

  it("lists another day's orders when the day changes", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    await choose(selectNamed(DAY), THURSDAY_LABEL);

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(api.orders).toHaveBeenLastCalledWith(ordersRequest(THURSDAY));
    expect(api.daysWithOrders).toHaveBeenLastCalledWith(daysRequest());
    expect(cardNames()).toEqual(["Green Grocer"]);
    expect(rowsOf("Green Grocer")).toEqual([
      [`2,0 ${PU} (8,0 ${PIECES})`, "Pumpkins", `(4,00 ${PIECES}/${PU})`, ""],
    ]);
    expect(screen.queryByText(/^Carrots/)).not.toBeInTheDocument();
  });

  it("steps to the next day with the arrow and says when that day has no orders", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    await userEvent.click(arrow(DAY, "common.next"));

    expect(await screen.findByText(NO_ORDERS)).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Wednesday, 07.10.2026"));
    expect(api.orders).toHaveBeenLastCalledWith(ordersRequest(WEDNESDAY));
    expect(cardNames()).toEqual([]);
  });

  it("shows none of the previous day's cards while another day loads", async () => {
    renderPage();
    await screen.findByText("Green Grocer");
    const thursday = pending<CommissioningListResellersEntry[]>();
    api.orders.mockImplementation(() => thursday.promise);

    await choose(selectNamed(DAY), THURSDAY_LABEL);

    await waitFor(() => expect(api.orders).toHaveBeenLastCalledWith(ordersRequest(THURSDAY)));
    expect(cardNames()).toEqual([]);
    expect(screen.queryByText(NO_ORDERS)).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    thursday.answer(THURSDAY_ORDERS);

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(cardNames()).toEqual(["Green Grocer"]);
  });
});

// ── Week and year ───────────────────────────────────────────────────────────

describe("CommissioningListResellers choosing the week and year", () => {
  it("loads the next week's orders and days with orders from the week arrow", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 42");
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Tuesday, 13.10.2026"));
    expect(api.orders).toHaveBeenLastCalledWith(ordersRequest(TUESDAY, { week: 42 }));
    expect(api.daysWithOrders).toHaveBeenLastCalledWith(daysRequest({ week: 42 }));
    expect(cardNames()).toEqual(["Corner Café"]);

    await userEvent.click(screen.getByRole("combobox", { name: DAY }));

    await waitFor(() =>
      expect(offeredDays().filter(({ hasOrders }) => hasOrders)).toEqual([
        { day: dayLabel("Tuesday, 13.10.2026"), hasOrders: true },
      ]),
    );
  });

  it("asks for the same week and day of another year when the year changes", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    await choose(selectNamed(YEAR), "2027");

    expect(await screen.findByText(NO_ORDERS)).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(dayLabel("Tuesday, 12.10.2027"));
    expect(api.orders).toHaveBeenLastCalledWith(ordersRequest(TUESDAY, { year: 2027 }));
    expect(api.daysWithOrders).toHaveBeenLastCalledWith(daysRequest({ year: 2027 }));
  });
});

// ── Download ────────────────────────────────────────────────────────────────

describe("CommissioningListResellers download", () => {
  it("prints the day's orders as a PDF named after the week and day", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    await userEvent.click(downloadButton());

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.commissioning_list_reseller_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf",
      ]),
    );
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("CommissioningListResellersPDF");
    expect(props).toMatchObject({
      year: 2026,
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      locale: "de-DE",
    });
    expect(props.data).toEqual(expect.arrayContaining([GREEN_GROCER, CORNER_CAFE]));
  });

  it("prints the chosen day's orders, named after that day", async () => {
    renderPage();
    await screen.findByText("Green Grocer");
    await choose(selectNamed(DAY), THURSDAY_LABEL);
    await screen.findByText("Pumpkins");

    await userEvent.click(downloadButton());

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.commissioning_list_reseller_2026_commissioning.KW41_COMMONWEEKDAYTHURSDAY.pdf",
      ]),
    );
    expect(printed.documents[0].props).toMatchObject({
      week: 41,
      dayName: "COMMON.WEEKDAY_THURSDAY",
      data: THURSDAY_ORDERS,
    });
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("CommissioningListResellers on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("stacks each article as a block with its amount, PU count and note instead of a table", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(cardNames()).toEqual(["Green Grocer", "Corner Café"]);
    expect(headingOf("Green Grocer")).toHaveTextContent(EARLY);
    expect(cardOf("Green Grocer").querySelectorAll(".mobile-card-item")).toHaveLength(2);

    // Named like the table names it: the sort after the name, then the size.
    const carrots = blockOf(`Carrots Nantaise, ${LARGE}`);
    expect(figuresOf(carrots)).toEqual({
      "commissioning.amount": `12,0 ${KG}`,
      [PU]: `4,8 (2,50 ${KG}/${PU})`,
    });
    expect(within(carrots).getByText(WASH)).toBeInTheDocument();

    const lettuce = blockOf("Lettuce");
    expect(within(lettuce).queryByText(MEDIUM)).not.toBeInTheDocument();
    expect(blockOf(`Radishes Cherry Belle, ${SMALL}`)).toBeInTheDocument();
    expect(figuresOf(lettuce)).toEqual({
      "commissioning.amount": `30,0 ${PIECES}`,
      [PU]: `2,5 (12,00 ${PIECES}/${PU})`,
    });

    expect(figuresOf(blockOf("Potatoes"))).toEqual({
      "commissioning.amount": `1.250,0 ${KG}`,
      [PU]: `100,0 (12,50 ${KG}/${PU})`,
    });
  });

  it("shows an article ordered in two units as two blocks, also once the order is fetched again", async () => {
    farm.orders[slot(2026, 41, TUESDAY)] = [orderOf("Farm Shop", FARM_SHOP_LINES)];
    renderPage();
    await screen.findByText("Farm Shop");

    await beetrootTakenOut();

    const blocks = () => Array.from(cardOf("Farm Shop").querySelectorAll<HTMLElement>(".mobile-card-item"));
    await waitFor(() => expect(blocks()).toHaveLength(2));
    expect(blocks().map((block) => figuresOf(block)["commissioning.amount"])).toEqual([
      `10,0 ${BUNCHES}`,
      `20,0 ${KG}`,
    ]);
  });

  it("labels the delivery day in the short phone format", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    expect(shownIn(selectNamed(DAY))).toBe("Tu, 06.10.");
  });

  it("leaves out the download and the explainer", async () => {
    renderPage();
    await screen.findByText("Green Grocer");

    expect(screen.queryByRole("button", { name: DOWNLOAD })).not.toBeInTheDocument();
    expect(screen.queryByText(EXPLAINER)).not.toBeInTheDocument();
  });

  it("says there are no orders on a day without orders", async () => {
    farm.orders = {};
    renderPage();

    expect(await screen.findByText(NO_ORDERS)).toBeInTheDocument();
    expect(cardNames()).toEqual([]);
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("CommissioningListResellers render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Green Grocer");
    await flushMicrotasks();

    // About ten commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});
