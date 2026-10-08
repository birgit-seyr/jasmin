/**
 * DeliveryStationFees: what the farm owes each delivery station that charges
 * a fee, net of VAT, over the year or the ISO week the office picks — a
 * read-only report, with a CSV export over any date range. Rendered through
 * the real week selector, EditableTable and date-range export dialog. The
 * generated commissioning client is the mocking boundary: its fee hook is a
 * real TanStack query around a spy that answers from an in-memory farm the way
 * the backend does — boxes delivered in the range for a fee per box, calendar
 * months or years the range touches for a monthly or yearly fee — with money
 * as decimal strings. A download is recorded, not saved.
 *
 * The clock is frozen on Wednesday 7 October 2026 (ISO week 41). The tenant
 * writes numbers the English way, with a decimal point.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DeliveryStationFees as FeeRow } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 7, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

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

// The tenant record and settings, per test; an unset setting falls back to
// the caller's default. The tenant started in 2024, so the year selector
// offers 2024 to 2027.
const tenantState = vi.hoisted(() => ({
  record: { created_at: "2024-03-04T09:00:00Z" } as Record<string, unknown>,
  settings: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    tenant: tenantState.record,
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.settings ? tenantState.settings[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => viewport.mobile }));

vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

const api = vi.hoisted(() => ({ listFees: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => ["/api/commissioning/delivery_station_fees/", ...(params ? [params] : [])];
  return {
    useCommissioningDeliveryStationFeesList: function useFeesList(params: unknown) {
      return useQuery({ queryKey: queryKey(params), queryFn: async () => api.listFees(params) });
    },
    commissioningDeliveryStationFeesList: (params: unknown) => api.listFees(params),
  };
});

const downloads = vi.hoisted(() => ({ files: [] as { blob: Blob; filename: string }[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (blob: Blob, filename: string) => downloads.files.push({ blob, filename }),
}));

import DeliveryStationFees from "../DeliveryStationFees";

// ── Fixtures ────────────────────────────────────────────────────────────────

type FeeType = "per_box" | "per_month" | "per_year";
type FeeParams = { start_date: string; end_date: string };

interface FeeStation {
  id: string;
  name: string | null;
  feeType: FeeType;
  rateCents: number;
  boxesPerDelivery?: number;
  /** 0 = Sunday … 6 = Saturday. */
  deliveryDay?: number;
}

// Six boxes every Tuesday at 1.50 a box.
const FARM_SHOP: FeeStation = {
  id: "st-farm-shop", name: "Farm shop", feeType: "per_box", rateCents: 150, boxesPerDelivery: 6, deliveryDay: 2,
};
// Ten boxes every Friday at 0.80 a box.
const SCHOOL: FeeStation = {
  id: "st-school", name: "School", feeType: "per_box", rateCents: 80, boxesPerDelivery: 10, deliveryDay: 5,
};
// 120.00 a year.
const OLD_MILL: FeeStation = { id: "st-old-mill", name: "Old mill", feeType: "per_year", rateCents: 12000 };
// 35.00 a month, with no short name of its own.
const CHURCH_HALL: FeeStation = { id: "st-church-hall", name: null, feeType: "per_month", rateCents: 3500 };

const UNITS: Record<FeeType, string> = { per_box: "boxes", per_month: "months", per_year: "years" };

/** Every day from ``start`` to ``end``, both included. */
function daysBetween(start: string, end: string): Date[] {
  const days: Date[] = [];
  for (let day = new Date(`${start}T00:00:00Z`); day <= new Date(`${end}T00:00:00Z`); ) {
    days.push(day);
    day = new Date(day.getTime() + 86_400_000);
  }
  return days;
}

/** What a station is billed for over the range, the way the backend counts it. */
function quantityFor(station: FeeStation, start: string, end: string): number {
  const [startYear, startMonth] = start.split("-").map(Number);
  const [endYear, endMonth] = end.split("-").map(Number);
  if (station.feeType === "per_month") return (endYear - startYear) * 12 + (endMonth - startMonth) + 1;
  if (station.feeType === "per_year") return endYear - startYear + 1;
  const deliveries = daysBetween(start, end).filter((day) => day.getUTCDay() === station.deliveryDay);
  return deliveries.length * (station.boxesPerDelivery ?? 0);
}

const money = (cents: number) => (cents / 100).toFixed(2);

// The stations the farm pays a fee, in the backend's order.
let feeStations: FeeStation[] = [];

function feesFor({ start_date, end_date }: FeeParams): FeeRow[] {
  return feeStations.map((station) => {
    const quantity = quantityFor(station, start_date, end_date);
    return {
      delivery_station: station.id, delivery_station_name: station.name, start_date, end_date,
      fee_type: station.feeType, quantity, quantity_unit: UNITS[station.feeType],
      rate_net: money(station.rateCents), total_net: money(station.rateCents * quantity), lines: [],
    };
  });
}

const YEAR_2026 = { start_date: "2026-01-01", end_date: "2026-12-31" };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantState.settings = { number_locale: "en-US" };
  viewport.mobile = false;
  downloads.files = [];
  feeStations = [FARM_SHOP, SCHOOL, OLD_MILL, CHURCH_HALL];
  api.listFees.mockReset().mockImplementation(async (params: FeeParams) => feesFor(params));
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<DeliveryStationFees />)}</QueryClientProvider>);
  return { user, profiler };
}

/** Renders the page and waits until the year's fees are listed. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Farm shop");
  return rendered;
}

const TITLE = "commissioning.station_fees";
const STATION = "commissioning.delivery_station";
const QUANTITY = "commissioning.quantity";
const RATE = "commissioning.rate_net";
const TOTAL = "commissioning.total_net";
const PER_BOX = "commissioning.fee_type_per_box";
const PER_MONTH = "commissioning.fee_type_per_month";
const PER_YEAR = "commissioning.fee_type_per_year";
const ALL_WEEKS = "commissioning.all_delivery_weeks";

type User = ReturnType<typeof userEvent.setup>;

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

const columnTitles = () =>
  Array.from(document.querySelectorAll(".ant-table-thead > tr > th")).map((th) => th.textContent?.trim() ?? "");

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest<HTMLElement>("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

function cellOf(row: HTMLElement, columnTitle: string): HTMLElement {
  const index = columnTitles().indexOf(columnTitle);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${columnTitle}`);
  return cell;
}

/** The quantity, rate and total a station's row shows. */
const amountsOf = (station: string) =>
  [QUANTITY, RATE, TOTAL].map((title) => cellOf(rowOf(station), title).textContent);

const shownStations = () => bodyRows().map((row) => cellOf(row, STATION).textContent);

// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");

const yearSelect = () => screen.getByRole("combobox", { name: "common.year" });
const weekSelect = () => screen.getByRole("combobox", { name: "common.week" });
const weekArrow = (direction: "common.previous" | "common.next") =>
  screen.getByRole("button", { name: direction });

/** The label a select shows for its current value. */
const selectedIn = (select: HTMLElement) =>
  select.closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent ?? "";

function openPopup(selector: string): HTMLElement {
  const popups = Array.from(document.querySelectorAll<HTMLElement>(selector));
  const popup = popups.filter((each) => !/-hidden\b/.test(each.className)).pop();
  if (!popup) throw new Error(`Nothing open matches ${selector}`);
  return popup;
}

async function choose(user: User, select: HTMLElement, option: string) {
  await user.click(select);
  const offered = openPopup(".ant-select-dropdown").querySelectorAll<HTMLElement>(".ant-select-item-option");
  const match = Array.from(offered).find((each) => each.textContent === option);
  if (!match) throw new Error(`${option} is not offered`);
  await user.click(match);
}

const lastRequest = () => api.listFees.mock.lastCall?.[0];

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

const readText = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });

/** The cells of each line of a downloaded CSV, in the tenant's default format. */
async function csvLines(blob: Blob): Promise<string[][]> {
  const text = (await readText(blob)).replace(/^\uFEFF/, "");
  return text.split("\n").map((line) => line.split(";"));
}

/** An amount written in a CSV cell, with either decimal separator. */
const csvAmount = (cell: string) => Number(cell.replace(",", "."));

// ── Loading and layout ──────────────────────────────────────────────────────

describe("DeliveryStationFees loading and layout", () => {
  it("asks for the whole of this year until a week is picked", async () => {
    await renderLoaded();

    expect(api.listFees).toHaveBeenCalledTimes(1);
    expect(api.listFees).toHaveBeenCalledWith(YEAR_2026);
    expect(selectedIn(yearSelect())).toBe("2026");
    expect(selectedIn(weekSelect())).toBe(ALL_WEEKS);
  });

  it("shows a spinner over the table while the fees load", async () => {
    const fees = pending<FeeRow[]>();
    api.listFees.mockImplementation(() => fees.promise);
    renderPage();

    await waitFor(() => expect(spinner()).toBeInTheDocument());

    fees.answer(feesFor(YEAR_2026));

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
    expect(columnTitles()).toEqual([STATION, QUANTITY, RATE, TOTAL]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.station_fees")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when no station is owed a fee", async () => {
    feeStations = [];
    renderPage();

    await waitFor(() => expect(api.listFees).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("keeps the page usable when the fees fail to load", async () => {
    api.listFees.mockRejectedValue(new Error("Network Error"));
    renderPage();

    await waitFor(() => expect(api.listFees).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
    expect(weekArrow("common.next")).toBeEnabled();
    expect(screen.getByRole("button", { name: /commissioning\.download_csv/ })).toBeEnabled();
  });

  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Rows ────────────────────────────────────────────────────────────────────

describe("DeliveryStationFees rows", () => {
  it("shows each station's billed quantity, its net rate per fee type and its net total", async () => {
    await renderLoaded();

    expect(shownStations()).toEqual(["Farm shop", "School", "Old mill", "st-church-hall"]);
    expect(amountsOf("Farm shop")).toEqual(["312 x", `1.50 € / ${PER_BOX}`, "468.00 €"]);
    expect(amountsOf("School")).toEqual(["520 x", `0.80 € / ${PER_BOX}`, "416.00 €"]);
    expect(amountsOf("Old mill")).toEqual(["1 x", `120.00 € / ${PER_YEAR}`, "120.00 €"]);
  });

  it("names a station without a short name by its id", async () => {
    await renderLoaded();

    expect(amountsOf("st-church-hall")).toEqual(["12 x", `35.00 € / ${PER_MONTH}`, "420.00 €"]);
  });

  it("shows the amounts in the tenant's currency", async () => {
    tenantState.settings = { ...tenantState.settings, currency: "CHF" };
    await renderLoaded();

    expect(amountsOf("School")).toEqual(["520 x", `0.80 CHF / ${PER_BOX}`, "416.00 CHF"]);
  });

  it("writes the amounts in the tenant's number format", async () => {
    tenantState.settings = { number_locale: "de-DE" };
    feeStations = [{ ...OLD_MILL, rateCents: 123450 }];
    renderPage();

    await screen.findByText("Old mill");
    expect(amountsOf("Old mill")).toEqual(["1 x", `1.234,50 € / ${PER_YEAR}`, "1.234,50 €"]);
  });

  it("puts a dollar sign in front of the amount", async () => {
    tenantState.settings = { ...tenantState.settings, currency: "USD" };
    await renderLoaded();

    expect(amountsOf("Farm shop")).toEqual(["312 x", `$1.50 / ${PER_BOX}`, "$468.00"]);
  });

  it("finds a station by its name", async () => {
    const { user } = await renderLoaded();

    await user.type(screen.getByRole("searchbox", { name: "table.search_placeholder" }), "SCHOOL");

    expect(shownStations()).toEqual(["School"]);
  });

  it("shows the fees read-only, with nothing to add, edit or delete", async () => {
    const { user } = await renderLoaded();

    expect(screen.queryByRole("button", { name: /table\.add_plus_icon/ })).not.toBeInTheDocument();
    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

    await user.click(screen.getByText("468.00 €"));
    await user.keyboard("+");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
  });
});

// ── Picking the period ──────────────────────────────────────────────────────

describe("DeliveryStationFees picking the period", () => {
  it("asks for the Monday to Sunday of a picked week, even when the week starts the year before", async () => {
    const { user } = await renderLoaded();

    await user.click(weekArrow("common.next"));

    await waitFor(() => expect(lastRequest()).toEqual({ start_date: "2025-12-29", end_date: "2026-01-04" }));
    await waitFor(() => expect(amountsOf("Old mill")).toEqual(["2 x", `120.00 € / ${PER_YEAR}`, "240.00 €"]));
    expect(amountsOf("Farm shop")).toEqual(["6 x", `1.50 € / ${PER_BOX}`, "9.00 €"]);

    await user.click(weekArrow("common.next"));

    await waitFor(() => expect(lastRequest()).toEqual({ start_date: "2026-01-05", end_date: "2026-01-11" }));
    await waitFor(() => expect(amountsOf("Old mill")).toEqual(["1 x", `120.00 € / ${PER_YEAR}`, "120.00 €"]));
  });

  it("steps back from the first week of a year to the last week of the year before", async () => {
    const { user } = await renderLoaded();

    await choose(user, yearSelect(), "2027");
    await waitFor(() => expect(lastRequest()).toEqual({ start_date: "2027-01-01", end_date: "2027-12-31" }));
    await user.click(weekArrow("common.next"));
    await waitFor(() => expect(lastRequest()).toEqual({ start_date: "2027-01-04", end_date: "2027-01-10" }));

    await user.click(weekArrow("common.previous"));

    await waitFor(() => expect(lastRequest()).toEqual({ start_date: "2026-12-28", end_date: "2027-01-03" }));
    expect(selectedIn(yearSelect())).toBe("2026");
  });

  it("asks for the whole of another year picked while all weeks are shown", async () => {
    const { user } = await renderLoaded();

    await choose(user, yearSelect(), "2025");

    await waitFor(() => expect(lastRequest()).toEqual({ start_date: "2025-01-01", end_date: "2025-12-31" }));
    expect(selectedIn(weekSelect())).toBe(ALL_WEEKS);
  });

  it("goes back to the whole year when all weeks are picked again", async () => {
    const { user } = await renderLoaded();
    await user.click(weekArrow("common.next"));
    await waitFor(() => expect(amountsOf("Farm shop")[2]).toBe("9.00 €"));

    await choose(user, weekSelect(), ALL_WEEKS);

    await waitFor(() => expect(amountsOf("Farm shop")[2]).toBe("468.00 €"));
    expect(lastRequest()).toEqual(YEAR_2026);
    expect(weekArrow("common.previous")).toBeDisabled();
  });

  it("shows a spinner while another week's fees load", async () => {
    const { user } = await renderLoaded();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    const week = pending<FeeRow[]>();
    api.listFees.mockImplementation(() => week.promise);

    await user.click(weekArrow("common.next"));

    await waitFor(() => expect(spinner()).toBeInTheDocument());

    week.answer(feesFor({ start_date: "2025-12-29", end_date: "2026-01-04" }));

    await waitFor(() => expect(amountsOf("Farm shop")[2]).toBe("9.00 €"));
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });
});

// ── CSV ─────────────────────────────────────────────────────────────────────

describe("DeliveryStationFees CSV", () => {
  async function openExport(user: User) {
    await user.click(screen.getByRole("button", { name: /commissioning\.download_csv/ }));
    return screen.findByRole("dialog");
  }

  async function pickPreset(user: User, dialog: HTMLElement, preset: string) {
    await user.click(within(dialog).getAllByRole("textbox")[0]);
    await user.click(within(openPopup(".ant-picker-dropdown")).getByText(preset));
  }

  const downloadIn = (dialog: HTMLElement) => within(dialog).getByRole("button", { name: /common\.download/ });

  it("exports the fees of the range the office picks, whatever the table shows", async () => {
    const { user } = await renderLoaded();
    await user.click(weekArrow("common.next"));
    await waitFor(() => expect(amountsOf("Farm shop")[2]).toBe("9.00 €"));
    const dialog = await openExport(user);
    expect(within(dialog).getByText(TITLE)).toBeInTheDocument();
    expect(downloadIn(dialog)).toBeDisabled();

    await pickPreset(user, dialog, "common.last_month");
    const [from, to] = within(dialog).getAllByRole("textbox");
    expect(from).toHaveValue("01.09.2026");
    expect(to).toHaveValue("30.09.2026");
    await user.click(downloadIn(dialog));

    await waitFor(() => expect(downloads.files).toHaveLength(1));
    expect(api.listFees).toHaveBeenCalledWith({ start_date: "2026-09-01", end_date: "2026-09-30" });
    expect(downloads.files[0].filename).toBe("station_fees_2026-09-01_2026-09-30.csv");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(amountsOf("Farm shop")[2]).toBe("9.00 €");
  });

  it("writes one line per station: name, fee type, billed quantity, net rate and net total", async () => {
    const { user } = await renderLoaded();
    const dialog = await openExport(user);
    await pickPreset(user, dialog, "common.last_month");
    await user.click(downloadIn(dialog));
    await waitFor(() => expect(downloads.files).toHaveLength(1));

    const [header, ...lines] = await csvLines(downloads.files[0].blob);

    expect(header).toEqual([STATION, "commissioning.fee_type", QUANTITY, RATE, TOTAL]);
    expect(lines.map(([station, feeType]) => [station, feeType])).toEqual([
      ["Farm shop", PER_BOX],
      ["School", PER_BOX],
      ["Old mill", PER_YEAR],
      ["st-church-hall", PER_MONTH],
    ]);
    expect(lines.map(([, , quantity]) => quantity.split(" ")[0])).toEqual(["30", "40", "1", "1"]);
    expect(lines.map(([, , , rate, total]) => [csvAmount(rate), csvAmount(total)])).toEqual([
      [1.5, 45],
      [0.8, 32],
      [120, 120],
      [35, 35],
    ]);
  });

  async function downloadLastMonth(user: User) {
    const dialog = await openExport(user);
    await pickPreset(user, dialog, "common.last_month");
    await user.click(downloadIn(dialog));
    await waitFor(() => expect(downloads.files).toHaveLength(1));
    return (await readText(downloads.files[0].blob)).replace(/^﻿/, "").split("\n");
  }

  it("writes the amounts with a decimal comma and the unit by name in the German format", async () => {
    const { user } = await renderLoaded();

    const [, ...lines] = await downloadLastMonth(user);

    expect(lines).toEqual([
      `Farm shop;${PER_BOX};30 commissioning.fee_quantity_unit.boxes;1,50;45,00`,
      `School;${PER_BOX};40 commissioning.fee_quantity_unit.boxes;0,80;32,00`,
      `Old mill;${PER_YEAR};1 commissioning.fee_quantity_unit.years;120,00;120,00`,
      `st-church-hall;${PER_MONTH};1 commissioning.fee_quantity_unit.months;35,00;35,00`,
    ]);
  });

  it("writes the tenant's English format: commas between cells, points in amounts", async () => {
    tenantState.settings = { ...tenantState.settings, csv_format: "en" };
    const { user } = await renderLoaded();

    const [header, firstLine] = await downloadLastMonth(user);

    expect(header).toBe([STATION, "commissioning.fee_type", QUANTITY, RATE, TOTAL].join(","));
    expect(firstLine).toBe(`Farm shop,${PER_BOX},30 commissioning.fee_quantity_unit.boxes,1.50,45.00`);
  });

  it("closes the export without asking for fees on cancel", async () => {
    const { user } = await renderLoaded();
    const dialog = await openExport(user);
    await pickPreset(user, dialog, "common.this_year");

    await user.click(within(dialog).getByRole("button", { name: "common.cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.listFees).toHaveBeenCalledTimes(1);
    expect(downloads.files).toHaveLength(0);
  });

  it("keeps the export open and saves nothing when the fees can't be fetched", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { user } = await renderLoaded();
    api.listFees.mockRejectedValue(new Error("Network Error"));
    const dialog = await openExport(user);
    await pickPreset(user, dialog, "common.last_month");

    await user.click(downloadIn(dialog));

    await waitFor(() => expect(api.listFees).toHaveBeenCalledTimes(2));
    await flushMicrotasks();
    expect(downloads.files).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(downloadIn(dialog)).toBeEnabled());
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("DeliveryStationFees on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  function cardOf(text: string): HTMLElement {
    const card = screen.getByText(text).closest<HTMLElement>(".mobile-card-item");
    if (!card) throw new Error(`No card shows ${text}`);
    return card;
  }

  const detailsOn = (card: HTMLElement) =>
    Array.from(card.querySelectorAll(".mobile-card-detail"), (detail) => detail.textContent);

  it("shows each station's fee on a card of its own", async () => {
    renderPage();
    await screen.findByText("Farm shop");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(detailsOn(cardOf("Farm shop"))).toEqual([
      `${QUANTITY}: 312 x`, `${RATE}: 1.50 € / ${PER_BOX}`, `${TOTAL}: 468.00 €`,
    ]);
    expect(detailsOn(cardOf("st-church-hall"))).toEqual([
      `${QUANTITY}: 12 x`, `${RATE}: 35.00 € / ${PER_MONTH}`, `${TOTAL}: 420.00 €`,
    ]);
  });

  it("offers nothing to add or edit on the cards", async () => {
    const { user } = renderPage();
    await user.click(await screen.findByText("School"));

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(within(cardOf("School")).getByRole("button", { name: "table.edit" })).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
