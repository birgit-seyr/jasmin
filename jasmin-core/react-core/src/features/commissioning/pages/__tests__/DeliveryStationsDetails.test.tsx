/**
 * DeliveryStationsDetails, the pickup lists: for one delivery station on one
 * delivery day, which member collects which boxes, with PDF downloads for that
 * station, for every station of the day and for every station of the week.
 * Rendered through its entry in the commissioning route table (role gate and
 * lazily loaded page) with the real week, day and station selectors, the
 * box-combination columns and the download buttons. The generated
 * commissioning client is the mocking boundary: its hooks are real TanStack
 * queries around spies that answer from an in-memory farm. The PDF library,
 * the PDF template and the browser download are stubbed, so no real PDF is
 * rendered.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The week state reads "today" when
 * the page mounts.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DeliveryStation,
  PackingBoxesMatrix,
  SharesDeliveryDay,
  StationMemberMatrix,
} from "@shared/api/generated/models";
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
const tenantSettings = vi.hoisted(() => ({
  values: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    tenantName: "Green Acres",
    logoUrl: "https://example.test/logo.png",
    tenant: { email: "office@example.test", phone_number: "+49 30 1234567" },
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// The signed-in user's roles, per test.
const session = vi.hoisted(() => ({ roles: [] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: { roles: session.roles },
    isAuthenticated: true,
    loading: false,
  }),
}));

const api = vi.hoisted(() => ({
  deliveryDays: vi.fn(),
  stations: vi.fn(),
  pickups: vi.fn(),
  memberAmounts: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryOptions =
    (path: string, request: (params: unknown) => unknown) =>
    (params?: unknown, options?: { query?: { enabled?: boolean } }) => ({
      queryKey: [`/api/commissioning/${path}/`, ...(params ? [params] : [])],
      queryFn: async () => request(params),
      ...options?.query,
    });
  const queryHook = (path: string, request: (params: unknown) => unknown) => {
    const optionsFor = queryOptions(path, request);
    return function useGeneratedQuery(
      params?: unknown,
      options?: { query?: { enabled?: boolean } },
    ) {
      return useQuery(optionsFor(params, options));
    };
  };
  return {
    useCommissioningSharesDeliveryDaysList: queryHook(
      "shares_delivery_days",
      api.deliveryDays,
    ),
    useCommissioningDeliveryStationsList: queryHook(
      "delivery_stations",
      api.stations,
    ),
    getCommissioningDeliveryStationsListQueryOptions: queryOptions(
      "delivery_stations",
      api.stations,
    ),
    useCommissioningShareDeliveryDetailsMatrixRetrieve: queryHook(
      "share_delivery_details/matrix",
      api.pickups,
    ),
    getCommissioningShareDeliveryDetailsMatrixRetrieveQueryOptions: queryOptions(
      "share_delivery_details/matrix",
      api.pickups,
    ),
    useCommissioningPackingListMemberAmountsRetrieve: queryHook(
      "packing_list/member_amounts",
      api.memberAmounts,
    ),
    getCommissioningPackingListMemberAmountsRetrieveQueryOptions: queryOptions(
      "packing_list/member_amounts",
      api.memberAmounts,
    ),
  };
});

// The page only needs its download button; the barrel would also load every
// other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  DeliveryStationDetailsPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/DeliveryStationDetailsPDFGenerator")
  ).default,
}));
vi.mock("@features/commissioning/pdfs/exports/DeliveryStationDetailsPDF", () => ({
  default: function DeliveryStationDetailsPDF() {
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

import { commissioningRoutes } from "@app/routing/routes/commissioning";
// Loaded up front so the route's lazy import resolves at once rather than
// inside the first test's time budget.
import "../DeliveryStationsDetails";
import {
  TUESDAY,
  FRIDAY,
  deliveryDay,
  FARM_SHOP,
  MARKET,
  SCHOOL,
  CHURCH_HALL,
  HONEY_M,
  BREAD_L,
  BREAD_ONLY,
  SMALL,
  MEDIUM_WITH_HONEY,
  FARM_SHOP_TUESDAY,
  MARKET_TUESDAY,
  MARKET_FRIDAY,
  SCHOOL_FRIDAY,
  FARM_SHOP_FRIDAY,
  FARM_SHOP_NEXT_TUESDAY,
  CARROTS,
  FARM_SHOP_TAKE,
  CARROTS_ON_THE_SHEET,
} from "./deliveryStationsDetails.fixtures";

// ── Fixtures ────────────────────────────────────────────────────────────────

type ListParams = {
  year: number;
  delivery_week: number;
  day_number: number;
  delivery_station: string;
  is_packed_bulk?: boolean;
};

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  deliveryDays: SharesDeliveryDay[];
  stationsByDeliveryDay: Record<string, DeliveryStation[]>;
  pickups: Record<string, StationMemberMatrix>;
  memberAmounts: Record<string, PackingBoxesMatrix>;
};

/** The week, delivery day and station a pickup list belongs to. */
const listOf = (week: number, dayNumber: number, stationOfList: DeliveryStation) =>
  `${week}/${dayNumber}/${stationOfList.id}`;
const listAskedFor = (params: ListParams) =>
  `${params.delivery_week}/${params.day_number}/${params.delivery_station}`;

const answerPickups = async (params: ListParams): Promise<StationMemberMatrix> =>
  farm.pickups[listAskedFor(params)] ?? { columns: [], rows: [] };

// ── Helpers ─────────────────────────────────────────────────────────────────

const PATH = "/commissioning/delivery-stations-details";

function renderPage() {
  const route = commissioningRoutes.find((entry) => entry.path === PATH);
  if (!route) throw new Error(`No route for ${PATH}`);
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[PATH]}>
        <Suspense fallback={null}>
          <Routes>
            <Route path={PATH} element={profiler.wrap(route.element)} />
          </Routes>
        </Suspense>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { profiler };
}

const DAY = "common.delivery_day";
const STATION = "placeholder.delivery_station_selector";
const WEEK = "common.week";
const TUESDAY_LABEL = "commissioning.delivery_day Tuesday, 06.10.2026";
const FRIDAY_LABEL = "commissioning.delivery_day Friday, 09.10.2026";
const STATION_PDF = /download\.delivery_details_station$/;
const DAY_PDF = /download\.all_pdf_for_this_day$/;
const WEEK_PDF = /download\.all_pdf_for_this_week$/;
const TENANT_ON_THE_PDF = {
  name: "Green Acres",
  logoUrl: "https://example.test/logo.png",
  email: "office@example.test",
  phone: "+49 30 1234567",
};

const download = (name: RegExp) => screen.getByRole("button", { name });

/** The label a selector shows for its current value. */
function selectedIn(name: string): string {
  const select = screen.getByRole("combobox", { name }).closest(".ant-select");
  return select?.querySelector(".ant-select-selection-item")?.textContent ?? "";
}

function openDropdown(): HTMLElement {
  const open = Array.from(
    document.querySelectorAll<HTMLElement>(".ant-select-dropdown"),
  ).filter((dropdown) => !dropdown.classList.contains("ant-select-dropdown-hidden"));
  const dropdown = open[open.length - 1];
  if (!dropdown) throw new Error("No select dropdown is open");
  return dropdown;
}

async function optionsOf(name: string): Promise<string[]> {
  await userEvent.click(screen.getByRole("combobox", { name }));
  return Array.from(
    openDropdown().querySelectorAll(".ant-select-item-option-content"),
  ).map((option) => option.textContent ?? "");
}

async function choose(name: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name }));
  await userEvent.click(within(openDropdown()).getByText(option));
}

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

function bodyRows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"),
  );
}

/** What each member's row shows, cell by cell. */
const tableRows = () =>
  bodyRows().map((row) =>
    Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent ?? ""),
  );

/** The text of every header cell, top header row first. */
const headerRows = () =>
  Array.from(document.querySelectorAll(".ant-table-thead > tr")).map((row) =>
    Array.from(row.querySelectorAll("th")).map((cell) => cell.textContent ?? ""),
  );

const tableIsBusy = () =>
  document.querySelector('.ant-table-wrapper [aria-busy="true"]') !== null;

/** Let pending requests answer and the page re-render. */
const settle = () => act(() => flushMicrotasks());

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

/** The one document printed so far. */
function printedDocument() {
  expect(printed.documents).toHaveLength(1);
  const [document] = printed.documents;
  expect(document.template).toBe("DeliveryStationDetailsPDF");
  return document.props;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  session.roles = ["office"];
  printed.documents = [];
  printed.files = [];
  farm = {
    deliveryDays: [deliveryDay("day-tue", TUESDAY), deliveryDay("day-fri", FRIDAY)],
    stationsByDeliveryDay: {
      "day-tue": [FARM_SHOP, MARKET],
      "day-fri": [SCHOOL, MARKET],
    },
    pickups: {
      [listOf(41, TUESDAY, FARM_SHOP)]: FARM_SHOP_TUESDAY,
      [listOf(41, TUESDAY, MARKET)]: MARKET_TUESDAY,
      [listOf(41, FRIDAY, SCHOOL)]: SCHOOL_FRIDAY,
      [listOf(41, FRIDAY, MARKET)]: MARKET_FRIDAY,
      [listOf(42, TUESDAY, FARM_SHOP)]: FARM_SHOP_NEXT_TUESDAY,
    },
    memberAmounts: { [listOf(41, TUESDAY, FARM_SHOP)]: FARM_SHOP_TAKE },
  };
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.stations
    .mockReset()
    .mockImplementation(async (params: { delivery_day?: string }) => [
      ...(farm.stationsByDeliveryDay[params.delivery_day ?? ""] ?? []),
    ]);
  api.pickups.mockReset().mockImplementation(answerPickups);
  api.memberAmounts
    .mockReset()
    .mockImplementation(
      async (params: ListParams) =>
        farm.memberAmounts[listAskedFor(params)] ?? { columns: [], rows: [] },
    );
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("DeliveryStationsDetails loading", () => {
  it("opens on the week's first delivery day and that day's first station, and lists its pickups", async () => {
    renderPage();

    expect(await screen.findByText("Ana Example")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "commissioning.delivery_notes_delivery_stations_details_title",
      }),
    ).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe(TUESDAY_LABEL);
    expect(selectedIn(STATION)).toBe("Farm shop");
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-10" });
    expect(api.stations).toHaveBeenCalledWith({ is_active: true, delivery_day: "day-tue" });
    expect(api.pickups).toHaveBeenCalledWith({
      year: 2026,
      delivery_week: 41,
      day_number: TUESDAY,
      delivery_station: FARM_SHOP.id,
    });
    expect(api.memberAmounts).toHaveBeenCalledWith({
      year: 2026,
      delivery_week: 41,
      day_number: TUESDAY,
      delivery_station: FARM_SHOP.id,
      is_packed_bulk: true,
    });
    expect(screen.getByText("explainers.delivery_stations_details")).toBeInTheDocument();
  });

  it("asks for a delivery station and loads no list until the day's stations are known", async () => {
    const stations = pending<DeliveryStation[]>();
    api.stations.mockImplementation(() => stations.promise);
    renderPage();

    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    expect(screen.getByText("commissioning.select_delivery_station")).toBeInTheDocument();
    expect(api.pickups).not.toHaveBeenCalled();
    expect(api.memberAmounts).not.toHaveBeenCalled();

    stations.answer([FARM_SHOP, MARKET]);

    expect(await screen.findByText("Ana Example")).toBeInTheDocument();
    expect(
      screen.queryByText("commissioning.select_delivery_station"),
    ).not.toBeInTheDocument();
  });

  it("shows a spinner over the table while the station's list loads", async () => {
    const pickups = pending<StationMemberMatrix>();
    api.pickups.mockImplementationOnce(() => pickups.promise);
    renderPage();

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);
    expect(download(STATION_PDF)).toBeDisabled();

    pickups.answer(FARM_SHOP_TUESDAY);

    expect(await screen.findByText("Ana Example")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });
});

// ── Pickup table ────────────────────────────────────────────────────────────

describe("DeliveryStationsDetails pickup table", () => {
  it("shows how many boxes of each combination every member collects, grouped by share type", async () => {
    renderPage();
    await screen.findByText("Ana Example");

    expect(headerRows()).toEqual([
      ["commissioning.pickup_name", "Veg", "commissioning.no_base_combination"],
      [
        "commissioning.S",
        "commissioning.MHoney·commissioning.M",
        "commissioning.no_base_combinationBread·commissioning.L",
      ],
    ]);
    expect(tableRows()).toEqual([
      ["Ana Example", "1", "", ""],
      ["Ben Sample", "", "2", ""],
      ["Dora Muster", "1", "", "1"],
    ]);
  });

  it("shows another station's members with that station's own box combinations", async () => {
    renderPage();
    await screen.findByText("Ana Example");

    await choose(STATION, "Market");

    expect(await screen.findByText("Cleo Muster")).toBeInTheDocument();
    expect(screen.queryByText("Ana Example")).not.toBeInTheDocument();
    expect(headerRows()).toEqual([
      ["commissioning.pickup_name", "Veg"],
      ["commissioning.M"],
    ]);
    expect(tableRows()).toEqual([["Cleo Muster", "1"]]);
  });

  it("says there are no deliveries and keeps every download disabled when nobody collects anything", async () => {
    farm.pickups = {};
    renderPage();

    expect(
      await screen.findByText("commissioning.packing_list_no_columns"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(download(STATION_PDF)).toBeDisabled();
    expect(download(DAY_PDF)).toBeDisabled();
    expect(download(WEEK_PDF)).toBeDisabled();
  });
});

// ── Week, day and station ───────────────────────────────────────────────────

describe("DeliveryStationsDetails choosing the week, day and station", () => {
  it("offers the week's delivery days with their dates and the chosen day's stations", async () => {
    renderPage();
    await screen.findByText("Ana Example");

    expect(await optionsOf(DAY)).toEqual([TUESDAY_LABEL, FRIDAY_LABEL]);
    await userEvent.keyboard("{Escape}");
    expect(await optionsOf(STATION)).toEqual(["Farm shop", "Market"]);
  });

  it("keeps the station on another day it also delivers on", async () => {
    renderPage();
    await screen.findByText("Ana Example");
    await choose(STATION, "Market");
    await screen.findByText("Cleo Muster");

    await choose(DAY, FRIDAY_LABEL);

    expect(await screen.findByText("Emil Probe")).toBeInTheDocument();
    expect(selectedIn(STATION)).toBe("Market");
    expect(screen.queryByText("Cleo Muster")).not.toBeInTheDocument();
    expect(api.stations).toHaveBeenCalledWith({ is_active: true, delivery_day: "day-fri" });
  });

  it("moves to the new day's first station when the station does not deliver that day", async () => {
    renderPage();
    await screen.findByText("Ana Example");

    await choose(DAY, FRIDAY_LABEL);

    expect(await screen.findByText("Finn Beispiel")).toBeInTheDocument();
    expect(selectedIn(STATION)).toBe("School");
    expect(screen.queryByText("Ana Example")).not.toBeInTheDocument();
  });

  it("hides this week's members while next week's list loads from the week arrow", async () => {
    renderPage();
    await screen.findByText("Ben Sample");
    const nextWeek = pending<StationMemberMatrix>();
    api.pickups.mockImplementation((params: ListParams) =>
      params.delivery_week === 42 ? nextWeek.promise : answerPickups(params),
    );

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(screen.queryByText("Ben Sample")).not.toBeInTheDocument();
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-17" });
    expect(api.pickups).toHaveBeenCalledWith({
      year: 2026,
      delivery_week: 42,
      day_number: TUESDAY,
      delivery_station: FARM_SHOP.id,
    });

    nextWeek.answer(FARM_SHOP_NEXT_TUESDAY);

    expect(await screen.findByText("Ana Example")).toBeInTheDocument();
    expect(screen.queryByText("Ben Sample")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(selectedIn(DAY)).toBe("commissioning.delivery_day Tuesday, 13.10.2026"),
    );
    expect(selectedIn(STATION)).toBe("Farm shop");
  });
});

// ── Downloads ───────────────────────────────────────────────────────────────

describe("DeliveryStationsDetails downloads", () => {
  it("explains each of the three downloads in a tooltip", async () => {
    renderPage();
    await screen.findByText("Ana Example");

    for (const tooltip of [
      "tooltip.pickup_list_single_delivery_station",
      "tooltip.pickup_list_whole_day",
      "tooltip.pickup_list_whole_week",
    ]) {
      expect(screen.getByRole("img", { name: tooltip })).toBeInTheDocument();
    }
  });

  it("prints the station's list with its take-home amounts, named after the week, day and station", async () => {
    renderPage();
    await screen.findByText("Ana Example");
    // The take-home amounts load beside the list; let them arrive before printing.
    await waitFor(() => expect(api.memberAmounts).toHaveBeenCalled());
    await settle();

    await userEvent.click(download(STATION_PDF));

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.pickup_list_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY_Farm_shop.pdf",
      ]),
    );
    const props = printedDocument();
    expect(props).toMatchObject({
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      tenant: TENANT_ON_THE_PDF,
    });
    expect(props.pages).toEqual([
      {
        stationName: "Farm shop",
        columns: FARM_SHOP_TUESDAY.columns,
        rows: FARM_SHOP_TUESDAY.rows,
        memberColumns: FARM_SHOP_TAKE.columns,
        memberRows: [CARROTS_ON_THE_SHEET],
        showSize: false,
      },
    ]);
  });

  it("asks the take-home sheet for the size column when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await screen.findByText("Ana Example");
    await waitFor(() => expect(api.memberAmounts).toHaveBeenCalled());
    await settle();

    await userEvent.click(download(STATION_PDF));

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printedDocument().pages).toEqual([
      expect.objectContaining({ stationName: "Farm shop", showSize: true }),
    ]);
  });

  it("prints every station of the day that has pickups, in one PDF named after the day", async () => {
    farm.stationsByDeliveryDay["day-tue"] = [FARM_SHOP, MARKET, CHURCH_HALL];
    renderPage();
    await screen.findByText("Ana Example");
    await waitFor(() => expect(download(DAY_PDF)).toBeEnabled());

    await userEvent.click(download(DAY_PDF));

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.pickup_lists_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY_commissioning.all_day.pdf",
      ]),
    );
    const props = printedDocument();
    expect(props).toMatchObject({
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      tenant: TENANT_ON_THE_PDF,
    });
    expect(props.pages).toEqual([
      {
        stationName: "Farm shop",
        columns: FARM_SHOP_TUESDAY.columns,
        rows: FARM_SHOP_TUESDAY.rows,
        memberColumns: FARM_SHOP_TAKE.columns,
        memberRows: [CARROTS_ON_THE_SHEET],
        showSize: false,
      },
      {
        stationName: "Market",
        columns: MARKET_TUESDAY.columns,
        rows: MARKET_TUESDAY.rows,
        memberColumns: [],
        memberRows: [],
        showSize: false,
      },
    ]);
  });

  it("offers the day's PDF only once every station's list has loaded", async () => {
    const marketPickups = pending<StationMemberMatrix>();
    api.pickups.mockImplementation((params: ListParams) =>
      listAskedFor(params) === listOf(41, TUESDAY, MARKET)
        ? marketPickups.promise
        : answerPickups(params),
    );
    renderPage();
    await screen.findByText("Ana Example");

    await waitFor(() =>
      expect(api.pickups).toHaveBeenCalledWith(
        expect.objectContaining({ day_number: TUESDAY, delivery_station: MARKET.id }),
      ),
    );
    expect(download(STATION_PDF)).toBeEnabled();
    expect(download(DAY_PDF)).toBeDisabled();

    marketPickups.answer(MARKET_TUESDAY);

    await waitFor(() => expect(download(DAY_PDF)).toBeEnabled());
  });

  it("offers the day's and the week's PDFs when nobody collects at the station on screen", async () => {
    // Every member of the farm shop took a joker this Tuesday.
    farm.pickups[listOf(41, TUESDAY, FARM_SHOP)] = { columns: [], rows: [] };
    renderPage();
    await screen.findByText("commissioning.packing_list_no_columns");

    await waitFor(() => expect(download(DAY_PDF)).toBeEnabled());
    await waitFor(() => expect(download(WEEK_PDF)).toBeEnabled());
    expect(download(STATION_PDF)).toBeDisabled();

    await userEvent.click(download(DAY_PDF));

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(
      (printedDocument().pages as { stationName: string }[]).map((page) => page.stationName),
    ).toEqual(["Market"]);
  });

  it("offers the day's and the week's PDFs when the station on screen fails to load", async () => {
    api.pickups.mockImplementation((params: ListParams) =>
      listAskedFor(params) === listOf(41, TUESDAY, FARM_SHOP)
        ? Promise.reject(new Error("Network Error"))
        : answerPickups(params),
    );
    renderPage();
    await screen.findByText("common.error_loading_data");

    await waitFor(() => expect(download(DAY_PDF)).toBeEnabled());
    await waitFor(() => expect(download(WEEK_PDF)).toBeEnabled());
    expect(download(STATION_PDF)).toBeDisabled();
  });

  it("offers the station's PDF only once its take-home amounts are in", async () => {
    const amounts = pending<PackingBoxesMatrix>();
    api.memberAmounts.mockImplementation((params: ListParams) =>
      listAskedFor(params) === listOf(41, TUESDAY, FARM_SHOP)
        ? amounts.promise
        : Promise.resolve({ columns: [], rows: [] }),
    );
    renderPage();
    await screen.findByText("Ana Example");
    await settle();

    expect(download(STATION_PDF)).toBeDisabled();

    amounts.answer(FARM_SHOP_TAKE);

    await waitFor(() => expect(download(STATION_PDF)).toBeEnabled());
    await userEvent.click(download(STATION_PDF));
    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printedDocument().pages).toEqual([
      expect.objectContaining({ memberRows: [CARROTS_ON_THE_SHEET] }),
    ]);
  });

  it("offers no station PDF when its take-home amounts fail to load", async () => {
    api.memberAmounts.mockImplementation((params: ListParams) =>
      listAskedFor(params) === listOf(41, TUESDAY, FARM_SHOP)
        ? Promise.reject(new Error("Network Error"))
        : Promise.resolve({ columns: [], rows: [] }),
    );
    renderPage();
    await screen.findByText("Ana Example");
    await waitFor(() => expect(download(WEEK_PDF)).toBeEnabled());
    await settle();

    expect(download(STATION_PDF)).toBeDisabled();
  });

  it("prints every delivery day's stations with pickups for the whole week, each page named after its day", async () => {
    // Both delivery days serve the same two stations; nobody collects at the
    // market on Tuesday.
    farm.stationsByDeliveryDay["day-fri"] = [FARM_SHOP, MARKET];
    farm.pickups[listOf(41, FRIDAY, FARM_SHOP)] = FARM_SHOP_FRIDAY;
    farm.pickups[listOf(41, TUESDAY, MARKET)] = { columns: [], rows: [] };
    renderPage();
    await screen.findByText("Ana Example");
    await waitFor(() => expect(download(WEEK_PDF)).toBeEnabled());

    await userEvent.click(download(WEEK_PDF));

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.pickup_lists_2026_commissioning.KW41_commissioning.whole_week.pdf",
      ]),
    );
    const props = printedDocument();
    expect(props).toMatchObject({
      week: 41,
      dayName: "commissioning.whole_week",
      tenant: TENANT_ON_THE_PDF,
    });
    expect(
      (props.pages as { stationName: string; rows: unknown[] }[]).map((page) => [
        page.stationName,
        page.rows,
      ]),
    ).toEqual([
      ["Farm shop — COMMON.WEEKDAY_TUESDAY", FARM_SHOP_TUESDAY.rows],
      ["Farm shop — COMMON.WEEKDAY_FRIDAY", FARM_SHOP_FRIDAY.rows],
      ["Market — COMMON.WEEKDAY_FRIDAY", MARKET_FRIDAY.rows],
    ]);
  });

  it("pairs every delivery day with the stations that day serves", async () => {
    // Friday serves the school, which Tuesday — the day on screen — doesn't.
    renderPage();
    await screen.findByText("Ana Example");
    await waitFor(() => expect(download(WEEK_PDF)).toBeEnabled());

    await userEvent.click(download(WEEK_PDF));

    await waitFor(() => expect(printed.files).toHaveLength(1));
    expect(
      (printedDocument().pages as { stationName: string }[]).map((page) => page.stationName),
    ).toEqual([
      "Farm shop — COMMON.WEEKDAY_TUESDAY",
      "Market — COMMON.WEEKDAY_TUESDAY",
      "School — COMMON.WEEKDAY_FRIDAY",
      "Market — COMMON.WEEKDAY_FRIDAY",
    ]);
  });
});

// ── Failures ────────────────────────────────────────────────────────────────

describe("DeliveryStationsDetails when a list cannot be loaded", () => {
  it("shows no members and offers no station PDF after a failed load, then recovers on another station", async () => {
    const farmShopPickups = pending<StationMemberMatrix>();
    api.pickups.mockImplementation((params: ListParams) =>
      params.delivery_station === FARM_SHOP.id
        ? farmShopPickups.promise
        : answerPickups(params),
    );
    renderPage();
    await waitFor(() => expect(tableIsBusy()).toBe(true));

    farmShopPickups.fail(new Error("Network Error"));

    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);
    expect(screen.getByText("common.error_loading_data")).toBeInTheDocument();
    expect(
      screen.queryByText("commissioning.packing_list_no_columns"),
    ).not.toBeInTheDocument();
    expect(download(STATION_PDF)).toBeDisabled();

    await choose(STATION, "Market");

    expect(await screen.findByText("Cleo Muster")).toBeInTheDocument();
    expect(screen.queryByText("common.error_loading_data")).not.toBeInTheDocument();
    await waitFor(() => expect(download(STATION_PDF)).toBeEnabled());
  });
});

// ── Import-shares farms ─────────────────────────────────────────────────────

describe("DeliveryStationsDetails for a farm that imports its share amounts", () => {
  it("explains that pickup lists need member deliveries, links to the import and loads no list", async () => {
    tenantSettings.values = { uploads_weekly_share_amount: true };
    renderPage();

    expect(
      await screen.findByText("commissioning.pickup_lists_import_unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "common.import_shares_mode_banner_link" }),
    ).toHaveAttribute("href", "/commissioning/import-shares");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download\./ })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // Let the delivery days arrive and every request that follows go out.
    await settle();
    expect(api.pickups).not.toHaveBeenCalled();
    expect(api.memberAmounts).not.toHaveBeenCalled();
  });
});

// ── Access ──────────────────────────────────────────────────────────────────

describe("DeliveryStationsDetails access", () => {
  it.each([
    ["the office", ["office"]],
    ["a gardener of the field team", ["gardener"]],
  ])("opens for %s", async (_who, roles) => {
    session.roles = roles;
    renderPage();

    expect(await screen.findByText("Ana Example")).toBeInTheDocument();
  });

  it.each([
    ["a member", ["member"]],
    ["a reseller's customer login", ["customer"]],
  ])("refuses %s and loads nothing", async (_who, roles) => {
    session.roles = roles;
    renderPage();

    expect(await screen.findByText("Not authorized.")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    await settle();
    expect(api.deliveryDays).not.toHaveBeenCalled();
    expect(api.pickups).not.toHaveBeenCalled();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("DeliveryStationsDetails render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Ana Example");
    await waitFor(() => expect(download(WEEK_PDF)).toBeEnabled());
    await settle();

    // About 11 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(120);
  });
});
