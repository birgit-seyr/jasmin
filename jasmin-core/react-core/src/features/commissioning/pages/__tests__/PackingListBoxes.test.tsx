/**
 * PackingListBoxes: how much of each article goes into every kind of box
 * packed on one delivery day, across every share type, with the number of
 * boxes of each kind. Rendered through the real week, day, tour and station
 * selectors, EditableTable, column hooks and PDF download button. The
 * generated commissioning client is the mocking boundary: its hooks are real
 * TanStack queries around spies that answer from an in-memory farm. The PDF
 * library, the PDF template and the browser download are stubbed, so no real
 * PDF is rendered.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The page reads "today" when it
 * mounts, so a test that moves the clock before rendering opens on that day.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DeliveryStation,
  GranularityCheckResponse,
  PackingBoxesMatrix,
  PackingBoxesMatrixAddOn,
  PackingBoxesMatrixColumn,
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
// It appends an interpolated `number`, so the tours read "… 1" and "… 2".
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
  deliveryDays: vi.fn(),
  stations: vi.fn(),
  shareArticles: vi.fn(),
  granularity: vi.fn(),
  boxesMatrix: vi.fn(),
  memberAmounts: vi.fn(),
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
    useCommissioningDeliveryStationsList: queryHook("delivery_stations", api.stations),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
    useCommissioningGranularityRetrieve: queryHook("granularity", api.granularity),
    useCommissioningPackingListBoxesMatrixRetrieve: queryHook(
      "packing_list/boxes_matrix",
      api.boxesMatrix,
    ),
    useCommissioningPackingListMemberAmountsRetrieve: queryHook(
      "packing_list/member_amounts",
      api.memberAmounts,
    ),
  };
});

// The page only needs its download button; the barrel would also load every
// other PDF template of the app.
vi.mock("@features/commissioning/pdfs", async () => ({
  PackingBoxesMatrixPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/PackingBoxesMatrixPDFGenerator")
  ).default,
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

import PackingListBoxes from "../PackingListBoxes";
import {
  ALIKE_ALL_DAY,
  ALIKE_PER_TOUR,
  article,
  boxesOf,
  deliveryDay,
  FARM_SHOP,
  FRIDAY,
  HONEY_ONLY,
  HONEY_SMALL,
  MARKET,
  MEDIUM,
  MEDIUM_WITH_HONEY,
  MEMBER_COLUMNS,
  MONDAY,
  PER_STATION,
  SCHOOL,
  scope,
  SMALL,
  THURSDAY,
  TUESDAY,
  TUESDAY_BOXES,
  TUESDAY_COLUMNS,
  TUESDAY_MEMBER_AMOUNTS,
  WASH,
} from "./packingListBoxes.fixtures";
import {
  arrow,
  choose,
  openDropdown,
  optionsOf,
  pending,
  selectNamed,
  shownIn,
} from "./packingListBoxes.helpers";

// ── Fixtures ────────────────────────────────────────────────────────────────


type MatrixParams = { day_number: number; delivery_station?: string; tour?: number };

/** What the in-memory farm holds; the request spies answer from it. */
let farm: {
  deliveryDays: SharesDeliveryDay[];
  stationsByDeliveryDay: Record<string, DeliveryStation[]>;
  granularityByDay: Record<number, GranularityCheckResponse>;
  boxes: Record<string, PackingBoxesMatrix>;
  memberAmounts: Record<string, PackingBoxesMatrix>;
};

const answerFrom =
  (matrices: () => Record<string, PackingBoxesMatrix>) =>
  async ({ day_number, delivery_station, tour }: MatrixParams) =>
    matrices()[scope(day_number, { station: delivery_station, tour })] ?? {
      columns: [],
      rows: [],
    };

/** The exact query for a day of week 41; `scoped` adds or overrides fields. */
const requestFor = (dayNumber: number, scoped: Record<string, unknown> = {}) => ({
  year: 2026,
  delivery_week: 41,
  day_number: dayNumber,
  is_past: false,
  ...scoped,
});

/** The question whether a day's planned amounts agree across its stations. */
const granularityFor = (dayNumber: number, week = 41) => ({
  year: 2026,
  delivery_week: week,
  day_number: dayNumber,
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<PackingListBoxes />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const DAY = "common.delivery_day";
const STATION = "placeholder.delivery_station_selector";
const WEEK = "common.week";
const DOWNLOAD = /download\.packing_list$/;
const NO_DELIVERIES = "commissioning.packing_list_no_columns";
const LOAD_FAILED = "table.load_failed_title";
const TUESDAY_LABEL = "commissioning.delivery_day Tuesday, 06.10.2026";
const FRIDAY_LABEL = "commissioning.delivery_day Friday, 09.10.2026";
const TOUR_1 = "commissioning.tour_number 1";
const TOUR_2 = "commissioning.tour_number 2";
const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const NOTE = "commissioning.note";
const NO_BASE = "commissioning.no_base_combination";
const BUNCH = "commissioning.units.bunch";
const PIECES = "commissioning.units.pcs";
const KILOS = "commissioning.units.kg";

/** The tour picker has no accessible name; it is the select showing a tour. */
const tourPicker = () =>
  screen.queryByText(/^commissioning\.tour_number \d$/)?.closest<HTMLElement>(".ant-select") ??
  null;

const stationPicker = () => screen.queryByRole("combobox", { name: STATION });

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

const bodyRows = () =>
  document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row");

const textsOf = (cells: Iterable<Element>) =>
  Array.from(cells, (cell) => cell.textContent ?? "");

/** The header rows of the table, top to bottom. */
const headerRows = () =>
  Array.from(document.querySelectorAll(".ant-table-thead > tr"), (row) =>
    textsOf(row.querySelectorAll("th")),
  );

/** Every cell of the article's row, left to right. */
const cellsOf = (text: string) => textsOf(rowOf(text).querySelectorAll("td"));

/** The box-count row below the articles. */
const countRow = () => textsOf(document.querySelectorAll(".ant-table-summary td"));

/** The phone card that shows ``text``. */
function cardOf(text: string): HTMLElement {
  const card = screen.getByText(text).closest<HTMLElement>(".mobile-card-item");
  if (!card) throw new Error(`No card shows ${text}`);
  return card;
}

/** What a phone card lists: each kind of box with its figure and unit. */
const figuresOn = (card: HTMLElement) =>
  Array.from(card.querySelectorAll(".text-muted-xs"), (label) => [
    label.textContent ?? "",
    Array.from(label.nextElementSibling?.children ?? [], (part) => part.textContent ?? "").join(
      " ",
    ),
  ]);

const isBusy = (container: HTMLElement = document.body) =>
  container.querySelector('[aria-busy="true"]') !== null;
const tableIsBusy = () => {
  const table = document.querySelector<HTMLElement>(".ant-table-wrapper");
  return table !== null && isBusy(table);
};

const downloadButton = () => screen.getByRole("button", { name: DOWNLOAD });

const lastBoxesRequest = () => api.boxesMatrix.mock.lastCall?.[0];
const lastMemberAmountsRequest = () => api.memberAmounts.mock.lastCall?.[0];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  printed.documents = [];
  printed.files = [];
  farm = {
    deliveryDays: [deliveryDay("day-tue", TUESDAY), deliveryDay("day-fri", FRIDAY, 2)],
    stationsByDeliveryDay: { "day-tue": [FARM_SHOP, MARKET], "day-fri": [SCHOOL, MARKET] },
    granularityByDay: {},
    boxes: { [scope(TUESDAY)]: TUESDAY_BOXES, [scope(FRIDAY)]: boxesOf("Pumpkins", 1, 1) },
    memberAmounts: { [scope(TUESDAY)]: TUESDAY_MEMBER_AMOUNTS },
  };
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.stations
    .mockReset()
    .mockImplementation(async (params: { delivery_day?: string }) => [
      ...(farm.stationsByDeliveryDay[params.delivery_day ?? ""] ?? []),
    ]);
  api.shareArticles.mockReset().mockResolvedValue([]);
  api.granularity
    .mockReset()
    .mockImplementation(
      async (params: { day_number: number }) =>
        farm.granularityByDay[params.day_number] ?? ALIKE_ALL_DAY,
    );
  api.boxesMatrix.mockReset().mockImplementation(answerFrom(() => farm.boxes));
  api.memberAmounts.mockReset().mockImplementation(answerFrom(() => farm.memberAmounts));
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("PackingListBoxes loading", () => {
  it("opens on today's delivery day and lists the boxes of every share type packed that day", async () => {
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(TUESDAY_LABEL);
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-10" });
    expect(api.granularity).toHaveBeenLastCalledWith(granularityFor(TUESDAY));
    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY));
    expect(api.memberAmounts).not.toHaveBeenCalled();
    expect(stationPicker()).not.toBeInTheDocument();
    expect(tourPicker()).toBeNull();
    expect(screen.getByText("explainers.packing_list_boxes")).toBeInTheDocument();
  });

  it("shows a spinner over the table and keeps the download disabled while the boxes load", async () => {
    const boxes = pending<PackingBoxesMatrix>();
    api.boxesMatrix.mockImplementation(() => boxes.promise);
    renderPage();

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    boxes.answer(TUESDAY_BOXES);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(downloadButton()).toBeEnabled();
  });

  it("asks for a station until it knows whether every station gets the same amounts", async () => {
    const granularity = pending<GranularityCheckResponse>();
    api.granularity.mockImplementation(() => granularity.promise);
    renderPage();

    await waitFor(() => expect(api.granularity).toHaveBeenCalled());
    expect(stationPicker()).toBeInTheDocument();
    expect(api.boxesMatrix).not.toHaveBeenCalled();

    granularity.answer(ALIKE_ALL_DAY);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(stationPicker()).not.toBeInTheDocument();
    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY));
  });
});

// ── The matrix ──────────────────────────────────────────────────────────────

describe("PackingListBoxes matrix", () => {
  it("groups the kinds of box under their share type and shows each article's amount per box", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(headerRows()).toEqual([
      [ARTICLE, UNIT, "Veg", NO_BASE, NOTE],
      // The base share's size, then a badge per add-on packed into the box.
      [
        "commissioning.S",
        "commissioning.M",
        "commissioning.MHoney·commissioning.S",
        `${NO_BASE}Honey·commissioning.S`,
      ],
    ]);
    expect(bodyRows()).toHaveLength(3);
    // At the unit's precision in the farm's number format; a box without the
    // article leaves its cell blank.
    expect(cellsOf("Carrots")).toEqual(["Carrots", BUNCH, "1,0", "2,0", "2,0", "", ""]);
    expect(cellsOf("Lettuce")).toEqual(["Lettuce", PIECES, "1,0", "1,0", "1,0", "", WASH]);
    expect(cellsOf("Forest honey")).toEqual(["Forest honey", PIECES, "", "", "1,0", "1,0", ""]);
  });

  it("shows a fraction of a kilo per box at the kilo's precision, on screen and on paper", async () => {
    farm.boxes[scope(TUESDAY)] = {
      columns: TUESDAY_COLUMNS,
      rows: [article("Potatoes", "KG", "M", TUESDAY_COLUMNS, [0.5, 0.25, 1.25, 0])],
    };
    renderPage();
    await screen.findByText("Potatoes");

    expect(cellsOf("Potatoes")).toEqual(["Potatoes", KILOS, "0,50", "0,25", "1,25", "", ""]);

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    const { cellText, data } = printed.documents[0].props as {
      cellText: (value: unknown, item: Record<string, unknown>) => string;
      data: Record<string, unknown>[];
    };
    expect(TUESDAY_COLUMNS.map((column) => cellText(data[0][column.key], data[0]))).toEqual([
      "0,50",
      "0,25",
      "1,25",
      "",
    ]);
  });

  it("counts the boxes of each kind in a row below the articles", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(countRow()).toEqual(["commissioning.box_count", "", "12", "30", "5", "2", ""]);
  });

  it("adds the size column, on screen and on paper, when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await screen.findByText("Carrots");

    expect(headerRows()[0]).toEqual([ARTICLE, UNIT, "commissioning.size", "Veg", NO_BASE, NOTE]);
    expect(cellsOf("Carrots").slice(0, 4)).toEqual(["Carrots", BUNCH, "commissioning.medium", "1,0"]);
    expect(cellsOf("Forest honey")[2]).toBe("");

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.documents[0].props).toMatchObject({ showSize: true });
  });

  it("leaves out the share sizes packed in bulk when the farm packs the rest in boxes", async () => {
    tenantSettings.values = { packing_mode: "MIXED" };
    renderPage();
    await screen.findByText("Carrots");

    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY, { is_packed_bulk: false }));
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

  it("says there are no deliveries, instead of an empty table, when no box is packed that day", async () => {
    farm.boxes = {};
    renderPage();

    expect(await screen.findByText(NO_DELIVERIES)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();
  });
});

// ── Farms that upload their weekly share amounts ────────────────────────────

describe("PackingListBoxes for a farm that uploads its weekly share amounts", () => {
  beforeEach(() => {
    tenantSettings.values = { uploads_weekly_share_amount: true };
  });

  it("shows what a member of each share size takes, without a box count", async () => {
    renderPage();
    await screen.findByText("Lettuce");

    expect(lastMemberAmountsRequest()).toEqual(requestFor(TUESDAY));
    expect(api.boxesMatrix).not.toHaveBeenCalled();
    expect(headerRows()).toEqual([
      [ARTICLE, UNIT, "Veg", "Honey", NOTE],
      ["commissioning.S", "commissioning.M", "commissioning.S"],
    ]);
    expect(cellsOf("Lettuce")).toEqual(["Lettuce", PIECES, "1,0", "2,0", "", ""]);
    expect(cellsOf("Forest honey")).toEqual(["Forest honey", PIECES, "", "", "1,0", ""]);
    expect(screen.queryByText("commissioning.box_count")).not.toBeInTheDocument();
    expect(countRow()).toEqual([]);
  });

  it("leaves out the share sizes packed in bulk when the farm packs the rest in boxes", async () => {
    tenantSettings.values = { uploads_weekly_share_amount: true, packing_mode: "MIXED" };
    renderPage();
    await screen.findByText("Lettuce");

    expect(lastMemberAmountsRequest()).toEqual(requestFor(TUESDAY, { is_packed_bulk: false }));
  });

  it("prints the amounts without a box-count row", async () => {
    renderPage();
    await screen.findByText("Lettuce");

    await userEvent.click(downloadButton());

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    expect(printed.documents[0].props).toMatchObject({
      columns: MEMBER_COLUMNS,
      showCountRow: false,
    });
  });

  it("asks for the stored amounts once the week lies more than a week back", async () => {
    renderPage();
    await screen.findByText("Lettuce");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await userEvent.click(arrow(WEEK, "common.previous"));

    await waitFor(() =>
      expect(lastMemberAmountsRequest()).toMatchObject({ delivery_week: 39, is_past: true }),
    );
  });
});

// ── Day, tour and station ───────────────────────────────────────────────────

describe("PackingListBoxes choosing the day", () => {
  it("offers only the farm's delivery days, each with its date", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(await optionsOf(selectNamed(DAY))).toEqual([TUESDAY_LABEL, FRIDAY_LABEL]);
  });

  it("opens on the week's first delivery day when today is none", async () => {
    farm.deliveryDays = [deliveryDay("day-mon", MONDAY), deliveryDay("day-thu", THURSDAY)];
    farm.boxes = { [scope(MONDAY)]: boxesOf("Potatoes", 2, 3) };
    renderPage();

    expect(await screen.findByText("Potatoes")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe("commissioning.delivery_day Monday, 05.10.2026");
    expect(api.granularity).toHaveBeenLastCalledWith(granularityFor(MONDAY));
    expect(lastBoxesRequest()).toEqual(requestFor(MONDAY));
  });

  // The module loaded on Tuesday of week 41, so these show that the page
  // reads the date when it opens.
  it("opens on today's delivery day when it opens later that week", async () => {
    vi.setSystemTime(new Date(2026, 9, 9, 12, 0));
    renderPage();

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(shownIn(selectNamed(DAY))).toBe(FRIDAY_LABEL);
    expect(lastBoxesRequest()).toEqual(requestFor(FRIDAY));
  });

  it("opens on today's week when it opens in a later week", async () => {
    vi.setSystemTime(new Date(2026, 9, 13, 12, 0));
    renderPage();

    await waitFor(() => expect(api.boxesMatrix).toHaveBeenCalled());
    expect(shownIn(selectNamed(WEEK))).toBe("commissioning.week_short 42");
    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY, { delivery_week: 42 }));
  });

  it("lists another day's boxes, named after that day on paper, when the day changes", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(api.granularity).toHaveBeenLastCalledWith(granularityFor(FRIDAY));
    // Friday has two tours, but every station gets the same amounts.
    expect(tourPicker()).toBeNull();
    expect(lastBoxesRequest()).toEqual(requestFor(FRIDAY));

    await userEvent.click(downloadButton());

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.packing_list_boxes_2026_commissioning.KW41_COMMONWEEKDAYFRIDAY.pdf",
      ]),
    );
    expect(printed.documents[0].props).toMatchObject({ dayName: "COMMON.WEEKDAY_FRIDAY" });
  });
});

describe("PackingListBoxes when the amounts differ between tours", () => {
  beforeEach(() => {
    farm.granularityByDay = { [FRIDAY]: ALIKE_PER_TOUR };
    farm.boxes = {
      [scope(TUESDAY)]: TUESDAY_BOXES,
      [scope(FRIDAY, { tour: 1 })]: boxesOf("Pumpkins", 1, 1),
      [scope(FRIDAY, { tour: 2 })]: boxesOf("Beetroot", 1, 2),
    };
  });

  it("asks for one of the day's tours and lists the boxes of the first", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    const tours = tourPicker();
    expect(tours).not.toBeNull();
    expect(shownIn(tours!)).toBe(TOUR_1);
    expect(await optionsOf(tours!)).toEqual([TOUR_1, TOUR_2]);
    expect(stationPicker()).not.toBeInTheDocument();
    expect(lastBoxesRequest()).toEqual(requestFor(FRIDAY, { tour: 1 }));
  });

  it("lists another tour's boxes when the tour changes", async () => {
    renderPage();
    await screen.findByText("Carrots");
    await choose(selectNamed(DAY), FRIDAY_LABEL);
    await screen.findByText("Pumpkins");

    await choose(tourPicker()!, TOUR_2);

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(screen.queryByText("Pumpkins")).not.toBeInTheDocument();
    expect(lastBoxesRequest()).toEqual(requestFor(FRIDAY, { tour: 2 }));
  });

  it("asks only for a tour of the day, never for the whole day, whose amounts the tours don't share", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    expect(await screen.findByText("Pumpkins")).toBeInTheDocument();
    expect(api.boxesMatrix).not.toHaveBeenCalledWith(requestFor(FRIDAY));
    expect(api.boxesMatrix).toHaveBeenCalledTimes(2);
  });

  it("offers no tour on a day served by a single tour", async () => {
    farm.granularityByDay = { [TUESDAY]: ALIKE_PER_TOUR };
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(tourPicker()).toBeNull();
    expect(stationPicker()).not.toBeInTheDocument();
    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY));
  });
});

describe("PackingListBoxes when the amounts differ between stations", () => {
  beforeEach(() => {
    farm.granularityByDay = { [TUESDAY]: PER_STATION, [FRIDAY]: PER_STATION };
    farm.boxes = {
      [scope(TUESDAY, { station: FARM_SHOP.id })]: TUESDAY_BOXES,
      [scope(TUESDAY, { station: MARKET.id })]: boxesOf("Potatoes", 2, 3),
      [scope(FRIDAY, { station: MARKET.id })]: boxesOf("Beetroot", 1, 2),
    };
  });

  it("loads nothing until one of the day's stations is chosen, then lists its boxes", async () => {
    renderPage();

    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    expect(shownIn(selectNamed(STATION))).toBe("");
    expect(await optionsOf(selectNamed(STATION))).toEqual(["Farm shop", "Market"]);
    expect(api.boxesMatrix).not.toHaveBeenCalled();
    expect(bodyRows()).toHaveLength(0);
    expect(downloadButton()).toBeDisabled();

    await userEvent.click(within(openDropdown()).getByText("Market"));

    expect(await screen.findByText("Potatoes")).toBeInTheDocument();
    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY, { delivery_station: MARKET.id }));
  });

  it("lists another station's boxes when the station changes", async () => {
    renderPage();
    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    await choose(selectNamed(STATION), "Market");
    await screen.findByText("Potatoes");

    await choose(selectNamed(STATION), "Farm shop");

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.queryByText("Potatoes")).not.toBeInTheDocument();
    expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY, { delivery_station: FARM_SHOP.id }));
  });

  it("keeps the station on another day it also delivers on, without asking for a tour", async () => {
    renderPage();
    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    await choose(selectNamed(STATION), "Market");
    await screen.findByText("Potatoes");

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(shownIn(selectNamed(STATION))).toBe("Market");
    expect(api.stations).toHaveBeenLastCalledWith({ is_active: true, delivery_day: "day-fri" });
    // Friday has two tours; the station already narrows the list further.
    expect(tourPicker()).toBeNull();
    expect(lastBoxesRequest()).toEqual(requestFor(FRIDAY, { delivery_station: MARKET.id }));
  });

  it("drops the station on a day it doesn't deliver on and asks for none of its boxes there", async () => {
    renderPage();
    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    await choose(selectNamed(STATION), "Farm shop");
    await screen.findByText("Carrots");

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    await waitFor(() => expect(shownIn(selectNamed(STATION))).toBe(""));
    expect(await optionsOf(selectNamed(STATION))).toEqual(["School", "Market"]);
    expect(api.boxesMatrix).not.toHaveBeenCalledWith(
      requestFor(FRIDAY, { delivery_station: FARM_SHOP.id }),
    );
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });
});

// ── Week ────────────────────────────────────────────────────────────────────

describe("PackingListBoxes choosing the week", () => {
  it("loads the next week's delivery days, amounts and boxes from the week arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() =>
      expect(shownIn(selectNamed(DAY))).toBe("commissioning.delivery_day Tuesday, 13.10.2026"),
    );
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-17" });
    await waitFor(() =>
      expect(lastBoxesRequest()).toEqual(requestFor(TUESDAY, { delivery_week: 42 })),
    );
    expect(api.granularity).toHaveBeenLastCalledWith(granularityFor(TUESDAY, 42));
  });

  it("asks for the stored boxes once the week lies more than a week back", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastBoxesRequest()).toMatchObject({ delivery_week: 40 }));
    expect(lastBoxesRequest()).toMatchObject({ is_past: false });

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastBoxesRequest()).toMatchObject({ delivery_week: 39 }));
    expect(lastBoxesRequest()).toMatchObject({ is_past: true });
  });
});

// ── Failures ────────────────────────────────────────────────────────────────

describe("PackingListBoxes when the boxes cannot be loaded", () => {
  it("shows no other day's boxes while loading or once loading failed, then recovers", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const friday = pending<PackingBoxesMatrix>();
    api.boxesMatrix.mockImplementation(() => friday.promise);

    await choose(selectNamed(DAY), FRIDAY_LABEL);

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(lastBoxesRequest()).toEqual(requestFor(FRIDAY));
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    friday.fail(new Error("Network Error"));

    await waitFor(() => expect(isBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);
    expect(downloadButton()).toBeDisabled();

    api.boxesMatrix.mockImplementation(answerFrom(() => farm.boxes));
    await choose(selectNamed(DAY), TUESDAY_LABEL);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
  });

  it("says the boxes could not be loaded, not that there are no deliveries, and loads them on retry", async () => {
    api.boxesMatrix.mockRejectedValueOnce(new Error("Network Error"));
    renderPage();

    expect(await screen.findByText(LOAD_FAILED)).toBeInTheDocument();
    expect(screen.queryByText(NO_DELIVERIES)).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "table.retry" }));

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.queryByText(LOAD_FAILED)).not.toBeInTheDocument();
  });
});

// ── Download ────────────────────────────────────────────────────────────────

describe("PackingListBoxes download", () => {
  it("prints the day's boxes with their counts as a PDF named after the week and day", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(downloadButton());

    await waitFor(() =>
      expect(printed.files).toEqual([
        "commissioning.packing_list_boxes_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf",
      ]),
    );
    expect(printed.documents).toHaveLength(1);
    const [{ template, props }] = printed.documents;
    expect(template).toBe("PackingBoxesMatrixPDF");
    expect(props).toMatchObject({
      columns: TUESDAY_BOXES.columns,
      week: 41,
      dayName: "COMMON.WEEKDAY_TUESDAY",
      showSize: false,
      showCountRow: true,
    });
    expect(props.data).toEqual([
      expect.objectContaining({
        share_article_name: "Carrots",
        unit_label: BUNCH,
        size_label: "commissioning.medium",
        [SMALL.key]: 1,
        [MEDIUM.key]: 2,
      }),
      expect.objectContaining({ share_article_name: "Lettuce", unit_label: PIECES, note: WASH }),
      expect.objectContaining({ share_article_name: "Forest honey", size_label: "" }),
    ]);
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("PackingListBoxes on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each article as a card with its amount in every kind of box it goes into", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(figuresOn(cardOf("Carrots"))).toEqual([
      ["Veg commissioning.S", `1,0 ${BUNCH}`],
      ["Veg commissioning.M", `2,0 ${BUNCH}`],
      ["Veg commissioning.MHoney·commissioning.S", `2,0 ${BUNCH}`],
    ]);
    // A box without a base share is named by its combination alone.
    expect(figuresOn(cardOf("Forest honey"))).toEqual([
      ["Veg commissioning.MHoney·commissioning.S", `1,0 ${PIECES}`],
      [`${NO_BASE}Honey·commissioning.S`, `1,0 ${PIECES}`],
    ]);
    expect(within(cardOf("Lettuce")).getByText(WASH)).toBeInTheDocument();
  });

  it("counts the boxes of each kind on a card above the articles", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(figuresOn(cardOf("commissioning.box_count"))).toEqual([
      ["Veg commissioning.S", "12"],
      ["Veg commissioning.M", "30"],
      ["Veg commissioning.MHoney·commissioning.S", "5"],
      [`${NO_BASE}Honey·commissioning.S`, "2"],
    ]);
  });

  it("shows a spinner instead of cards while the boxes load", async () => {
    const boxes = pending<PackingBoxesMatrix>();
    api.boxesMatrix.mockImplementation(() => boxes.promise);
    renderPage();

    await waitFor(() => expect(isBusy()).toBe(true));
    expect(screen.queryByText("table.no_data")).not.toBeInTheDocument();

    boxes.answer(TUESDAY_BOXES);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(isBusy()).toBe(false);
  });

  it("labels the delivery day in the short phone format", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(shownIn(selectNamed(DAY))).toBe("Tu, 06.10.");
  });

  it("leaves out the download and the explainer", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: DOWNLOAD })).not.toBeInTheDocument();
    expect(screen.queryByText("explainers.packing_list_boxes")).not.toBeInTheDocument();
  });

  it("offers no add button and opens nothing when a card is tapped", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Carrots"));

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("PackingListBoxes render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Carrots");
    await flushMicrotasks();

    // About 10 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});
