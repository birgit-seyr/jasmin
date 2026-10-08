/**
 * DeliveryStationsOverview, the tour lists: for one delivery day of a week,
 * every tour that delivers, its stations in stop order and how many boxes of
 * each kind each station gets — or, for a farm that uploads its weekly share
 * amounts, how many shares of each size. Rendered through the real week and
 * day selectors, combination-column hook and PDF download button. The
 * generated commissioning client is the mocking boundary: its hooks are real
 * TanStack queries around spies that answer from an in-memory farm. The PDF
 * library, the PDF template and the browser download are stubbed, so no real
 * PDF is rendered.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The week state reads "today" when
 * the page mounts.
 */

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommissioningDeliveryStationToursOverviewRetrieveParams,
  CommissioningShareTypeVariationsListParams,
  DeliveryStationsToursOverviewResponse,
  SharesDeliveryDay,
  ShareTypeVariation,
  TourOverview,
} from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// The canonical mock with one `t` for every render, as react-i18next keeps it.
// It appends an interpolated `number`, so the tours read "… 1" and "… 2", and
// prints the share sizes S, M and L the way every locale does.
const i18nMock = vi.hoisted(() => {
  const sizes: Record<string, string> = {
    "commissioning.S": "S",
    "commissioning.M": "M",
    "commissioning.L": "L",
    "commissioning.HALF": "Half",
    "commissioning.FULL": "Full",
    "commissioning.ONE_SIZE": "One size",
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

// Phone or desktop viewport, per test.
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({
  useIsMobile: () => viewport.mobile,
}));

const api = vi.hoisted(() => ({
  deliveryDays: vi.fn(),
  shareSizes: vi.fn(),
  toursOverview: vi.fn(),
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
    useCommissioningSharesDeliveryDaysList: queryHook("shares_delivery_days", api.deliveryDays),
    useCommissioningShareTypeVariationsList: queryHook("share_type_variations", api.shareSizes),
    useCommissioningDeliveryStationToursOverviewRetrieve: queryHook(
      "delivery_station_tours_overview",
      api.toursOverview,
    ),
  };
});

// The page only needs its download button; the barrel would also load every
// other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  DeliveryStationsOverviewPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/DeliveryStationsOverviewPDFGenerator")
  ).default,
}));
vi.mock("@features/commissioning/pdfs/exports/DeliveryStationsOverviewPDF", () => ({
  default: function DeliveryStationsOverviewPDF() {
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

import DeliveryStationsOverview from "../DeliveryStationsOverview";
import {
  TUESDAY,
  WEDNESDAY,
  FRIDAY,
  deliveryDay,
  shareSize,
  shareColumn,
  shares,
  BREAD_ADD_ON,
  vegetables,
  box,
  SMALL,
  MEDIUM,
  MEDIUM_WITH_HONEY,
  HONEY_ONLY,
  BREAD,
  stop,
  tour,
  overview,
  FARM_SHOP,
  MARKET,
  SCHOOL,
  LIBRARY,
  TUESDAY_TOURS,
  UPLOADED_TUESDAY_TOURS,
  FRIDAY_TOURS,
  NEXT_TUESDAY_TOURS,
  scope,
} from "./deliveryStationsOverview.fixtures";

// ── Farm ────────────────────────────────────────────────────────────────────

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  deliveryDays: SharesDeliveryDay[];
  shareSizes: ShareTypeVariation[];
  overviews: Record<string, DeliveryStationsToursOverviewResponse>;
};

/** A day the farm holds no overview for has no deliveries. */
const answerFromFarm = async (params: CommissioningDeliveryStationToursOverviewRetrieveParams) => {
  const when = { year: params.year, week: params.delivery_week };
  return farm.overviews[scope(params.day_number, when)] ?? overview(params.day_number, [], when);
};

/** The exact query for a day of week 41; `scoped` overrides fields. */
const requestFor = (dayNumber: number, scoped: Record<string, unknown> = {}) =>
  ({ year: 2026, delivery_week: 41, day_number: dayNumber, ...scoped });

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  // The app shows a toast for every query that fails; here they are collected.
  const loadErrors = vi.fn();
  const queryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => loadErrors(error) }),
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<DeliveryStationsOverview />)}
    </QueryClientProvider>,
  );
  return { profiler, loadErrors };
}

const TITLE = "commissioning.tour_lists";
const DAY = "common.delivery_day";
const WEEK = "common.week";
const YEAR = "common.year";
const DOWNLOAD = /download\.deliveries_overview$/;
const NO_DELIVERIES = "commissioning.packing_list_no_columns";
const NO_DAYS_IN_WEEK = "commissioning.no_delivery_days_in_week";
const EXPLAINER = "explainers.delivery_stations_overview";
const STATION = "commissioning.delivery_station";
const NO_BASE = "commissioning.no_base_combination";
const TUESDAY_LABEL = "commissioning.delivery_day Tuesday, 06.10.2026";
const FRIDAY_LABEL = "commissioning.delivery_day Friday, 09.10.2026";
const TOUR = "commissioning.tour_number";
const TOUR_1 = `${TOUR} 1`;
const TOUR_2 = `${TOUR} 2`;

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

/** Opens a select and returns its options; AntD repeats short labels in a hidden list. */
async function openOptions(select: HTMLElement): Promise<HTMLElement[]> {
  await userEvent.click(within(select).getByRole("combobox"));
  return Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content"));
}

const optionsOf = async (select: HTMLElement) =>
  (await openOptions(select)).map((option) => option.textContent ?? "");

async function choose(select: HTMLElement, option: string) {
  const item = (await openOptions(select)).find((content) => content.textContent === option);
  if (!item) throw new Error(`No option ${option}`);
  await userEvent.click(item);
}

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

/** The headings of the tours shown, top to bottom. */
const tourHeadings = () =>
  screen.queryAllByRole("heading", { level: 3 }).map((heading) => heading.textContent ?? "");

/** The part of the page that holds one tour: its heading and its table. */
function tourSection(tourNumber: number): HTMLElement {
  const heading = screen.getByRole("heading", { level: 3, name: `${TOUR} ${tourNumber}` });
  if (!heading.parentElement) throw new Error(`No section for tour ${tourNumber}`);
  return heading.parentElement;
}

const textsOf = (cells: Iterable<Element>) =>
  Array.from(cells, (cell) => cell.textContent ?? "");

/** The header rows of a tour's table, top to bottom. */
const headerRowsOf = (tourNumber: number) =>
  Array.from(tourSection(tourNumber).querySelectorAll(".ant-table-thead > tr"), (row) =>
    textsOf(row.querySelectorAll("th")),
  );

/** Every station row of a tour's table, as the texts of its cells. */
const rowsOf = (tourNumber: number) =>
  Array.from(
    tourSection(tourNumber).querySelectorAll(".ant-table-tbody > tr.ant-table-row"),
    (row) => textsOf(row.querySelectorAll("td")),
  );

/** The spinner the page shows while it waits for the day's tours. */
const loadingSpinner = () => document.querySelector(".ant-spin-spinning");

const downloadButton = () => screen.getByRole("button", { name: DOWNLOAD });
const queryDownloadButton = () => screen.queryByRole("button", { name: DOWNLOAD });

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

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  printed.documents = [];
  printed.files = [];
  farm = {
    deliveryDays: [deliveryDay("day-tue", TUESDAY), deliveryDay("day-fri", FRIDAY)],
    shareSizes: [
      shareSize("veg", "S"),
      shareSize("veg", "M"),
      shareSize("honey", "S"),
      shareSize("bread", "L", true),
    ],
    overviews: {
      [scope(TUESDAY)]: overview(TUESDAY, TUESDAY_TOURS),
      [scope(FRIDAY)]: overview(FRIDAY, FRIDAY_TOURS),
      [scope(TUESDAY, { week: 42 })]: overview(TUESDAY, NEXT_TUESDAY_TOURS, { week: 42 }),
    },
  };
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.shareSizes
    .mockReset()
    .mockImplementation(async ({ is_packed_bulk }: CommissioningShareTypeVariationsListParams) =>
      farm.shareSizes.filter((size) => [undefined, size.is_packed_bulk].includes(is_packed_bulk)),
    );
  api.toursOverview.mockReset().mockImplementation(answerFromFarm);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("DeliveryStationsOverview loading", () => {
  it("opens on the week's first delivery day and asks once for its tours", async () => {
    renderPage();

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeInTheDocument();
    expect(screen.getByText("commissioning.tour_lists_subtitle")).toBeInTheDocument();
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 41");
    expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL);
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-10" });
    expect(api.shareSizes).toHaveBeenCalledWith({ is_packed_bulk: true });
    // Nothing is asked for before the day is known.
    expect(api.toursOverview.mock.calls).toEqual([[requestFor(TUESDAY)]]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });

  it("shows no tour, no hint and no download while the day's tours load", async () => {
    const tours = pending<DeliveryStationsToursOverviewResponse>();
    api.toursOverview.mockImplementation(() => tours.promise);
    renderPage();

    await waitFor(() => expect(api.toursOverview).toHaveBeenCalled());
    expect(tourHeadings()).toEqual([]);
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(queryDownloadButton()).not.toBeInTheDocument();

    tours.answer(overview(TUESDAY, TUESDAY_TOURS));

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(tourHeadings()).toEqual([TOUR_1, TOUR_2]);
    expect(downloadButton()).toBeEnabled();
  });

  it("shows a spinner, not the no-deliveries hint, while the week's delivery days load", async () => {
    const days = pending<SharesDeliveryDay[]>();
    api.deliveryDays.mockImplementation(() => days.promise);
    renderPage();

    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalled());
    expect(loadingSpinner()).toBeInTheDocument();
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(queryDownloadButton()).not.toBeInTheDocument();

    days.answer([...farm.deliveryDays]);

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(loadingSpinner()).not.toBeInTheDocument();
  });

  it("shows a spinner while the day's tours load", async () => {
    const tours = pending<DeliveryStationsToursOverviewResponse>();
    api.toursOverview.mockImplementation(() => tours.promise);
    renderPage();

    await waitFor(() => expect(api.toursOverview).toHaveBeenCalled());
    expect(loadingSpinner()).toBeInTheDocument();

    tours.answer(overview(TUESDAY, TUESDAY_TOURS));

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(loadingSpinner()).not.toBeInTheDocument();
  });
});

// ── Tours of boxes ──────────────────────────────────────────────────────────

describe("DeliveryStationsOverview tours", () => {
  it("lists each tour under its number, with its stations in stop order", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(tourHeadings()).toEqual([TOUR_1, TOUR_2]);
    expect(rowsOf(1).map(([name]) => name)).toEqual(["Farm shop", "Market"]);
    expect(rowsOf(2).map(([name]) => name)).toEqual(["School", "Town library"]);
  });

  it("groups each tour's kinds of box under their share type and counts them per station", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(headerRowsOf(1)).toEqual([
      [STATION, "Veg", NO_BASE],
      // The base share's size, then a badge per add-on packed into the box.
      ["S", "M", "MHoney·S", `${NO_BASE}Honey·S`],
    ]);
    // A station that gets none of a kind leaves its cell blank.
    expect(rowsOf(1)).toEqual([
      ["Farm shop", "12", "30", "5", ""],
      ["Market", "7", "8", "", "2"],
    ]);
    // The second tour shows only the kinds of box packed for it.
    expect(headerRowsOf(2)).toEqual([
      [STATION, "Veg"],
      ["S", "M"],
    ]);
    expect(rowsOf(2)).toEqual([
      ["School", "3", ""],
      ["Town library", "", "2"],
    ]);
  });

  it.each([
    ["de-DE", "1.250"],
    ["en-US", "1,250"],
  ])("writes the box counts in the farm's number format (%s)", async (locale, shown) => {
    tenantSettings.values = { number_locale: locale };
    const depot = stop("depot", 1, "Central depot", null, { [SMALL.key]: 980, [MEDIUM.key]: 1250 });
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [tour(1, [SMALL, MEDIUM], [depot])]);
    renderPage();
    await screen.findByText("Central depot");

    expect(rowsOf(1)).toEqual([["Central depot", "980", shown]]);
  });

  it("leaves out the boxes of a share size packed in bulk, on screen and on paper", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(headerRowsOf(1)[0]).not.toContain("Bread");
    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    const [firstTour] = printed.documents[0].props.tours as TourOverview[];
    expect(firstTour.columns).toEqual([MEDIUM_WITH_HONEY, SMALL, HONEY_ONLY, MEDIUM]);
  });

  it("shows the bread boxes once bread is packed into the boxes", async () => {
    farm.shareSizes = farm.shareSizes.map((size) => ({ ...size, is_packed_bulk: false }));
    renderPage();
    await screen.findByText("Farm shop");

    expect(headerRowsOf(1)).toEqual([
      [STATION, "Veg", "Bread", NO_BASE],
      ["S", "M", "MHoney·S", "L", `${NO_BASE}Honey·S`],
    ]);
    expect(rowsOf(1)).toEqual([
      ["Farm shop", "12", "30", "5", "4", ""],
      ["Market", "7", "8", "", "3", "2"],
    ]);
  });

  it("keeps a box of vegetables that carries bread packed in bulk", async () => {
    const withBread = box(vegetables("S", 1), [BREAD_ADD_ON], 3);
    const shop = stop("farm-shop", 1, "Farm shop", null, { [SMALL.key]: 9, [withBread.key]: 3 });
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [tour(1, [SMALL, withBread], [shop])]);
    renderPage();
    await screen.findByText("Farm shop");

    expect(headerRowsOf(1)).toEqual([
      [STATION, "Veg"],
      ["S", "SBread·L"],
    ]);
    expect(rowsOf(1)).toEqual([["Farm shop", "9", "3"]]);
  });

  it("drops a tour whose boxes are all packed in bulk, on screen and on paper", async () => {
    const bakery = stop("bakery", 1, "Bakery", null, { [BREAD.key]: 6 });
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [
      tour(1, [SMALL, MEDIUM], [SCHOOL, LIBRARY]),
      tour(2, [BREAD], [bakery]),
    ]);
    renderPage();
    await screen.findByText("School");

    expect(tourHeadings()).toEqual([TOUR_1]);
    expect(screen.queryByText("Bakery")).not.toBeInTheDocument();
    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.documents[0].props.tours).toEqual([
      { tour_number: 1, columns: [SMALL, MEDIUM], stations: [SCHOOL, LIBRARY] },
    ]);
  });

  it("says there are no deliveries, and offers no download, when the day's boxes are all packed in bulk", async () => {
    const bakery = stop("bakery", 1, "Bakery", null, { [BREAD.key]: 6 });
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [tour(1, [BREAD], [bakery])]);
    renderPage();
    await waitFor(() => expect(api.toursOverview).toHaveBeenCalled());
    await act(() => flushMicrotasks());

    expect(screen.getByText(NO_DELIVERIES)).toBeInTheDocument();
    expect(tourHeadings()).toEqual([]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(queryDownloadButton()).not.toBeInTheDocument();
  });
});

// ── Farms that upload their weekly share amounts ────────────────────────────

describe("DeliveryStationsOverview for a farm that uploads its weekly share amounts", () => {
  beforeEach(() => {
    tenantSettings.values = { uploads_weekly_share_amount: true };
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, UPLOADED_TUESDAY_TOURS);
  });

  it("shows a column per share size, grouped by share type, with each station's shares", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(api.toursOverview.mock.calls).toEqual([[requestFor(TUESDAY)]]);
    expect(tourHeadings()).toEqual([TOUR_1, TOUR_2]);
    // Bread is packed in bulk, so it has no column.
    expect(headerRowsOf(1)).toEqual([
      [STATION, "Vegetables", "Honey"],
      ["S", "M", "S"],
    ]);
    expect(rowsOf(1)).toEqual([
      ["Farm shop", "12", "35", "5"],
      ["Market", "7", "8", "2"],
    ]);
    // Every tour shows every share size of the day; none of a size leaves a blank.
    expect(headerRowsOf(2)).toEqual(headerRowsOf(1));
    expect(rowsOf(2)).toEqual([
      ["School", "3", "", ""],
      ["Town library", "", "2", ""],
    ]);
  });

  it("shows the bread shares once bread is packed into the boxes", async () => {
    farm.shareSizes = farm.shareSizes.map((size) => ({ ...size, is_packed_bulk: false }));
    renderPage();
    await screen.findByText("Farm shop");

    expect(headerRowsOf(1)).toEqual([
      [STATION, "Vegetables", "Bread", "Honey"],
      ["S", "M", "L", "S"],
    ]);
    expect(rowsOf(1)).toEqual([
      ["Farm shop", "12", "35", "4", "5"],
      ["Market", "7", "8", "3", "2"],
    ]);
  });

  it("offers no download", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(queryDownloadButton()).not.toBeInTheDocument();
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });

  it("names every share size by its label, not its code", async () => {
    const half = shareColumn("veg", "Vegetables", "HALF");
    const full = shareColumn("veg", "Vegetables", "FULL");
    const honey = shareColumn("honey", "Honey", "ONE_SIZE");
    const shop = stop("farm-shop", 1, "Farm shop", null, {
      [half.key]: 4,
      [full.key]: 6,
      [honey.key]: 2,
    });
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [tour(1, [], [shop])], {
      variations: [half, full, honey],
    });
    renderPage();
    await screen.findByText("Farm shop");

    expect(headerRowsOf(1)).toEqual([
      [STATION, "Vegetables", "Honey"],
      ["Half", "Full", "One size"],
    ]);
  });

  it.each([
    ["de-DE", "1.250"],
    ["en-US", "1,250"],
  ])("writes the share counts in the farm's number format (%s)", async (locale, shown) => {
    tenantSettings.values = { uploads_weekly_share_amount: true, number_locale: locale };
    const depot = stop("depot", 1, "Central depot", null, shares(980, 1250, 0, 3));
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [tour(1, [], [depot])]);
    renderPage();
    await screen.findByText("Central depot");

    expect(rowsOf(1)).toEqual([["Central depot", "980", shown, "3"]]);
  });

  it("drops a tour that delivers only shares packed in bulk", async () => {
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [
      UPLOADED_TUESDAY_TOURS[0],
      tour(2, [], [stop("bakery", 1, "Bakery", null, shares(0, 0, 6, 0))]),
    ]);
    renderPage();
    await screen.findByText("Farm shop");

    expect(tourHeadings()).toEqual([TOUR_1]);
    expect(screen.queryByText("Bakery")).not.toBeInTheDocument();
  });

  it("says there are no deliveries when the day's shares are all packed in bulk", async () => {
    farm.overviews[scope(TUESDAY)] = overview(TUESDAY, [
      tour(1, [], [stop("bakery", 1, "Bakery", null, shares(0, 0, 6, 0))]),
    ]);
    renderPage();
    await waitFor(() => expect(api.toursOverview).toHaveBeenCalled());
    await act(() => flushMicrotasks());

    expect(screen.getByText(NO_DELIVERIES)).toBeInTheDocument();
    expect(tourHeadings()).toEqual([]);
  });
});

// ── Day ─────────────────────────────────────────────────────────────────────

describe("DeliveryStationsOverview choosing the day", () => {
  it("offers the week's delivery days, each with its date", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(await optionsOf(selectNamed(DAY))).toEqual([TUESDAY_LABEL, FRIDAY_LABEL]);
  });

  it("dates the delivery days in the farm's date format", async () => {
    tenantSettings.values = { date_format: "YYYY-MM-DD" };
    renderPage();
    await screen.findByText("Farm shop");

    expect(await optionsOf(selectNamed(DAY))).toEqual([
      "commissioning.delivery_day Tuesday, 2026-10-06",
      "commissioning.delivery_day Friday, 2026-10-09",
    ]);
  });

  it("lists another day's tours, named after that day on paper, when the day changes", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    expect(await screen.findByText("Village hall")).toBeInTheDocument();
    expect(screen.queryByText("Farm shop")).not.toBeInTheDocument();
    expect(api.toursOverview.mock.calls).toEqual([[requestFor(TUESDAY)], [requestFor(FRIDAY)]]);
    // Friday's second tour delivers nothing, so only the first is listed.
    expect(tourHeadings()).toEqual([TOUR_1]);
    expect(rowsOf(1)).toEqual([["Village hall", "6", "9"]]);

    await userEvent.click(downloadButton());

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.deliveries_overview_2026_commissioning.KW41_COMMONWEEKDAYFRIDAY.pdf",
      ]),
    );
    expect(printed.documents[0].props).toMatchObject({
      week: 41,
      dayName: "COMMON.WEEKDAY_FRIDAY",
    });
  });

  it("steps to the next delivery day with the arrow", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    await userEvent.click(arrow(DAY, "common.next"));

    expect(await screen.findByText("Village hall")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(FRIDAY_LABEL);
    expect(api.toursOverview).toHaveBeenLastCalledWith(requestFor(FRIDAY));
    expect(arrow(DAY, "common.next")).toBeDisabled();
  });
});

// ── Week and year ───────────────────────────────────────────────────────────

describe("DeliveryStationsOverview choosing the week", () => {
  it("loads the next week's delivery days and tours from the week arrow", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(rowsOf(1)).toEqual([["Farm shop", "11", "31"]]));
    expect(tourHeadings()).toEqual([TOUR_1]);
    expect(api.deliveryDays.mock.calls).toEqual([
      [{ active_at_date: "2026-10-10" }],
      [{ active_at_date: "2026-10-17" }],
    ]);
    expect(api.toursOverview.mock.calls).toEqual([
      [requestFor(TUESDAY)],
      [requestFor(TUESDAY, { delivery_week: 42 })],
    ]);
    expect(shownIn(selectNamed(DAY))).toBe("commissioning.delivery_day Tuesday, 13.10.2026");
  });

  it("moves to the first delivery day of a week that delivers on other days", async () => {
    api.deliveryDays.mockImplementation(async ({ active_at_date }: { active_at_date: string }) =>
      active_at_date === "2026-10-17"
        ? [deliveryDay("day-wed", WEDNESDAY), deliveryDay("day-fri", FRIDAY)]
        : [...farm.deliveryDays],
    );
    const church = tour(1, [SMALL], [stop("church", 1, "Church", null, { [SMALL.key]: 5 })]);
    farm.overviews[scope(WEDNESDAY, { week: 42 })] = overview(WEDNESDAY, [church], { week: 42 });
    renderPage();
    await screen.findByText("Farm shop");

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await screen.findByText("Church")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe("commissioning.delivery_day Wednesday, 14.10.2026");
    // The week has no Tuesday, so the Tuesday picked before is never asked for.
    expect(api.toursOverview.mock.calls).toEqual([
      [requestFor(TUESDAY)],
      [requestFor(WEDNESDAY, { delivery_week: 42 })],
    ]);
  });

  it("asks for no tours, and says the week has no delivery days, in a week without one", async () => {
    api.deliveryDays.mockImplementation(async ({ active_at_date }: { active_at_date: string }) =>
      active_at_date === "2026-10-17" ? [] : [...farm.deliveryDays],
    );
    const { loadErrors } = renderPage();
    await screen.findByText("Farm shop");

    await userEvent.click(arrow(WEEK, "common.next"));

    expect(await screen.findByText(NO_DAYS_IN_WEEK)).toBeInTheDocument();
    expect(api.toursOverview.mock.calls).toEqual([[requestFor(TUESDAY)]]);
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(tourHeadings()).toEqual([]);
    expect(shownIn(selectNamed(DAY))).toBe("");
    expect(loadingSpinner()).not.toBeInTheDocument();
    expect(loadErrors).not.toHaveBeenCalled();

    // Back in a week with delivery days, its first day is picked again.
    await userEvent.click(arrow(WEEK, "common.previous"));

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL);
  });

  it("loads the same week of another year", async () => {
    const depot = tour(1, [SMALL], [stop("depot", 1, "New depot", null, { [SMALL.key]: 4 })]);
    farm.overviews[scope(TUESDAY, { year: 2027 })] = overview(TUESDAY, [depot], { year: 2027 });
    renderPage();
    await screen.findByText("Farm shop");

    await choose(selectNamed(YEAR), "2027");

    expect(await screen.findByText("New depot")).toBeInTheDocument();
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2027-10-16" });
    expect(api.toursOverview.mock.calls).toEqual([
      [requestFor(TUESDAY)],
      [requestFor(TUESDAY, { year: 2027 })],
    ]);
  });
});

// ── Nothing to show ─────────────────────────────────────────────────────────

describe("DeliveryStationsOverview with nothing to show", () => {
  it("says there are no deliveries, without a table or a download, when no box goes out", async () => {
    delete farm.overviews[scope(TUESDAY)];
    renderPage();

    await waitFor(() => expect(api.toursOverview).toHaveBeenCalled());
    expect(await screen.findByText(NO_DELIVERIES)).toBeInTheDocument();
    expect(api.toursOverview.mock.calls).toEqual([[requestFor(TUESDAY)]]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(tourHeadings()).toEqual([]);
    expect(queryDownloadButton()).not.toBeInTheDocument();
    expect(screen.getByText(EXPLAINER)).toBeInTheDocument();
  });

  it("says the week has no delivery days, and asks for no tours, in a week without one", async () => {
    farm.deliveryDays = [];
    renderPage();

    expect(await screen.findByText(NO_DAYS_IN_WEEK)).toBeInTheDocument();
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(loadingSpinner()).not.toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe("");
    expect(api.toursOverview).not.toHaveBeenCalled();
    expect(queryDownloadButton()).not.toBeInTheDocument();
  });
});

// ── Failures ────────────────────────────────────────────────────────────────

describe("DeliveryStationsOverview when the tours cannot be loaded", () => {
  it("shows none of another day's tours while loading or once loading failed, then recovers", async () => {
    const { loadErrors } = renderPage();
    await screen.findByText("Farm shop");
    const friday = pending<DeliveryStationsToursOverviewResponse>();
    api.toursOverview.mockImplementation(
      (params: CommissioningDeliveryStationToursOverviewRetrieveParams) =>
        params.day_number === FRIDAY ? friday.promise : answerFromFarm(params),
    );

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    await waitFor(() => expect(api.toursOverview).toHaveBeenLastCalledWith(requestFor(FRIDAY)));
    expect(tourHeadings()).toEqual([]);
    expect(screen.queryByText("Farm shop")).not.toBeInTheDocument();
    expect(queryDownloadButton()).not.toBeInTheDocument();

    friday.fail(new Error("Network Error"));

    // The failure reaches the app, which shows it as a toast.
    await waitFor(() => expect(loadErrors).toHaveBeenCalledWith(new Error("Network Error")));
    expect(tourHeadings()).toEqual([]);
    // The toast reports the failure; the day is not claimed to have no deliveries.
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(loadingSpinner()).not.toBeInTheDocument();
    expect(queryDownloadButton()).not.toBeInTheDocument();

    await choose(selectNamed(DAY), TUESDAY_LABEL);

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(tourHeadings()).toEqual([TOUR_1, TOUR_2]);
    expect(downloadButton()).toBeEnabled();
  });
});

// ── Download ────────────────────────────────────────────────────────────────

describe("DeliveryStationsOverview download", () => {
  it("prints every tour's stations and boxes as a PDF named after the week and day", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    await userEvent.click(downloadButton());

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.deliveries_overview_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf",
      ]),
    );
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("DeliveryStationsOverviewPDF");
    expect(props).toMatchObject({ week: 41, dayName: "COMMON.WEEKDAY_TUESDAY" });
    // The kinds of box in the server's order, without the bread packed in
    // bulk; the PDF groups and orders them itself.
    expect(props.tours).toEqual([
      {
        tour_number: 1,
        columns: [MEDIUM_WITH_HONEY, SMALL, HONEY_ONLY, MEDIUM],
        stations: [FARM_SHOP, MARKET],
      },
      { tour_number: 2, columns: [SMALL, MEDIUM], stations: [SCHOOL, LIBRARY] },
    ]);
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("DeliveryStationsOverview on a phone", () => {
  it("shows the same tour tables and download, with the day in the short phone format", async () => {
    viewport.mobile = true;
    renderPage();
    await screen.findByText("Farm shop");

    expect(shownIn(selectNamed(DAY))).toBe("Tu, 06.10.");
    expect(tourHeadings()).toEqual([TOUR_1, TOUR_2]);
    expect(rowsOf(1)).toEqual([
      ["Farm shop", "12", "30", "5", ""],
      ["Market", "7", "8", "", "2"],
    ]);
    expect(downloadButton()).toBeEnabled();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("DeliveryStationsOverview render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Farm shop");
    await flushMicrotasks();

    // A healthy run commits a handful of times; a setState-in-render loop
    // makes thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});
