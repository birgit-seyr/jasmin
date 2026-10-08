/**
 * ShareWeights: up to four sample weights of each share packed for one
 * delivery day of a week, next to the share size's target weight and the
 * average of the weights taken, recorded inline by the office; plus the CSV
 * export of the average weights over a date range. Rendered through the real
 * week and delivery-day selectors, EditableTable and CSV export modal. The
 * generated commissioning client is the mocking boundary: its hooks are real
 * TanStack queries around spies that answer from an in-memory farm, and its
 * update stores the weights the way the backend does, echoing the saved
 * share. The browser download is recorded, not saved.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), before the
 * imports run as well as before every test. The page's week state reads
 * "today" when the page mounts.
 */

import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Share, SharesDeliveryDay } from "@shared/api/generated/models";
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

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

const api = vi.hoisted(() => ({
  deliveryDays: vi.fn(), shares: vi.fn(), update: vi.fn(), exportCsv: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      const enabled = options?.query?.enabled;
      return useQuery({ queryKey: queryKey(path, params), queryFn: async () => request(params), enabled });
    };
  return {
    useCommissioningSharesDeliveryDaysList: queryHook("shares_delivery_days", api.deliveryDays),
    useCommissioningSharesList: queryHook("shares", api.shares),
    getCommissioningSharesListQueryKey: (params?: unknown) => queryKey("shares", params),
    commissioningSharesPartialUpdate: (id: string, share: unknown) => api.update(id, share),
    commissioningSharesExportCsvRetrieve: (params: unknown) => api.exportCsv(params),
  };
});

// The page needs only the share-weights export; the barrel would also load
// every other modal of the app.
vi.mock("@features/commissioning/modals", async () => ({
  ExportCsvShareWeights: (await import("@features/commissioning/modals/csv/ExportCsvShareWeights"))
    .default,
}));

// The files the CSV export saved, in order.
const downloads = vi.hoisted(() => ({ files: [] as string[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (_blob: Blob, filename: string) => downloads.files.push(filename),
}));

import ShareWeights from "../ShareWeights";

// ── Fixtures ────────────────────────────────────────────────────────────────

const deliveryDay = (id: string, dayNumber: number): SharesDeliveryDay => ({
  id,
  day_number: dayNumber as SharesDeliveryDay["day_number"],
  valid_from: "2026-01-05",
  valid_until: null,
  number_of_tours: 1,
});

const TUESDAY = deliveryDay("day-tue", 1);
const FRIDAY = deliveryDay("day-fri", 4);

/** A share size: its share type, size and the weight a share of it should have. */
type ShareSize = { shareType: string; size: string; target: string | null };
const VEGETABLES_S: ShareSize = { shareType: "Vegetables", size: "S", target: "2.500" };
const VEGETABLES_M: ShareSize = { shareType: "Vegetables", size: "M", target: "4.000" };
// Fruit has no target weight.
const FRUIT_L: ShareSize = { shareType: "Fruit", size: "L", target: null };

type Weights = [string | null, string | null, string | null, string | null];
const NO_WEIGHTS: Weights = [null, null, null, null];

/** A share as the list returns it: the delivery and the weights taken of it. */
type ShareRow = Share & { id: string };

const share = (
  id: string,
  week: number,
  day: SharesDeliveryDay,
  of: ShareSize,
  weights: Weights = NO_WEIGHTS,
): ShareRow => ({
  id,
  year: 2026,
  delivery_week: week,
  delivery_day: day.id!,
  delivery_day_number: day.day_number,
  share_type_variation: `var-${of.shareType.toLowerCase()}-${of.size}`,
  share_type_name: of.shareType,
  share_type_variation_size: of.size,
  ...(of.target ? { share_type_variation_average_weight: of.target } : {}),
  changed_day_number: null,
  harvesting_day: 0,
  washing_day: 0,
  cleaning_day: 1,
  packing_day: 1,
  get_current_stock_day: 1,
  weight1: weights[0],
  weight2: weights[1],
  weight3: weights[2],
  weight4: weights[3],
});

// Tuesday of week 41: the small vegetable share weighed twice, the medium one
// not yet, the fruit share once. Friday and next Tuesday have a small
// vegetable share each.
const SMALL_TUESDAY = share("share-small-tue", 41, TUESDAY, VEGETABLES_S, ["2.450", "2.610", null, null]);
const MEDIUM_TUESDAY = share("share-medium-tue", 41, TUESDAY, VEGETABLES_M);
const FRUIT_TUESDAY = share("share-fruit-tue", 41, TUESDAY, FRUIT_L, ["1.200", null, null, null]);
const SMALL_FRIDAY = share("share-small-fri", 41, FRIDAY, VEGETABLES_S, ["2.380", null, null, null]);
const SMALL_NEXT_TUESDAY = share("share-small-next-tue", 42, TUESDAY, VEGETABLES_S);

const SMALL = "Vegetables S";
const MEDIUM = "Vegetables M";
const FRUIT = "Fruit L";

/** What Friday's small vegetable share shows from its target weight to the average. */
const FRIDAY_SMALL_WEIGHTS = ["2,500 kg", "2,380", "", "", "", "2,38 kg"];

/** What the in-memory farm holds; the request spies answer from it. */
let farm: { deliveryDays: SharesDeliveryDay[]; shares: ShareRow[] };

type Payload = Record<string, unknown>;
type SharesParams = { year: number; delivery_week: number; delivery_day: string };

/** A weight as the backend's three-decimal field stores it; empty is none. */
const weight = (value: unknown) =>
  value === null || value === undefined || value === "" ? null : Number(value).toFixed(3);

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<ShareWeights />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const DAY = "placeholder.shares_delivery_day_selector";
const NO_DAYS = "commissioning.no_delivery_days_in_week";
const FRIDAY_LABEL = "Friday, 09.10.2026";
const WEEK = "common.week";
const TARGET = "commissioning.target_weight";
const WEIGHT_1 = "commissioning.weight 1";
const WEIGHT_2 = "commissioning.weight 2";
const WEIGHT_3 = "commissioning.weight 3";
const WEIGHT_4 = "commissioning.weight 4";
const AVERAGE = "⌀";
const EXPORT = "commissioning.csv_export_average_weight";
const EXPORT_TITLE = "commissioning.export_share_weights_csv";
const EDIT_OR_DELETE = /table\.(edit|delete)/;

/** The label a select shows for its current value. */
const shownIn = (name: string) =>
  screen
    .getByRole("combobox", { name })
    .closest(".ant-select")
    ?.querySelector(".ant-select-selection-item")?.textContent ?? "";

/** What a select shows while nothing is picked. */
const placeholderIn = (name: string) =>
  screen
    .getByRole("combobox", { name })
    .closest(".ant-select")
    ?.querySelector(".ant-select-selection-placeholder")?.textContent ?? "";

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

/** Picks a delivery day from the day select by its label. */
async function chooseDay(label: string) {
  await userEvent.click(screen.getByRole("combobox", { name: DAY }));
  const option = Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).find(
    (content) => content.textContent === label,
  );
  if (!option) throw new Error(`No delivery day ${label}`);
  await userEvent.click(option);
}

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

function rowOf(label: string): HTMLElement {
  const row = screen.getByText(label).closest("tr");
  if (!row) throw new Error(`No table row shows ${label}`);
  return row;
}

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

const headerTexts = () => screen.getAllByRole("columnheader").map((header) => header.textContent ?? "");

/** The cell of a share's row under the column whose header reads ``header``. */
function cellOf(label: string, header: string): HTMLElement {
  const column = headerTexts().indexOf(header);
  if (column < 0) throw new Error(`No column ${header}`);
  return within(rowOf(label)).getAllByRole("cell")[column];
}

/** What a share's row shows from its target weight to the average. */
const weightsOf = (label: string) =>
  [TARGET, WEIGHT_1, WEIGHT_2, WEIGHT_3, WEIGHT_4, AVERAGE].map((header) => cellOf(label, header).textContent);

/** The weight input of the row being edited. */
const weightInput = (header: string) => screen.getByRole("textbox", { name: header });

/** Puts ``text`` in a weight of the row being edited, replacing what it held. */
async function typeWeight(header: string, text: string) {
  await userEvent.clear(weightInput(header));
  if (text) await userEvent.type(weightInput(header), text);
}

const save = () => userEvent.click(screen.getByRole("button", { name: "table.save" }));
const editingDone = () =>
  waitFor(() => expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument());

const tableIsBusy = () => document.querySelector('.ant-table-wrapper [aria-busy="true"]') !== null;

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

/** An API refusal in the canonical error shape. */
const refusal = (message: string, details: Record<string, unknown> = {}) => ({
  isAxiosError: true,
  message: "Request failed with status code 400",
  response: { status: 400, data: { code: "validation_error", message, details } },
});

const lastSharesRequest = () => api.shares.mock.lastCall?.[0];
const lastUpdate = () => api.update.mock.lastCall?.[1] as Payload | undefined;

/** The farm delivers on no day of the week that starts on ``monday``. */
function noDeliveryDaysInWeekOf(monday: string) {
  api.deliveryDays.mockImplementation(async ({ active_at_date }: { active_at_date?: string }) =>
    active_at_date === monday ? [] : [...farm.deliveryDays],
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  auth.roles = ["office"];
  downloads.files = [];
  farm = {
    deliveryDays: [TUESDAY, FRIDAY],
    shares: [SMALL_TUESDAY, MEDIUM_TUESDAY, FRUIT_TUESDAY, SMALL_FRIDAY, SMALL_NEXT_TUESDAY],
  };
  api.deliveryDays.mockReset().mockImplementation(async () => [...farm.deliveryDays]);
  api.shares.mockReset().mockImplementation(async (params: SharesParams) =>
    farm.shares.filter(
      (row) =>
        row.year === params.year &&
        row.delivery_week === params.delivery_week &&
        row.delivery_day === params.delivery_day,
    ),
  );
  // The update answers with the saved share, as the API does.
  api.update.mockReset().mockImplementation(async (id: string, payload: Payload) => {
    const weights = Object.fromEntries(
      ["weight1", "weight2", "weight3", "weight4"]
        .filter((field) => field in payload)
        .map((field) => [field, weight(payload[field])]),
    );
    farm.shares = farm.shares.map((row) => (row.id === id ? { ...row, ...weights } : row));
    return farm.shares.find((row) => row.id === id);
  });
  api.exportCsv.mockReset().mockResolvedValue("week;share;average\r\n41;Vegetables S;2,53\r\n");
});

afterEach(() => {
  vi.useRealTimers();
  // A test may have taken the browser offline.
  act(() => onlineManager.setOnline(true));
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("ShareWeights loading", () => {
  it("opens on this week's first delivery day and lists its shares", async () => {
    renderPage();

    expect(await screen.findByText(SMALL)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "commissioning.share_weights" })).toBeInTheDocument();
    expect(shownIn("common.year")).toBe("2026");
    expect(shownIn(WEEK)).toBe("commissioning.week_short 41");
    expect(shownIn(DAY)).toBe("Tuesday, 06.10.2026");
    // The delivery days running in the selected week.
    expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-05" });
    expect(api.shares.mock.calls).toEqual([[{ year: 2026, delivery_week: 41, delivery_day: TUESDAY.id }]]);
    // In the server's order.
    expect(screen.getAllByText(/^(Vegetables|Fruit) [SML]$/).map((cell) => cell.textContent)).toEqual([
      SMALL, MEDIUM, FRUIT,
    ]);
    expect(screen.getByText("explainers.share_weights")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: EXPORT })).toBeEnabled();
  });

  it("asks for no shares and shows no table until the week's delivery days are known", async () => {
    const days = pending<SharesDeliveryDay[]>();
    api.deliveryDays.mockImplementation(() => days.promise);
    renderPage();

    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalled());
    expect(api.shares).not.toHaveBeenCalled();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("explainers.share_weights")).toBeInTheDocument();

    days.answer([TUESDAY, FRIDAY]);

    expect(await screen.findByText(SMALL)).toBeInTheDocument();
    expect(lastSharesRequest()).toEqual({ year: 2026, delivery_week: 41, delivery_day: TUESDAY.id });
  });

  it("shows a spinner over the table while the shares load", async () => {
    const rows = pending<ShareRow[]>();
    api.shares.mockImplementation(() => rows.promise);
    renderPage();

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);

    rows.answer([SMALL_TUESDAY]);

    expect(await screen.findByText(SMALL)).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });
});

// ── Weights ─────────────────────────────────────────────────────────────────

describe("ShareWeights weights", () => {
  it("shows each share's target weight, the weights taken and their average", async () => {
    renderPage();
    await screen.findByText(SMALL);

    expect(headerTexts()).toEqual(
      expect.arrayContaining([TARGET, WEIGHT_1, WEIGHT_2, WEIGHT_3, WEIGHT_4, AVERAGE]),
    );
    // Three decimals for the weights and the target, two for the average; a
    // weight not taken leaves its cell blank.
    expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,450", "2,610", "", "", "2,53 kg"]);
    expect(weightsOf(MEDIUM)).toEqual(["4,000 kg", "", "", "", "", ""]);
    expect(weightsOf(FRUIT)).toEqual(["", "1,200", "", "", "", "1,20 kg"]);
  });

  it("writes the weights in the farm's number format", async () => {
    tenantSettings.values = { number_locale: "en-US" };
    renderPage();
    await screen.findByText(SMALL);

    expect(weightsOf(SMALL)).toEqual(["2.500 kg", "2.450", "2.610", "", "", "2.53 kg"]);
  });

  it("averages only the weights above zero", async () => {
    farm.shares = [share("share-medium-tue", 41, TUESDAY, VEGETABLES_M, ["3.000", "0.000", "5.000", null])];
    renderPage();
    await screen.findByText(MEDIUM);

    expect(weightsOf(MEDIUM)).toEqual(["4,000 kg", "3,000", "", "5,000", "", "4,00 kg"]);
  });

  it("says there are no shares on a delivery day without any", async () => {
    farm.shares = [];
    renderPage();

    await waitFor(() => expect(api.shares).toHaveBeenCalled());
    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });
});

// ── Week and day ────────────────────────────────────────────────────────────

describe("ShareWeights choosing the week and day", () => {
  it("offers the week's delivery days, each with its date", async () => {
    renderPage();
    await screen.findByText(SMALL);

    await userEvent.click(screen.getByRole("combobox", { name: DAY }));

    const options = Array.from(
      openDropdown().querySelectorAll(".ant-select-item-option-content"),
      (option) => option.textContent,
    );
    expect(options).toEqual(["Tuesday, 06.10.2026", "Friday, 09.10.2026"]);
  });

  it("loads the next week's shares of the same delivery day from the week arrow", async () => {
    renderPage();
    await screen.findByText(SMALL);

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() =>
      expect(lastSharesRequest()).toEqual({ year: 2026, delivery_week: 42, delivery_day: TUESDAY.id }),
    );
    expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-12" });
    await waitFor(() => expect(shownIn(DAY)).toBe("Tuesday, 13.10.2026"));
    await waitFor(() => expect(bodyRows()).toHaveLength(1));
    expect(weightsOf(SMALL)).toEqual(["2,500 kg", "", "", "", "", ""]);
    expect(screen.queryByText(MEDIUM)).not.toBeInTheDocument();
  });

  it("keeps the delivery day chosen and records the weights of its shares", async () => {
    renderPage();
    await screen.findByText(MEDIUM);

    await chooseDay(FRIDAY_LABEL);

    await waitFor(() => expect(weightsOf(SMALL)).toEqual(FRIDAY_SMALL_WEIGHTS));
    await flushMicrotasks();
    expect(shownIn(DAY)).toBe(FRIDAY_LABEL);
    expect(api.shares.mock.calls.map(([params]) => params.delivery_day)).toEqual([TUESDAY.id, FRIDAY.id]);
    expect(screen.queryByText(MEDIUM)).not.toBeInTheDocument();

    await userEvent.click(cellOf(SMALL, WEIGHT_2));
    await typeWeight(WEIGHT_2, "2,42");
    await save();

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith(SMALL_FRIDAY.id, expect.objectContaining({ weight2: "2.42" })),
    );
    await editingDone();
    expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,380", "2,420", "", "", "2,40 kg"]);
    expect(shownIn(DAY)).toBe(FRIDAY_LABEL);
  });

  it("steps to the next delivery day with the arrow and stays there", async () => {
    renderPage();
    await screen.findByText(MEDIUM);

    await userEvent.click(arrow(DAY, "common.next"));

    await waitFor(() => expect(weightsOf(SMALL)).toEqual(FRIDAY_SMALL_WEIGHTS));
    await flushMicrotasks();
    expect(shownIn(DAY)).toBe(FRIDAY_LABEL);
    expect(lastSharesRequest()).toEqual({ year: 2026, delivery_week: 41, delivery_day: FRIDAY.id });
    expect(screen.queryByText(MEDIUM)).not.toBeInTheDocument();
    expect(arrow(DAY, "common.next")).toBeDisabled();
    expect(arrow(DAY, "common.previous")).toBeEnabled();
  });

  it("keeps the chosen delivery day in the next week when the farm delivers on it then", async () => {
    farm.shares.push(share("share-small-next-fri", 42, FRIDAY, VEGETABLES_S, ["2.410", null, null, null]));
    renderPage();
    await screen.findByText(MEDIUM);
    await chooseDay(FRIDAY_LABEL);
    await waitFor(() => expect(weightsOf(SMALL)).toEqual(FRIDAY_SMALL_WEIGHTS));

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,410", "", "", "", "2,41 kg"]));
    await flushMicrotasks();
    expect(shownIn(DAY)).toBe("Friday, 16.10.2026");
    expect(lastSharesRequest()).toEqual({ year: 2026, delivery_week: 42, delivery_day: FRIDAY.id });
    expect(api.shares).not.toHaveBeenCalledWith(expect.objectContaining({ delivery_day: TUESDAY.id, delivery_week: 42 }));
  });

  it("shows no delivery day and no table, and asks for no shares, in a week without delivery days", async () => {
    noDeliveryDaysInWeekOf("2026-10-12");
    renderPage();
    await screen.findByText(SMALL);

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(placeholderIn(DAY)).toBe(NO_DAYS));
    await flushMicrotasks();
    expect(shownIn(DAY)).toBe("");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(NO_DAYS, { selector: ".ant-typography" })).toBeInTheDocument();
    expect(arrow(DAY, "common.previous")).toBeDisabled();
    expect(arrow(DAY, "common.next")).toBeDisabled();
    expect(api.shares).not.toHaveBeenCalledWith(expect.objectContaining({ delivery_week: 42 }));
    await userEvent.click(screen.getByRole("combobox", { name: DAY }));
    expect(within(openDropdown()).getByText(NO_DAYS)).toBeInTheDocument();

    await userEvent.click(arrow(WEEK, "common.previous"));

    expect(await screen.findByText(SMALL)).toBeInTheDocument();
    expect(shownIn(DAY)).toBe("Tuesday, 06.10.2026");
    expect(lastSharesRequest()).toEqual({ year: 2026, delivery_week: 41, delivery_day: TUESDAY.id });
    expect(screen.queryByText(NO_DAYS, { selector: ".ant-typography" })).not.toBeInTheDocument();
  });

  it("asks for the next week's shares only once that week's delivery days are in", async () => {
    renderPage();
    await screen.findByText(SMALL);
    const nextWeekDays = pending<SharesDeliveryDay[]>();
    api.deliveryDays.mockImplementation(() => nextWeekDays.promise);

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(api.deliveryDays).toHaveBeenLastCalledWith({ active_at_date: "2026-10-12" }));
    await flushMicrotasks();
    expect(api.shares).not.toHaveBeenCalledWith(expect.objectContaining({ delivery_week: 42 }));
    expect(tableIsBusy()).toBe(true);

    nextWeekDays.answer([TUESDAY, FRIDAY]);

    await waitFor(() => expect(bodyRows()).toHaveLength(1));
    expect(api.shares.mock.calls.filter(([params]) => params.delivery_week === 42)).toEqual([
      [{ year: 2026, delivery_week: 42, delivery_day: TUESDAY.id }],
    ]);
    // The page reads each week's days from the day selector's request.
    expect(api.deliveryDays.mock.calls).toEqual([
      [{ active_at_date: "2026-10-05" }],
      [{ active_at_date: "2026-10-12" }],
    ]);
  });

  it("keeps the chosen day and claims nothing about the next week while its delivery days wait for the network", async () => {
    farm.shares.push(share("share-small-next-fri", 42, FRIDAY, VEGETABLES_S, ["2.410", null, null, null]));
    renderPage();
    await screen.findByText(MEDIUM);
    await chooseDay(FRIDAY_LABEL);
    await waitFor(() => expect(weightsOf(SMALL)).toEqual(FRIDAY_SMALL_WEIGHTS));

    act(() => onlineManager.setOnline(false));
    await userEvent.click(arrow(WEEK, "common.next"));
    await flushMicrotasks();

    expect(api.deliveryDays).not.toHaveBeenCalledWith({ active_at_date: "2026-10-12" });
    expect(screen.queryAllByText(NO_DAYS)).toEqual([]);
    expect(tableIsBusy()).toBe(true);
    expect(api.shares).not.toHaveBeenCalledWith(expect.objectContaining({ delivery_week: 42 }));

    act(() => onlineManager.setOnline(true));

    await waitFor(() => expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,410", "", "", "", "2,41 kg"]));
    expect(shownIn(DAY)).toBe("Friday, 16.10.2026");
    expect(api.shares.mock.calls.filter(([params]) => params.delivery_week === 42)).toEqual([
      [{ year: 2026, delivery_week: 42, delivery_day: FRIDAY.id }],
    ]);
  });
});

// ── Recording weights ───────────────────────────────────────────────────────

describe("ShareWeights recording weights", () => {
  it("records weights for a share and shows their average as they are typed", async () => {
    renderPage();
    await screen.findByText(MEDIUM);

    await userEvent.click(cellOf(MEDIUM, WEIGHT_1));
    expect(within(rowOf(MEDIUM)).queryByRole("textbox", { name: TARGET })).not.toBeInTheDocument();
    await typeWeight(WEIGHT_1, "4,1");
    await typeWeight(WEIGHT_2, "3,9");
    expect(weightInput(WEIGHT_1)).toHaveValue("4,1");
    await waitFor(() => expect(cellOf(MEDIUM, AVERAGE)).toHaveTextContent("4,00 kg"));
    expect(api.update).not.toHaveBeenCalled();
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      MEDIUM_TUESDAY.id,
      expect.objectContaining({ weight1: "4.1", weight2: "3.9" }),
    );
    await editingDone();
    expect(weightsOf(MEDIUM)).toEqual(["4,000 kg", "4,100", "3,900", "", "", "4,00 kg"]);
    // The other shares keep their weights.
    expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,450", "2,610", "", "", "2,53 kg"]);
  });

  it("starts from the weights taken and saves a corrected one with Enter", async () => {
    renderPage();
    await screen.findByText(SMALL);

    await userEvent.click(cellOf(SMALL, WEIGHT_2));
    expect(weightInput(WEIGHT_1)).toHaveValue("2,450");
    expect(weightInput(WEIGHT_2)).toHaveValue("2,610");
    await userEvent.clear(weightInput(WEIGHT_2));
    await userEvent.type(weightInput(WEIGHT_2), "2,55{Enter}");

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith(
        SMALL_TUESDAY.id,
        expect.objectContaining({ weight1: "2.450", weight2: "2.55" }),
      ),
    );
    await editingDone();
    expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,450", "2,550", "", "", "2,50 kg"]);
  });

  it("clears a weight and leaves it out of the average", async () => {
    renderPage();
    await screen.findByText(SMALL);

    await userEvent.click(cellOf(SMALL, WEIGHT_2));
    await typeWeight(WEIGHT_2, "");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(lastUpdate()?.weight2 ?? "").toBe("");
    await editingDone();
    expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,450", "", "", "", "2,45 kg"]);
  });

  it("takes at most three decimals and no letters in a weight", async () => {
    renderPage();
    await screen.findByText(MEDIUM);

    await userEvent.click(cellOf(MEDIUM, WEIGHT_3));
    await typeWeight(WEIGHT_3, "4,1256kg");

    expect(weightInput(WEIGHT_3)).toHaveValue("4,125");
  });

  it("keeps the row open with the server's reason when a save is refused", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reason = "Ensure that there are no more than 7 digits before the decimal point.";
    api.update.mockRejectedValueOnce(refusal(reason, { weight1: [reason] }));
    renderPage();
    await screen.findByText(MEDIUM);

    await userEvent.click(cellOf(MEDIUM, WEIGHT_1));
    await typeWeight(WEIGHT_1, "41000000");
    await save();

    expect(await screen.findByText(`${WEIGHT_1}: ${reason} — table.save_failed_hint`)).toBeInTheDocument();
    expect(screen.getByText("table.save_failed_title")).toBeInTheDocument();
    expect(weightInput(WEIGHT_1)).toHaveValue("41000000");

    await typeWeight(WEIGHT_1, "4,1");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(2));
    expect(lastUpdate()).toMatchObject({ weight1: "4.1" });
    await editingDone();
    expect(cellOf(MEDIUM, WEIGHT_1)).toHaveTextContent("4,100");
    expect(screen.queryByText("table.save_failed_title")).not.toBeInTheDocument();
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ShareWeights roles", () => {
  it.each(["office", "admin"])("lets a %s login record weights", async (role) => {
    auth.roles = [role];
    renderPage();
    await screen.findByText(SMALL);

    expect(within(rowOf(SMALL)).getByRole("button", { name: "table.edit" })).toBeEnabled();
    await userEvent.click(cellOf(SMALL, WEIGHT_3));

    expect(weightInput(WEIGHT_3)).toBeInTheDocument();
  });

  it.each(["gardener", "staff", "management"])(
    "shows the weights to a %s login without a way to change them, and lets it export them",
    async (role) => {
      auth.roles = [role];
      renderPage();
      await screen.findByText(SMALL);

      expect(screen.queryByRole("button", { name: EDIT_OR_DELETE })).not.toBeInTheDocument();
      await userEvent.click(cellOf(SMALL, WEIGHT_3));

      expect(screen.queryByRole("textbox", { name: WEIGHT_3 })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
      expect(weightsOf(SMALL)).toEqual(["2,500 kg", "2,450", "2,610", "", "", "2,53 kg"]);
      expect(screen.getByRole("button", { name: EXPORT })).toBeEnabled();
    },
  );

  it("offers the office no way to add or delete a share", async () => {
    renderPage();
    await screen.findByText(SMALL);

    expect(screen.queryByRole("button", { name: /table\.add_plus_icon/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    await userEvent.keyboard("+");

    expect(bodyRows()).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });
});

// ── CSV export ──────────────────────────────────────────────────────────────

describe("ShareWeights CSV export", () => {
  async function openExport() {
    await userEvent.click(screen.getByRole("button", { name: EXPORT }));
    return screen.findByRole("dialog", { name: EXPORT_TITLE });
  }

  const downloadIn = (dialog: HTMLElement) =>
    within(dialog).getByRole("button", { name: /common\.download/ });

  it("downloads the average weights of a date range as a CSV file", async () => {
    renderPage();
    await screen.findByText(SMALL);

    const dialog = await openExport();
    expect(downloadIn(dialog)).toBeDisabled();
    await userEvent.click(within(dialog).getByPlaceholderText("Start date"));
    await userEvent.click(await screen.findByText("common.last_month"));
    await userEvent.click(downloadIn(dialog));

    await waitFor(() => expect(downloads.files).toEqual(["anteilsgewichte_2026-09-01_2026-09-30.csv"]));
    expect(api.exportCsv.mock.calls).toEqual([[{ date_from: "2026-09-01", date_to: "2026-09-30" }]]);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: EXPORT_TITLE })).not.toBeInTheDocument());
  });

  it("downloads nothing when the export is cancelled", async () => {
    renderPage();
    await screen.findByText(SMALL);

    const dialog = await openExport();
    await userEvent.click(within(dialog).getByRole("button", { name: "common.cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: EXPORT_TITLE })).not.toBeInTheDocument());
    expect(api.exportCsv).not.toHaveBeenCalled();
    expect(downloads.files).toEqual([]);
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("ShareWeights render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText(SMALL);
    await flushMicrotasks();

    // About 9 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });

  it("settles after a day is chosen and in a week without delivery days", async () => {
    noDeliveryDaysInWeekOf("2026-10-12");
    const { profiler } = renderPage();
    await screen.findByText(MEDIUM);
    await chooseDay(FRIDAY_LABEL);
    await waitFor(() => expect(weightsOf(SMALL)).toEqual(FRIDAY_SMALL_WEIGHTS));

    await userEvent.click(arrow(WEEK, "common.next"));
    await waitFor(() => expect(placeholderIn(DAY)).toBe(NO_DAYS));
    await flushMicrotasks();

    // About 40 commits in a healthy run.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});
