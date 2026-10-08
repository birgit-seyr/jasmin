/**
 * PackingListBulk: how much of each article one delivery station needs on one
 * delivery day, summed over every share type. Rendered through the real week,
 * day and station selectors, EditableTable, column hooks, phone card and PDF
 * download buttons. The generated commissioning client is the mocking
 * boundary: its hooks are real TanStack queries around spies that answer from
 * an in-memory farm. The PDF library, the PDF templates and the browser
 * download are stubbed, so no real PDF is rendered.
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
  DeliveryStation,
  PackingBoxesMatrix,
  PackingListBulkRow,
  Share,
  SharesDeliveryDay,
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

// Phone or desktop viewport, per test.
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({
  useIsMobile: () => viewport.mobile,
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const api = vi.hoisted(() => ({
  deliveryDays: vi.fn(),
  shares: vi.fn(),
  stations: vi.fn(),
  shareArticles: vi.fn(),
  bulkList: vi.fn(),
  memberAmounts: vi.fn(),
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
    useCommissioningSharesDeliveryDaysList: queryHook(
      "shares_delivery_days",
      api.deliveryDays,
    ),
    useCommissioningSharesList: queryHook("shares", api.shares),
    useCommissioningDeliveryStationsList: queryHook(
      "delivery_stations",
      api.stations,
    ),
    useCommissioningShareArticlesList: queryHook(
      "share_articles",
      api.shareArticles,
    ),
    useCommissioningPackingListBulkList: queryHook(
      "packing_list_bulk",
      api.bulkList,
    ),
    getCommissioningPackingListBulkListQueryKey: (params?: unknown) =>
      queryKey("packing_list_bulk", params),
    useCommissioningPackingListMemberAmountsRetrieve: queryHook(
      "packing_list/member_amounts",
      api.memberAmounts,
    ),
  };
});

// The page only needs the two download buttons; the barrel would also load
// every other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  PackingListBulkPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/PackingListBulkPDFGenerator")
  ).default,
  PackingBoxesMatrixPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/PackingBoxesMatrixPDFGenerator")
  ).default,
}));
vi.mock("@features/commissioning/pdfs/exports/PackingListBulkPDF", () => ({
  default: function PackingListBulkPDF() {
    return null;
  },
}));
vi.mock("@features/commissioning/pdfs/exports/PackingBoxesMatrixPDF", () => ({
  default: function PackingBoxesMatrixPDF() {
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

import PackingListBulk from "../PackingListBulk";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Backend day numbers: 0 = Monday … 6 = Sunday.
const MONDAY = 0;
const TUESDAY = 1;
const THURSDAY = 3;
const FRIDAY = 4;
const SATURDAY = 5;

const deliveryDay = (id: string, dayNumber: number): SharesDeliveryDay => ({
  id,
  day_number: dayNumber as SharesDeliveryDay["day_number"],
  valid_from: "2026-01-05",
  valid_until: null,
});

const station = (id: string, shortName: string): DeliveryStation => ({
  id,
  short_name: shortName,
  is_active: true,
});

const FARM_SHOP = station("st-farm-shop", "Farm shop");
const MARKET = station("st-market", "Market");
const SCHOOL = station("st-school", "School");

/** A share of the frozen week, delivered on one weekday and packed on another. */
const share = (id: string, deliveryDayNumber: number, packingDay: number): Share => ({
  id,
  year: 2026,
  delivery_week: 41,
  delivery_day: `day-${deliveryDayNumber}`,
  delivery_day_number: deliveryDayNumber,
  share_type_variation: "var-standard",
  packing_day: packingDay as Share["packing_day"],
});

const bulkRow = (
  stationOfRow: DeliveryStation,
  articleName: string,
  totalAmount: number,
  overrides: Partial<PackingListBulkRow> = {},
): PackingListBulkRow => ({
  id: `${stationOfRow.id}_${articleName}`,
  delivery_station: stationOfRow.id ?? "",
  delivery_station_name: stationOfRow.short_name ?? "",
  share_article: `sa-${articleName}`,
  share_article_name: articleName,
  unit: "KG",
  size: "M",
  total_amount: totalAmount,
  note: "",
  ...overrides,
});

const CARROTS = bulkRow(FARM_SHOP, "Carrots", 12, { note: "Wash before packing" });
const LETTUCE = bulkRow(FARM_SHOP, "Lettuce", 40, { unit: "PCS", size: "L" });
const POTATOES = bulkRow(MARKET, "Potatoes", 25);
const BEETROOT = bulkRow(MARKET, "Beetroot", 6);
const PUMPKINS = bulkRow(SCHOOL, "Pumpkins", 8, { unit: "PCS" });

/** "What you may take": one column per share size, the amount per share. */
const MEMBER_AMOUNTS: PackingBoxesMatrix = {
  columns: [
    {
      key: "var-small",
      base_variation_id: "var-small",
      base_size: "S",
      base_sort_order: 1,
      base_share_type_id: "st-vegetables",
      base_share_type_name: "Vegetables",
      base_share_type_short_name: "Veg",
      base_share_type_sort_index: 1,
      add_ons: [],
      count: 0,
    },
  ],
  // The amount per share sits under the column key, which the generated row
  // type leaves out.
  rows: [
    {
      id: "row-carrots",
      share_article_id: "sa-Carrots",
      share_article_name: "Carrots",
      unit: "KG",
      size: "M",
      note: "",
      "var-small": 0.5,
    } as PackingBoxesMatrix["rows"][number],
  ],
};

type ListParams = { day_number: number; delivery_station?: string };

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  deliveryDays: SharesDeliveryDay[];
  stationsByDeliveryDay: Record<string, DeliveryStation[]>;
  shares: Share[];
  bulkRows: Record<string, PackingListBulkRow[]>;
  memberAmounts: Record<string, PackingBoxesMatrix>;
};

/** The delivery day and station a packing list belongs to. */
const dayAndStation = (dayNumber: number, stationId: string | undefined) =>
  `${dayNumber}/${stationId}`;

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<PackingListBulk />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const DAY = "common.delivery_day";
const STATION = "placeholder.delivery_station_selector";
const WEEK = "common.week";
const DOWNLOAD_LIST = /download\.packing_list_bulk$/;
const DOWNLOAD_MEMBER_SHEET = /download\.packing_list_bulk_member$/;

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

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

function bodyRows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"),
  );
}

/** The phone card that shows ``text``. */
function cardOf(text: string): HTMLElement {
  const card = screen.getByText(text).closest<HTMLElement>(".mobile-card-item");
  if (!card) throw new Error(`No card shows ${text}`);
  return card;
}

const isBusy = (container: HTMLElement = document.body) =>
  container.querySelector('[aria-busy="true"]') !== null;
const tableIsBusy = () => {
  const table = document.querySelector<HTMLElement>(".ant-table-wrapper");
  return table !== null && isBusy(table);
};

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

const lastListRequest = () => api.bulkList.mock.lastCall?.[0];
const lastMemberSheetRequest = () => api.memberAmounts.mock.lastCall?.[0];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  printed.documents = [];
  printed.files = [];
  farm = {
    deliveryDays: [deliveryDay("day-tue", TUESDAY), deliveryDay("day-fri", FRIDAY)],
    stationsByDeliveryDay: {
      "day-tue": [FARM_SHOP, MARKET],
      "day-fri": [SCHOOL, MARKET],
    },
    shares: [share("share-tue", TUESDAY, MONDAY), share("share-fri", FRIDAY, THURSDAY)],
    bulkRows: {
      [dayAndStation(TUESDAY, FARM_SHOP.id)]: [CARROTS, LETTUCE],
      [dayAndStation(TUESDAY, MARKET.id)]: [POTATOES],
      [dayAndStation(FRIDAY, SCHOOL.id)]: [PUMPKINS],
      [dayAndStation(FRIDAY, MARKET.id)]: [BEETROOT],
    },
    memberAmounts: { [dayAndStation(TUESDAY, FARM_SHOP.id)]: MEMBER_AMOUNTS },
  };
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.stations
    .mockReset()
    .mockImplementation(async (params: { delivery_day?: string }) => [
      ...(farm.stationsByDeliveryDay[params.delivery_day ?? ""] ?? []),
    ]);
  api.shares
    .mockReset()
    .mockImplementation(async (params: { delivery_week: number }) =>
      farm.shares.filter((row) => row.delivery_week === params.delivery_week),
    );
  api.shareArticles.mockReset().mockResolvedValue([]);
  api.bulkList
    .mockReset()
    .mockImplementation(async (params: ListParams) => [
      ...(farm.bulkRows[dayAndStation(params.day_number, params.delivery_station)] ??
        []),
    ]);
  api.memberAmounts
    .mockReset()
    .mockImplementation(
      async (params: ListParams) =>
        farm.memberAmounts[dayAndStation(params.day_number, params.delivery_station)] ?? {
          columns: [],
          rows: [],
        },
    );
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("PackingListBulk loading", () => {
  it("opens on today's delivery day and that day's first station, then lists what the station needs", async () => {
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe("commissioning.delivery_day Tuesday, 06.10.2026");
    expect(selectedIn(STATION)).toBe("Farm shop");
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-10" });
    expect(api.stations).toHaveBeenCalledWith({ is_active: true, delivery_day: "day-tue" });
    expect(lastListRequest()).toEqual({
      year: 2026,
      delivery_week: 41,
      day_number: TUESDAY,
      is_past: false,
      delivery_station: FARM_SHOP.id,
    });
    expect(lastMemberSheetRequest()).toEqual(lastListRequest());
    expect(screen.getByText("explainers.packing_list_bulk")).toBeInTheDocument();
  });

  it("asks for a delivery station and loads no list until the day's stations are known", async () => {
    const stations = pending<DeliveryStation[]>();
    api.stations.mockImplementation(() => stations.promise);
    renderPage();

    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    expect(screen.getByText("commissioning.please_select_delivery_station")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(api.bulkList).not.toHaveBeenCalled();
    expect(api.memberAmounts).not.toHaveBeenCalled();

    stations.answer([FARM_SHOP, MARKET]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(
      screen.queryByText("commissioning.please_select_delivery_station"),
    ).not.toBeInTheDocument();
  });

  it("shows a spinner over the table while the station's articles load", async () => {
    const rows = pending<PackingListBulkRow[]>();
    api.bulkList.mockImplementation(() => rows.promise);
    renderPage();

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);

    rows.answer([CARROTS]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });
});

// ── Packing rows ────────────────────────────────────────────────────────────

describe("PackingListBulk packing rows", () => {
  it("lists every article the station needs with its unit, total amount and note", async () => {
    renderPage();
    await screen.findByText("Carrots");

    for (const header of [
      /commissioning\.vegetables_and_fruits/,
      /commissioning\.unit/,
      /commissioning\.total_amount/,
      /commissioning\.note/,
    ]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(
      screen.queryByRole("columnheader", { name: /commissioning\.size/ }),
    ).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(2);
    const carrots = rowOf("Carrots");
    expect(within(carrots).getByText("commissioning.units.kg")).toBeInTheDocument();
    expect(within(carrots).getByText("12,00")).toBeInTheDocument();
    expect(within(carrots).getByText("Wash before packing")).toBeInTheDocument();
    const lettuce = rowOf("Lettuce");
    expect(within(lettuce).getByText("commissioning.units.pcs")).toBeInTheDocument();
    expect(within(lettuce).getByText("40,0")).toBeInTheDocument();
  });

  it("adds the size column when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await screen.findByText("Lettuce");

    expect(screen.getByRole("columnheader", { name: /commissioning\.size/ })).toBeInTheDocument();
    expect(within(rowOf("Lettuce")).getByText("commissioning.large")).toBeInTheDocument();
  });

  it("counts only the share sizes packed in bulk when the farm packs the rest in boxes", async () => {
    tenantSettings.values = { packing_mode: "MIXED" };
    renderPage();
    await screen.findByText("Carrots");

    expect(lastListRequest()).toMatchObject({
      delivery_station: FARM_SHOP.id,
      is_packed_bulk: true,
    });
    expect(lastMemberSheetRequest()).toMatchObject({ is_packed_bulk: true });
  });

  it("counts every share size when the farm packs everything in bulk", async () => {
    tenantSettings.values = { packing_mode: "BULK" };
    renderPage();
    await screen.findByText("Carrots");

    expect(lastListRequest()).not.toHaveProperty("is_packed_bulk");
    expect(lastMemberSheetRequest()).not.toHaveProperty("is_packed_bulk");
  });
});

// ── Week, day and station ───────────────────────────────────────────────────

describe("PackingListBulk choosing the week, day and station", () => {
  const fridayLabel = "commissioning.delivery_day Friday, 09.10.2026";

  it("offers only the farm's delivery days, each with its date", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(await optionsOf(DAY)).toEqual([
      "commissioning.delivery_day Tuesday, 06.10.2026",
      fridayLabel,
    ]);
  });

  it("opens on the week's first delivery day when today is none", async () => {
    farm.deliveryDays = [deliveryDay("day-mon", MONDAY), deliveryDay("day-thu", THURSDAY)];
    farm.stationsByDeliveryDay = { "day-mon": [MARKET], "day-thu": [SCHOOL] };
    farm.bulkRows = { [dayAndStation(MONDAY, MARKET.id)]: [POTATOES] };
    renderPage();

    expect(await screen.findByText("Potatoes")).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe("commissioning.delivery_day Monday, 05.10.2026");
    expect(lastListRequest()).toMatchObject({ day_number: MONDAY, delivery_station: MARKET.id });
  });

  it("opens on the delivery day of the day the page is opened, not the day it was loaded", async () => {
    vi.setSystemTime(new Date(2026, 9, 9, 12, 0));
    renderPage();

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(selectedIn(DAY)).toBe(fridayLabel);
    expect(lastListRequest()).toMatchObject({ day_number: FRIDAY, delivery_station: SCHOOL.id });
  });

  it("asks for a station and loads no list on a day without stations", async () => {
    farm.stationsByDeliveryDay = { "day-tue": [FARM_SHOP, MARKET], "day-fri": [] };
    renderPage();
    await screen.findByText("Carrots");

    await choose(DAY, fridayLabel);

    expect(
      await screen.findByText("commissioning.please_select_delivery_station"),
    ).toBeInTheDocument();
    expect(api.stations).toHaveBeenLastCalledWith({ is_active: true, delivery_day: "day-fri" });
    expect(selectedIn(STATION)).toBe("");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("lists another station's articles when the station changes", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(STATION, "Market");

    expect(await screen.findByText("Potatoes")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(lastListRequest()).toMatchObject({ day_number: TUESDAY, delivery_station: MARKET.id });
  });

  it("keeps the station on another day it also delivers on", async () => {
    renderPage();
    await screen.findByText("Carrots");
    await choose(STATION, "Market");
    await screen.findByText("Potatoes");

    await choose(DAY, fridayLabel);

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(selectedIn(STATION)).toBe("Market");
    expect(api.stations).toHaveBeenLastCalledWith({ is_active: true, delivery_day: "day-fri" });
    expect(lastListRequest()).toMatchObject({ day_number: FRIDAY, delivery_station: MARKET.id });
  });

  it("moves to the new day's first station when the station doesn't deliver that day", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(DAY, fridayLabel);

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(selectedIn(STATION)).toBe("School");
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(lastListRequest()).toMatchObject({ day_number: FRIDAY, delivery_station: SCHOOL.id });
  });

  it("loads the next week's delivery days and list from the week arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() =>
      expect(selectedIn(DAY)).toBe("commissioning.delivery_day Tuesday, 13.10.2026"),
    );
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-17" });
    await waitFor(() =>
      expect(lastListRequest()).toEqual({
        year: 2026,
        delivery_week: 42,
        day_number: TUESDAY,
        is_past: false,
        delivery_station: FARM_SHOP.id,
      }),
    );
  });

  it("asks for the stored list once the week lies more than a week back", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastListRequest()).toMatchObject({ delivery_week: 40 }));
    expect(lastListRequest()).toMatchObject({ is_past: false });

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastListRequest()).toMatchObject({ delivery_week: 39 }));
    expect(lastListRequest()).toMatchObject({ is_past: true });
    expect(lastMemberSheetRequest()).toMatchObject({ delivery_week: 39, is_past: true });
  });
});

// ── Packing day ─────────────────────────────────────────────────────────────

describe("PackingListBulk packing day", () => {
  const packingDay = () => screen.getByText("commissioning.packing_day");

  it("names the day the chosen delivery is packed on", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await waitFor(() => expect(packingDay()).toHaveTextContent("Monday, 05.10.2026"));
  });

  it("dates the packing day by the chosen delivery when one packing day serves two", async () => {
    farm.deliveryDays = [deliveryDay("day-mon", MONDAY), deliveryDay("day-sat", SATURDAY)];
    farm.stationsByDeliveryDay = { "day-mon": [MARKET], "day-sat": [MARKET] };
    farm.shares = [share("share-mon", MONDAY, FRIDAY), share("share-sat", SATURDAY, FRIDAY)];
    farm.bulkRows = {
      [dayAndStation(MONDAY, MARKET.id)]: [POTATOES],
      [dayAndStation(SATURDAY, MARKET.id)]: [BEETROOT],
    };
    renderPage();
    await screen.findByText("Potatoes");
    await waitFor(() => expect(packingDay()).toHaveTextContent("Friday, 02.10.2026"));

    await choose(DAY, "commissioning.delivery_day Saturday, 10.10.2026");

    await screen.findByText("Beetroot");
    await waitFor(() => expect(packingDay()).toHaveTextContent("Friday, 09.10.2026"));
  });

  it("dates a packing weekday after the delivery's weekday in the week before", async () => {
    farm.deliveryDays = [deliveryDay("day-mon", MONDAY)];
    farm.stationsByDeliveryDay = { "day-mon": [MARKET] };
    farm.shares = [share("share-mon", MONDAY, SATURDAY)];
    farm.bulkRows = { [dayAndStation(MONDAY, MARKET.id)]: [POTATOES] };
    renderPage();
    await screen.findByText("Potatoes");

    await waitFor(() => expect(packingDay()).toHaveTextContent("Saturday, 03.10.2026"));
  });
});

// ── Downloads ───────────────────────────────────────────────────────────────

describe("PackingListBulk downloads", () => {
  const weekAndDay = "2026_commissioning.KW41_COMMONWEEKDAYTUESDAY";

  it("prints the station's packing list as a PDF named after the week and day", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(screen.getByRole("button", { name: DOWNLOAD_LIST }));

    await waitFor(() =>
      expect(printed.files).toEqual([`commissioning.packing_list_bulk_${weekAndDay}.pdf`]),
    );
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("PackingListBulkPDF");
    expect(props).toMatchObject({
      year: 2026,
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      deliveryStationName: "Farm shop",
      showSize: false,
    });
    expect(props.data).toEqual([
      expect.objectContaining({
        share_article_name: "Carrots",
        total_amount: 12,
        total_amount_text: "12,00",
        unit_label: "commissioning.units.kg",
        note: "Wash before packing",
      }),
      expect.objectContaining({
        share_article_name: "Lettuce",
        total_amount: 40,
        total_amount_text: "40,0",
        unit_label: "commissioning.units.pcs",
        size_label: "commissioning.large",
      }),
    ]);
  });

  it("shows and prints a weight with decimals in the tenant's number format", async () => {
    farm.bulkRows = {
      [dayAndStation(TUESDAY, FARM_SHOP.id)]: [bulkRow(FARM_SHOP, "Carrots", 4.5)],
    };
    renderPage();
    await screen.findByText("Carrots");

    expect(within(rowOf("Carrots")).getByText("4,50")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: DOWNLOAD_LIST }));

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.documents[0].props.data).toEqual([
      expect.objectContaining({ total_amount_text: "4,50" }),
    ]);
  });

  it("prints the members' sheet with the amount per share size under the farm's name and logo", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const download = screen.getByRole("button", { name: DOWNLOAD_MEMBER_SHEET });
    await waitFor(() => expect(download).toBeEnabled());

    await userEvent.click(download);

    await waitFor(() =>
      expect(printed.files).toEqual([
        `commissioning.packing_list_bulk_member_${weekAndDay}.pdf`,
      ]),
    );
    const [{ template, props }] = printed.documents;
    expect(template).toBe("PackingBoxesMatrixPDF");
    expect(props).toMatchObject({
      columns: MEMBER_AMOUNTS.columns,
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      pillKey: "commissioning.packing_list_bulk_member",
      showCountRow: false,
      tenant: {
        name: "Green Acres",
        logoUrl: "https://example.test/logo.png",
        email: "office@example.test",
        phone: "+49 30 1234567",
      },
    });
    expect(props.data).toEqual([
      expect.objectContaining({
        share_article_name: "Carrots",
        unit_label: "commissioning.units.kg",
        "var-small": 0.5,
      }),
    ]);
    // Each share size's amount prints at its unit's precision in the farm's
    // number format, as the box list prints its cells; no amount stays blank.
    const cellText = props.cellText as (value: unknown, item: Record<string, unknown>) => string;
    const [carrots] = props.data as Record<string, unknown>[];
    expect(cellText(carrots["var-small"], carrots)).toBe("0,50");
    expect(cellText(3, { ...carrots, unit: "PCS" })).toBe("3,0");
    expect(cellText(0, carrots)).toBe("");
    expect(cellText(null, carrots)).toBe("");
  });

  it("says there is nothing to pack and keeps both downloads disabled", async () => {
    farm.bulkRows = {};
    farm.memberAmounts = {};
    renderPage();

    await waitFor(() => expect(api.memberAmounts).toHaveBeenCalled());
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(screen.getByRole("button", { name: DOWNLOAD_LIST })).toBeDisabled();
    expect(screen.getByRole("button", { name: DOWNLOAD_MEMBER_SHEET })).toBeDisabled();
  });
});

// ── Failures ────────────────────────────────────────────────────────────────

describe("PackingListBulk when the list cannot be loaded", () => {
  it("shows no other station's rows while the list loads or once it failed, then recovers", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const marketList = pending<PackingListBulkRow[]>();
    api.bulkList.mockImplementation(() => marketList.promise);
    api.memberAmounts.mockRejectedValue(new Error("Network Error"));

    await choose(STATION, "Market");

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(lastListRequest()).toMatchObject({ delivery_station: MARKET.id });
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: DOWNLOAD_LIST })).toBeDisabled();

    marketList.fail(new Error("Network Error"));

    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);
    expect(screen.getByRole("button", { name: DOWNLOAD_LIST })).toBeDisabled();
    expect(screen.getByRole("button", { name: DOWNLOAD_MEMBER_SHEET })).toBeDisabled();

    api.bulkList.mockImplementation(async () => [CARROTS]);
    await choose(STATION, "Farm shop");

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
  });
});

// ── Read-only ───────────────────────────────────────────────────────────────

describe("PackingListBulk is read-only", () => {
  it("offers no way to add, edit or delete an article", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: /table\.add_plus_icon/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "table.actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

    await userEvent.click(within(rowOf("Carrots")).getByText("12,00"));

    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(within(rowOf("Carrots")).queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(within(rowOf("Carrots")).queryByRole("textbox")).not.toBeInTheDocument();
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("PackingListBulk on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each article as a card with its total and unit instead of the table", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const carrots = cardOf("Carrots");
    expect(within(carrots).getByText("commissioning.total_amount")).toBeInTheDocument();
    expect(within(carrots).getByText("12,00")).toBeInTheDocument();
    expect(within(carrots).getByText("commissioning.units.kg")).toBeInTheDocument();
    expect(within(carrots).getByText("Wash before packing")).toBeInTheDocument();
    const lettuce = cardOf("Lettuce");
    expect(within(lettuce).getByText("40,0")).toBeInTheDocument();
    expect(within(lettuce).getByText("commissioning.units.pcs")).toBeInTheDocument();
    expect(within(lettuce).getByText("commissioning.large")).toBeInTheDocument();
  });

  it("shows a spinner instead of cards while the articles load", async () => {
    const rows = pending<PackingListBulkRow[]>();
    api.bulkList.mockImplementation(() => rows.promise);
    renderPage();

    await waitFor(() => expect(isBusy()).toBe(true));
    expect(screen.queryByText("table.no_data")).not.toBeInTheDocument();

    rows.answer([CARROTS]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(isBusy()).toBe(false);
  });

  it("labels the delivery day in the short phone format", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(selectedIn(DAY)).toBe("Tu, 06.10.");
  });

  it("switches to another station's cards", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(STATION, "Market");

    await screen.findByText("Potatoes");
    expect(within(cardOf("Potatoes")).getByText("25,00")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("leaves out the downloads, the packing day and the explainer", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: DOWNLOAD_LIST })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: DOWNLOAD_MEMBER_SHEET })).not.toBeInTheDocument();
    expect(screen.queryByText("commissioning.packing_day")).not.toBeInTheDocument();
    expect(screen.queryByText("explainers.packing_list_bulk")).not.toBeInTheDocument();
  });

  it("offers no add button and opens nothing when a card is tapped", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Carrots"));

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("PackingListBulk render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Carrots");
    await flushMicrotasks();

    // About 15 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});
