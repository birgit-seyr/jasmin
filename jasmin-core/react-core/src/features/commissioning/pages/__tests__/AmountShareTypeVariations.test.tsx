/**
 * AmountShareTypeVariations: how many boxes of each kind go out in a week, one
 * row per delivery day, or per tour or per delivery station of each day when
 * the office asks for that split. The joker overview renders the same page in
 * joker mode and counts the boxes skipped with a joker instead. Rendered
 * through the real week selector, switches and combination-column hook. The
 * generated commissioning client is the mocking boundary: its hooks are real
 * TanStack queries around spies that answer from an in-memory farm with the
 * box-combination matrix the backend builds.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The week state reads "today" when
 * the page mounts.
 */

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
  PackingBoxesMatrixAddOn,
  PackingBoxesMatrixColumn,
  SharesDeliveryDay,
  WeeklyComboMatrixResponse,
  WeeklyComboMatrixRow,
} from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// The canonical mock with one `t` for every render, as react-i18next keeps it.
// It appends an interpolated `number`, so the weeks read "… 41", and prints
// the share sizes S, M and L the way every locale does.
const i18nMock = vi.hoisted(() => {
  const sizes: Record<string, string> = {
    "commissioning.S": "S",
    "commissioning.M": "M",
    "commissioning.L": "L",
  };
  return {
    t: (key: string, fallback?: unknown) => {
      if (typeof fallback === "string") return fallback;
      if (key in sizes) return sizes[key];
      const number = (fallback as { number?: unknown } | undefined)?.number;
      return number === undefined ? key : `${key} ${String(number)}`;
    },
  };
});
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

vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => false }));

const api = vi.hoisted(() => ({
  deliveryDays: vi.fn(), shareSizes: vi.fn(), boxMatrix: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      return useQuery({
        queryKey: [`/api/commissioning/${path}/`, ...(params ? [params] : [])],
        queryFn: async () => request(params),
        enabled: options?.query?.enabled,
      });
    };
  return {
    useCommissioningSharesDeliveryDaysList: queryHook("shares_delivery_days", api.deliveryDays),
    useCommissioningShareTypeVariationsList: queryHook("share_type_variations", api.shareSizes),
    useCommissioningShareDeliveryBoxCombinationMatrixRetrieve: queryHook(
      "share_delivery/box_combination_matrix",
      api.boxMatrix,
    ),
  };
});

import AmountShareTypeVariations from "../AmountShareTypeVariations";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Backend day numbers: 0 = Monday … 6 = Sunday.
const TUESDAY = 1;
const FRIDAY = 4;

type Stop = { id: string; name: string; tour: number };
const FARM_SHOP: Stop = { id: "ds-farm-shop", name: "Farm shop", tour: 1 };
const MARKET: Stop = { id: "ds-market", name: "Market", tour: 1 };
const SCHOOL: Stop = { id: "ds-school", name: "School", tour: 1 };
const LIBRARY: Stop = { id: "ds-library", name: "Library", tour: 2 };

/** A delivery day running all year, with the stations it serves. */
const deliveryDay = (dayNumber: number, tours: number, stops: Stop[]): SharesDeliveryDay => ({
  id: `day-${dayNumber}`,
  day_number: dayNumber as SharesDeliveryDay["day_number"],
  valid_from: "2026-01-05",
  valid_until: null,
  number_of_tours: tours,
  delivery_stations: stops.map((each, index) => ({
    id: each.id, short_name: each.name, tour_number: each.tour, stop_order: index + 1,
  })),
});

// Tuesday is served by one tour; Friday by two.
const TUESDAY_ONE_TOUR = deliveryDay(TUESDAY, 1, [FARM_SHOP, MARKET]);
const FRIDAY_TWO_TOURS = deliveryDay(FRIDAY, 2, [SCHOOL, LIBRARY]);
const FRIDAY_ONE_TOUR = deliveryDay(FRIDAY, 1, [SCHOOL, LIBRARY]);

const HONEY_SMALL: PackingBoxesMatrixAddOn = {
  variation_id: "var-honey-S",
  size: "S",
  sort_order: 1,
  share_type_id: "st-honey",
  share_type_short_name: "Honey",
  share_type_sort_index: 1,
};

/** A kind of box: a vegetable share of one size (or none) and the add-ons packed in. */
const box = (
  base: { size: "S" | "M"; sortOrder: number } | null,
  addOns: PackingBoxesMatrixAddOn[],
  count: number,
): PackingBoxesMatrixColumn => {
  const baseId = base ? `var-veg-${base.size}` : null;
  return {
    key: `combo_${baseId ?? "none"}|${addOns.map((addOn) => addOn.variation_id).join("-")}`,
    base_variation_id: baseId,
    base_size: base?.size ?? "",
    base_sort_order: base?.sortOrder ?? 0,
    base_share_type_id: base ? "st-veg" : null,
    base_share_type_name: base ? "Vegetables" : "",
    base_share_type_short_name: base ? "Veg" : "",
    // Boxes without a base share come after every share type.
    base_share_type_sort_index: base ? 0 : 99,
    add_ons: addOns,
    count,
  };
};

const SMALL = box({ size: "S", sortOrder: 1 }, [], 20);
const MEDIUM = box({ size: "M", sortOrder: 2 }, [], 50);
const MEDIUM_WITH_HONEY = box({ size: "M", sortOrder: 2 }, [HONEY_SMALL], 5);
/** The box of members who take honey but no vegetables. */
const HONEY_ONLY = box(null, [HONEY_SMALL], 2);
/** The week's kinds of box in the server's order; the page groups and orders them. */
const WEEK_41_COLUMNS = [MEDIUM_WITH_HONEY, HONEY_ONLY, SMALL, MEDIUM];

/** A row of the matrix: which delivery, and how many boxes of each kind it gets. */
type MatrixRow = WeeklyComboMatrixRow & Record<string, unknown>;
type Counts = Record<string, number>;

const counts = (small: number, medium: number, mediumWithHoney = 0, honeyOnly = 0): Counts => ({
  ...(small ? { [SMALL.key]: small } : {}),
  ...(medium ? { [MEDIUM.key]: medium } : {}),
  ...(mediumWithHoney ? { [MEDIUM_WITH_HONEY.key]: mediumWithHoney } : {}),
  ...(honeyOnly ? { [HONEY_ONLY.key]: honeyOnly } : {}),
});

const dayRow = (dayNumber: number, boxes: Counts): MatrixRow => ({
  id: `day-${dayNumber}`, day_number: dayNumber, tour: null,
  delivery_station_id: null, delivery_station_name: null, ...boxes,
});
const tourRow = (dayNumber: number, tour: number, boxes: Counts): MatrixRow => ({
  ...dayRow(dayNumber, boxes), id: `day-${dayNumber}_tour_${tour}`, tour,
});
const stationRow = (dayNumber: number, stop: Stop, boxes: Counts): MatrixRow => ({
  ...dayRow(dayNumber, boxes),
  id: `day-${dayNumber}_station_${stop.id}`,
  delivery_station_id: stop.id,
  delivery_station_name: stop.name,
});

type Split = "day" | "tours" | "stations";
type Counted = "shipped" | "jokered";

/** Where a matrix belongs: a week, how its days are split, and which boxes it counts. */
const scope = (week: number, split: Split = "day", counted: Counted = "shipped", year = 2026) =>
  `${year}/${week}/${split}/${counted}`;

const matrix = (columns: PackingBoxesMatrixColumn[], rows: MatrixRow[]): WeeklyComboMatrixResponse => ({
  columns,
  rows,
});

// Week 41: every box shipped, then the boxes skipped with a joker.
const WEEK_41 = matrix(WEEK_41_COLUMNS, [
  dayRow(TUESDAY, counts(12, 30, 5, 2)),
  dayRow(FRIDAY, counts(8, 20)),
]);
const WEEK_41_PER_TOUR = matrix(WEEK_41_COLUMNS, [
  tourRow(TUESDAY, 1, counts(12, 30, 5, 2)),
  tourRow(FRIDAY, 1, counts(5, 12)),
  tourRow(FRIDAY, 2, counts(3, 8)),
]);
const WEEK_41_PER_STATION = matrix(WEEK_41_COLUMNS, [
  stationRow(TUESDAY, FARM_SHOP, counts(7, 18, 5)),
  stationRow(TUESDAY, MARKET, counts(5, 12, 0, 2)),
  stationRow(FRIDAY, SCHOOL, counts(5, 12)),
  stationRow(FRIDAY, LIBRARY, counts(3, 8)),
]);
const WEEK_41_JOKERED = matrix([SMALL, MEDIUM], [
  dayRow(TUESDAY, counts(0, 3)),
  dayRow(FRIDAY, counts(1, 0)),
]);
const WEEK_41_JOKERED_PER_STATION = matrix([SMALL, MEDIUM], [
  stationRow(TUESDAY, FARM_SHOP, counts(0, 2)),
  stationRow(TUESDAY, MARKET, counts(0, 1)),
  stationRow(FRIDAY, SCHOOL, counts(1, 0)),
]);
const WEEK_42 = matrix([SMALL, MEDIUM], [dayRow(TUESDAY, counts(11, 31))]);

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  deliveryDays: SharesDeliveryDay[];
  matrices: Record<string, WeeklyComboMatrixResponse>;
};

type MatrixParams = CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams;

/** A week the farm holds no matrix for ships no box. */
const answerFromFarm = async (params: MatrixParams) => {
  const split: Split = params.for_stations ? "stations" : params.for_tours ? "tours" : "day";
  const counted: Counted = params.joker ? "jokered" : "shipped";
  return (
    farm.matrices[scope(params.delivery_week, split, counted, params.year)] ?? { columns: [], rows: [] }
  );
};

/** The exact matrix request for a week of 2026; ``asked`` adds the switches. */
const requestFor = (week: number, asked: Partial<MatrixParams> = {}) => ({
  year: 2026,
  delivery_week: week,
  ...asked,
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage({ jokerMode = false } = {}) {
  const profiler = profileRenders();
  // The app shows a toast for every query that fails; here they are collected.
  const loadErrors = vi.fn();
  const queryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => loadErrors(error) }),
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<AmountShareTypeVariations jokerMode={jokerMode} />)}
    </QueryClientProvider>,
  );
  return { profiler, loadErrors };
}

const TITLE = "commissioning.amount_share_type_variations";
const JOKER_TITLE = "abos.overview_jokers";
const WEEK = "common.week";
const DELIVERY = "commissioning.delivery_day";
const NO_BASE = "commissioning.no_base_combination";
const NO_DELIVERIES = "commissioning.packing_list_no_columns";
const SHOW_TOURS = "commissioning.show_tours";
const SHOW_STATIONS = "commissioning.show_delivery_stations";
const EXPLAINER = "explainers.amount_share_type_variations";
const JOKER_EXPLAINER = "explainers.amount_jokers";

/** The label a select shows for its current value. */
const shownIn = (name: string) =>
  screen
    .getByRole("combobox", { name })
    .closest(".ant-select")
    ?.querySelector(".ant-select-selection-item")?.textContent ?? "";

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

const textsOf = (cells: Iterable<Element>) => Array.from(cells, (cell) => cell.textContent ?? "");

/** The header rows of the table, top to bottom. */
const headerRows = () =>
  Array.from(document.querySelectorAll(".ant-table-thead > tr"), (row) => textsOf(row.querySelectorAll("th")));

/** Every row of the table, as the texts of its cells. */
const rows = () =>
  Array.from(document.querySelectorAll(".ant-table-tbody > tr.ant-table-row"), (row) =>
    textsOf(row.querySelectorAll("td")),
  );

const toursSwitch = () => screen.queryByRole("switch", { name: SHOW_TOURS });
const stationsSwitch = () => screen.queryByRole("switch", { name: SHOW_STATIONS });

const isBusy = () => document.querySelector('[aria-busy="true"]') !== null;

/** A request that answers or fails only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  let fail!: (error: Error) => void;
  const promise = new Promise<T>((resolve, reject) => {
    answer = resolve;
    fail = reject;
  });
  return { promise, answer, fail };
}

const lastMatrixRequest = () => api.boxMatrix.mock.lastCall?.[0];

/** The whole-day rows of week 41, as the table shows them. */
const WEEK_41_ROWS = [
  ["commissioning.weekdays.1", "12", "30", "5", "2"],
  ["commissioning.weekdays.4", "8", "20", "", ""],
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  farm = {
    deliveryDays: [TUESDAY_ONE_TOUR, FRIDAY_TWO_TOURS],
    matrices: {
      [scope(41)]: WEEK_41,
      [scope(41, "tours")]: WEEK_41_PER_TOUR,
      [scope(41, "stations")]: WEEK_41_PER_STATION,
      [scope(41, "day", "jokered")]: WEEK_41_JOKERED,
      [scope(41, "stations", "jokered")]: WEEK_41_JOKERED_PER_STATION,
      [scope(42)]: WEEK_42,
    },
  };
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.shareSizes.mockReset().mockResolvedValue([]);
  api.boxMatrix.mockReset().mockImplementation(answerFromFarm);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("AmountShareTypeVariations loading", () => {
  it("opens on this week and counts the boxes of each kind per delivery day", async () => {
    renderPage();

    await waitFor(() => expect(rows()).toEqual(WEEK_41_ROWS));
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeInTheDocument();
    expect(shownIn("common.year")).toBe("2026");
    expect(shownIn(WEEK)).toBe("commissioning.week_short 41");
    expect(api.boxMatrix.mock.calls).toEqual([[requestFor(41)]]);
    // The week's delivery days decide whether the days can be split per tour.
    expect(api.deliveryDays).toHaveBeenCalledWith({
      active_at_date: "2026-10-10", get_delivery_stations: true, need_info_on_tours: true,
    });
    expect(api.shareSizes).not.toHaveBeenCalled();
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });

  it("shows a spinner over the table while the boxes load", async () => {
    const week = pending<WeeklyComboMatrixResponse>();
    api.boxMatrix.mockImplementation(() => week.promise);
    renderPage();

    await waitFor(() => expect(isBusy()).toBe(true));
    expect(rows()).toEqual([]);
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();

    week.answer(WEEK_41);

    await waitFor(() => expect(rows()).toEqual(WEEK_41_ROWS));
    await waitFor(() => expect(isBusy()).toBe(false));
  });

  it("says there are no deliveries, without the table or the switches, in a week without boxes", async () => {
    delete farm.matrices[scope(41)];
    renderPage();

    expect(await screen.findByText(NO_DELIVERIES)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(toursSwitch()).not.toBeInTheDocument();
    expect(stationsSwitch()).not.toBeInTheDocument();
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });
});

// ── The counts ──────────────────────────────────────────────────────────────

describe("AmountShareTypeVariations counts", () => {
  it("groups the kinds of box under their share type, the boxes without a base share last", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    expect(headerRows()).toEqual([
      [DELIVERY, "Veg", NO_BASE],
      // The base share's size, then a badge per add-on packed into the box.
      ["S", "M", "MHoney·S", `${NO_BASE}Honey·S`],
    ]);
    // A day without a kind of box leaves its cell blank.
    expect(rows()).toEqual(WEEK_41_ROWS);
  });

  it.each([
    ["de-DE", "1.250"],
    ["en-US", "1,250"],
  ])("writes the box counts in the farm's number format (%s)", async (locale, shown) => {
    tenantSettings.values = { number_locale: locale };
    farm.matrices[scope(41)] = matrix([SMALL, MEDIUM], [dayRow(TUESDAY, counts(980, 1250))]);
    renderPage();

    await waitFor(() => expect(rows()).toEqual([["commissioning.weekdays.1", "980", shown]]));
  });

  it("shows a column per share size for a farm that imports its weekly shares", async () => {
    const shareSize = (shareType: string, shortName: string, size: string, sortOrder: number, sortIndex: number) =>
      ({
        ...box(null, [], 0),
        key: `variation_var-${shareType}-${size}`,
        base_variation_id: `var-${shareType}-${size}`,
        base_size: size,
        base_sort_order: sortOrder,
        base_share_type_id: `st-${shareType}`,
        base_share_type_name: shortName,
        base_share_type_short_name: shortName,
        base_share_type_sort_index: sortIndex,
      }) satisfies PackingBoxesMatrixColumn;
    const vegetablesS = shareSize("veg", "Veg", "S", 1, 0);
    const vegetablesM = shareSize("veg", "Veg", "M", 2, 0);
    const honeyS = shareSize("honey", "Honey", "S", 1, 1);
    farm.matrices[scope(41)] = matrix([honeyS, vegetablesM, vegetablesS], [
      dayRow(TUESDAY, { [vegetablesS.key]: 14, [vegetablesM.key]: 33, [honeyS.key]: 6 }),
      dayRow(FRIDAY, { [vegetablesS.key]: 9 }),
    ]);
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    expect(headerRows()).toEqual([
      [DELIVERY, "Veg", "Honey"],
      ["S", "M", "S"],
    ]);
    expect(rows()).toEqual([
      ["commissioning.weekdays.1", "14", "33", "6"],
      ["commissioning.weekdays.4", "9", "", ""],
    ]);
  });
});

// ── Tours and stations ──────────────────────────────────────────────────────

describe("AmountShareTypeVariations splitting the days", () => {
  it("offers to split the days per tour in a week with a delivery day of more than one tour", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    expect(toursSwitch()).toBeInTheDocument();
    expect(toursSwitch()).not.toBeChecked();
    expect(stationsSwitch()).toBeInTheDocument();
    expect(stationsSwitch()).not.toBeChecked();
  });

  it("offers no tours when every delivery day of the week has a single tour", async () => {
    farm.deliveryDays = [TUESDAY_ONE_TOUR, FRIDAY_ONE_TOUR];
    renderPage();
    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalled());
    await waitFor(() => expect(rows()).toHaveLength(2));

    expect(toursSwitch()).not.toBeInTheDocument();
    expect(stationsSwitch()).toBeInTheDocument();
  });

  it("splits each day per tour when the tours are shown", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    await userEvent.click(toursSwitch()!);

    await waitFor(() =>
      expect(rows()).toEqual([
        ["commissioning.weekdays.1 · T1", "12", "30", "5", "2"],
        ["commissioning.weekdays.4 · T1", "5", "12", "", ""],
        ["commissioning.weekdays.4 · T2", "3", "8", "", ""],
      ]),
    );
    expect(lastMatrixRequest()).toEqual(requestFor(41, { for_tours: true }));
    expect(toursSwitch()).toBeChecked();
  });

  it("splits each day per delivery station when the stations are shown", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    await userEvent.click(stationsSwitch()!);

    await waitFor(() =>
      expect(rows()).toEqual([
        ["commissioning.weekdays.1 · Farm shop", "7", "18", "5", ""],
        ["commissioning.weekdays.1 · Market", "5", "12", "", "2"],
        ["commissioning.weekdays.4 · School", "5", "12", "", ""],
        ["commissioning.weekdays.4 · Library", "3", "8", "", ""],
      ]),
    );
    expect(lastMatrixRequest()).toEqual(requestFor(41, { for_stations: true }));
  });

  it("splits the days per tour or per station, never both at once", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    await userEvent.click(toursSwitch()!);
    await waitFor(() => expect(lastMatrixRequest()).toEqual(requestFor(41, { for_tours: true })));
    await userEvent.click(stationsSwitch()!);

    await waitFor(() => expect(lastMatrixRequest()).toEqual(requestFor(41, { for_stations: true })));
    expect(toursSwitch()).not.toBeChecked();
    expect(stationsSwitch()).toBeChecked();
    await waitFor(() => expect(rows()).toHaveLength(4));

    await userEvent.click(toursSwitch()!);

    await waitFor(() => expect(lastMatrixRequest()).toEqual(requestFor(41, { for_tours: true })));
    expect(stationsSwitch()).not.toBeChecked();
    await waitFor(() => expect(rows()).toHaveLength(3));
    // No request ever asked for both splits.
    expect(api.boxMatrix.mock.calls.some(([params]) => params.for_tours && params.for_stations)).toBe(false);
  });

  it("counts whole days in a week of single-tour days though the tours were shown in the week before", async () => {
    // Week 42 (from Saturday 17 October) is served by a single Tuesday tour.
    api.deliveryDays.mockImplementation(async (params: { active_at_date: string }) =>
      params.active_at_date === "2026-10-17" ? [TUESDAY_ONE_TOUR] : [...farm.deliveryDays],
    );
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));
    await userEvent.click(toursSwitch()!);
    await waitFor(() => expect(rows()).toHaveLength(3));

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(rows()).toEqual([["commissioning.weekdays.1", "11", "31"]]));
    expect(toursSwitch()).not.toBeInTheDocument();
    expect(lastMatrixRequest()).toEqual(requestFor(42));
    const week42Requests = api.boxMatrix.mock.calls.filter(([params]) => params.delivery_week === 42);
    expect(week42Requests.some(([params]) => params.for_tours)).toBe(false);
  });

  it("waits for the next week's delivery days before counting it per tour", async () => {
    const nextWeekDays = pending<SharesDeliveryDay[]>();
    api.deliveryDays.mockImplementation((params: { active_at_date: string }) =>
      params.active_at_date === "2026-10-17" ? nextWeekDays.promise : Promise.resolve([...farm.deliveryDays]),
    );
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));
    await userEvent.click(toursSwitch()!);
    await waitFor(() => expect(rows()).toHaveLength(3));

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(isBusy()).toBe(true));
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(api.boxMatrix.mock.calls.some(([params]) => params.delivery_week === 42)).toBe(false);

    nextWeekDays.answer([TUESDAY_ONE_TOUR]);

    await waitFor(() => expect(rows()).toEqual([["commissioning.weekdays.1", "11", "31"]]));
    expect(api.boxMatrix.mock.calls.filter(([params]) => params.delivery_week === 42)).toEqual([[requestFor(42)]]);
  });

  it("goes back to whole days when the split is turned off", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));
    await userEvent.click(stationsSwitch()!);
    await waitFor(() => expect(rows()).toHaveLength(4));

    await userEvent.click(stationsSwitch()!);

    await waitFor(() => expect(rows()).toEqual(WEEK_41_ROWS));
    expect(stationsSwitch()).not.toBeChecked();
    expect(lastMatrixRequest()).toEqual(requestFor(41));
  });
});

// ── Week ────────────────────────────────────────────────────────────────────

describe("AmountShareTypeVariations choosing the week", () => {
  it("loads the next week's boxes and delivery days from the week arrow", async () => {
    renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(rows()).toEqual([["commissioning.weekdays.1", "11", "31"]]));
    expect(headerRows()).toEqual([
      [DELIVERY, "Veg"],
      ["S", "M"],
    ]);
    expect(lastMatrixRequest()).toEqual(requestFor(42));
    expect(api.deliveryDays).toHaveBeenLastCalledWith({
      active_at_date: "2026-10-17", get_delivery_stations: true, need_info_on_tours: true,
    });
  });

  it("shows none of another week's counts while it loads or once it failed to load, then recovers", async () => {
    const { loadErrors } = renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));
    const nextWeek = pending<WeeklyComboMatrixResponse>();
    api.boxMatrix.mockImplementation((params: MatrixParams) =>
      params.delivery_week === 42 ? nextWeek.promise : answerFromFarm(params),
    );

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(lastMatrixRequest()).toEqual(requestFor(42)));
    await waitFor(() => expect(isBusy()).toBe(true));
    expect(rows()).toEqual([]);

    nextWeek.fail(new Error("Network Error"));

    // The failure reaches the app, which shows it as a toast.
    await waitFor(() => expect(loadErrors).toHaveBeenCalledWith(new Error("Network Error")));
    expect(rows()).toEqual([]);

    await userEvent.click(arrow(WEEK, "common.previous"));

    await waitFor(() => expect(rows()).toEqual(WEEK_41_ROWS));
  });
});

// ── Joker mode ──────────────────────────────────────────────────────────────

describe("AmountShareTypeVariations in joker mode", () => {
  it("counts the boxes skipped with a joker under the joker overview's title", async () => {
    renderPage({ jokerMode: true });

    await waitFor(() =>
      expect(rows()).toEqual([
        ["commissioning.weekdays.1", "", "3"],
        ["commissioning.weekdays.4", "1", ""],
      ]),
    );
    expect(screen.getByRole("heading", { level: 1, name: JOKER_TITLE })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: TITLE })).not.toBeInTheDocument();
    expect(api.boxMatrix.mock.calls).toEqual([[requestFor(41, { joker: true })]]);
    expect(screen.getByText(JOKER_EXPLAINER)).toBeInTheDocument();
    expect(screen.queryByText(EXPLAINER)).not.toBeInTheDocument();
  });

  it("keeps counting the jokered boxes when the days are split per station", async () => {
    renderPage({ jokerMode: true });
    await waitFor(() => expect(rows()).toHaveLength(2));

    await userEvent.click(stationsSwitch()!);

    await waitFor(() =>
      expect(rows()).toEqual([
        ["commissioning.weekdays.1 · Farm shop", "", "2"],
        ["commissioning.weekdays.1 · Market", "", "1"],
        ["commissioning.weekdays.4 · School", "1", ""],
      ]),
    );
    expect(lastMatrixRequest()).toEqual(requestFor(41, { joker: true, for_stations: true }));
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("AmountShareTypeVariations render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await waitFor(() => expect(rows()).toHaveLength(2));
    await flushMicrotasks();

    // About 5 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(60);
  });
});
