/**
 * ShareDays: the office plans the share days of one week. Each delivery day is
 * a row with the weekday its shares are moved to that week and the weekdays of
 * the washing, cleaning, harvesting and packing behind them, and the office
 * changes them row by row. Rendered through the real week selector and
 * EditableTable. The generated commissioning client is the mocking boundary:
 * the day list is a real TanStack query around a spy, and the list and the
 * bulk update both answer from an in-memory plan that builds its rows the way
 * the backend does.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41). The page's week
 * state starts on today's week, so the clock is set before the imports run as
 * well as before every test. The changes are made in next week, because the
 * backend refuses changes to a week that has begun.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareDayPlanningRow } from "@shared/api/generated/models";
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

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => false }));

vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

// The signed-in user's roles, per test.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles }, logout: () => {} }),
}));

const api = vi.hoisted(() => ({ days: vi.fn(), saveDays: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => [
    "/api/commissioning/shares/get_days/",
    ...(params ? [params] : []),
  ];
  function useCommissioningSharesGetDaysList(params: unknown) {
    return useQuery({ queryKey: queryKey(params), queryFn: async () => api.days(params) });
  }
  return {
    useCommissioningSharesGetDaysList,
    getCommissioningSharesGetDaysListQueryKey: queryKey,
    commissioningSharesBulkUpdateUpdate: (body: unknown, params: unknown) =>
      api.saveDays(body, params),
    commissioningSharesCreate: vi.fn(),
    commissioningSharesDestroy: vi.fn(),
  };
});

import ShareDays from "../ShareDays";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Backend day numbers: 0 = Monday … 6 = Sunday.
const MONDAY = 0;
const TUESDAY = 1;
const WEDNESDAY = 2;
const THURSDAY = 3;
const FRIDAY = 4;
const SATURDAY = 5;

/** What a weekday cell shows for a day number: the day's short name. */
const shown = (day: number) =>
  `configuration.acronym_${["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][day]}`;

type WorkDay = "harvesting_day" | "packing_day" | "washing_day" | "cleaning_day" | "get_current_stock_day";
type DayFields = Record<WorkDay | "changed_day_number", number | null>;

/** The fields of a day the bulk update applies. */
const DAY_FIELDS = [
  "changed_day_number", "harvesting_day", "packing_day", "washing_day", "cleaning_day",
  "get_current_stock_day",
] as const;

/** Each delivery day's usual weekdays for the work behind its shares. */
const USUAL: Record<number, Record<WorkDay, number | null>> = {
  [TUESDAY]: {
    harvesting_day: MONDAY, washing_day: MONDAY, cleaning_day: TUESDAY, packing_day: TUESDAY,
    get_current_stock_day: TUESDAY,
  },
  [FRIDAY]: {
    harvesting_day: THURSDAY, washing_day: THURSDAY, cleaning_day: null, packing_day: FRIDAY,
    get_current_stock_day: FRIDAY,
  },
};

/** The shares of one delivery day in one week, with the weekdays planned for them. */
type PlannedDay = { year: number; week: number; day: number } & DayFields;

const planned = (
  year: number, week: number, day: number, changes: Partial<DayFields> = {},
): PlannedDay => ({ year, week, day, changed_day_number: null, ...USUAL[day], ...changes });

/** What the Tuesday row shows in a week that keeps Tuesday's usual days. */
const USUAL_TUESDAY = {
  movedTo: "-", washing: shown(MONDAY), cleaning: shown(TUESDAY), harvesting: shown(MONDAY),
  packing: shown(TUESDAY),
};

/** What the in-memory farm has planned; the request spies answer from it. */
let plan: PlannedDay[];

/** A day's row as the backend builds it: the id is the day number + 1, and a
 *  work day other than the delivery day's usual one is flagged as changed. */
function planningRow(share: PlannedDay): ShareDayPlanningRow {
  const changed = (field: WorkDay) =>
    share[field] !== null && share[field] !== USUAL[share.day][field];
  return {
    id: share.day + 1,
    delivery_day: share.day,
    changed_day_number: share.changed_day_number,
    harvesting_day: share.harvesting_day, harvesting_day_changed: changed("harvesting_day"),
    packing_day: share.packing_day, packing_day_changed: changed("packing_day"),
    washing_day: share.washing_day, washing_day_changed: changed("washing_day"),
    cleaning_day: share.cleaning_day, cleaning_day_changed: changed("cleaning_day"),
    get_current_stock_day: share.get_current_stock_day,
    get_current_stock_day_changed: changed("get_current_stock_day"),
  };
}

type DaysParams = { year: number; delivery_week: number; day_number?: number };
type SaveBody = Record<string, unknown>;

/** The rows the backend lists: the week's delivery days in day order, or one of them. */
const listed = ({ year, delivery_week, day_number }: DaysParams) =>
  plan
    .filter(
      (share) =>
        share.year === year &&
        share.week === delivery_week &&
        (day_number === undefined || share.day === day_number),
    )
    .sort((a, b) => a.day - b.day)
    .map(planningRow);

/** Applies the body's day fields to one delivery day of a week and answers with
 *  that day's row, as the backend does. A cleared work day falls back to the
 *  delivery day's usual one. */
function applyDays(body: SaveBody, params: DaysParams) {
  plan = plan.map((share) => {
    if (
      share.year !== params.year ||
      share.week !== params.delivery_week ||
      share.day !== params.day_number
    ) {
      return share;
    }
    const next = { ...share };
    for (const field of DAY_FIELDS) {
      if (!(field in body)) continue;
      const value = body[field] as number | null;
      next[field] = value ?? (field === "changed_day_number" ? null : USUAL[share.day][field]);
    }
    return next;
  });
  return listed(params);
}

const refusal = (status: number, data: { code: string; message: string }) =>
  Object.assign(new Error(data.message), { isAxiosError: true, response: { status, data } });

// ── Helpers ─────────────────────────────────────────────────────────────────

const DELIVERY = "configuration.delivery_day_shares";
const MOVED_TO = "configuration.changed_delivery_day_shares";
const WASHING = "configuration.default_washing_day";
const CLEANING = "configuration.default_cleaning_day";
const HARVESTING = "configuration.default_harvesting_day";
const PACKING = "configuration.default_packing_day";
const YEAR = "common.year";
const WEEK = "common.week";
const PAST_WEEK = "table.past_week_readonly";
const WEEK_BEGUN = "configuration.share_days_week_begun";

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ShareDays />)}</QueryClientProvider>);
  return { profiler };
}

const lastListRequest = () => api.days.mock.lastCall?.[0] as DaysParams | undefined;
const listRequests = () => api.days.mock.calls.map(([params]) => params as DaysParams);
const lastSave = () => api.saveDays.mock.lastCall as [SaveBody, DaysParams];

/** The day fields of a saved body: what the backend applies to the day. */
const dayFieldsOf = (body: SaveBody) =>
  Object.fromEntries(DAY_FIELDS.map((field) => [field, body[field]]));

/** The label a selector shows for its current value. */
function selectedIn(name: string): string {
  const select = screen.getByRole("combobox", { name }).closest(".ant-select");
  return select?.querySelector(".ant-select-selection-item")?.textContent ?? "";
}

function openDropdown(): HTMLElement {
  const open = Array.from(document.querySelectorAll<HTMLElement>(".ant-select-dropdown")).filter(
    (dropdown) => !dropdown.classList.contains("ant-select-dropdown-hidden"),
  );
  const dropdown = open[open.length - 1];
  if (!dropdown) throw new Error("No select dropdown is open");
  return dropdown;
}

async function optionsOf(combobox: HTMLElement): Promise<string[]> {
  await userEvent.click(combobox);
  return Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map(
    (option) => option.textContent ?? "",
  );
}

async function pickOption(combobox: HTMLElement, label: string) {
  await userEvent.click(combobox);
  const option = await waitFor(() => {
    const match = Array.from(
      openDropdown().querySelectorAll<HTMLElement>(".ant-select-item-option"),
    ).find((item) => item.textContent === label);
    if (!match) throw new Error(`No option ${label} is offered`);
    return match;
  });
  await userEvent.click(option);
}

/** The previous / next arrow beside the week. */
function arrow(direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name: WEEK }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error("No stepper around the week");
  return within(stepper).getByRole("button", { name: direction });
}

function tableBody(): HTMLElement {
  const body = document.querySelector<HTMLElement>(".ant-table-tbody");
  if (!body) throw new Error("The share-day table is not rendered");
  return body;
}

const bodyRows = () =>
  Array.from(tableBody().querySelectorAll<HTMLTableRowElement>("tr.ant-table-row"));

/** The cell of ``row`` in the column headed ``title``. */
function cellIn(row: HTMLTableRowElement, title: string): HTMLTableCellElement {
  const header = screen.getByRole("columnheader", { name: title }) as HTMLTableCellElement;
  const cell = row.cells[header.cellIndex];
  if (!cell) throw new Error(`The row has no cell under ${title}`);
  return cell;
}

/** The row of a delivery day. */
function dayRow(day: number): HTMLTableRowElement {
  const row = bodyRows().find((candidate) => cellIn(candidate, DELIVERY).textContent === shown(day));
  if (!row) throw new Error(`No row for the delivery day ${shown(day)}`);
  return row;
}

const deliveryDays = () => bodyRows().map((row) => cellIn(row, DELIVERY).textContent);

/** The weekdays a delivery day's row shows. */
function planOf(day: number) {
  const text = (title: string) => cellIn(dayRow(day), title).textContent;
  return {
    movedTo: text(MOVED_TO), washing: text(WASHING), cleaning: text(CLEANING),
    harvesting: text(HARVESTING), packing: text(PACKING),
  };
}

/** The columns in which a row highlights its weekday as differing from the usual one. */
const highlightedIn = (day: number) =>
  [MOVED_TO, WASHING, CLEANING, HARVESTING, PACKING].filter(
    (title) => cellIn(dayRow(day), title).querySelector(".changed-day") !== null,
  );

function editingRow(): HTMLTableRowElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

const editor = (title: string) => within(editingRow()).getByRole("combobox", { name: title });
const save = () => userEvent.click(screen.getByRole("button", { name: "table.save" }));

/** Opens a delivery day's row by clicking its weekday in the column ``title``. */
async function openRow(day: number, title: string) {
  await userEvent.click(cellIn(dayRow(day), title));
  return editor(title);
}

/** Opens a row, picks another weekday in one of its columns and saves. */
async function change(day: number, title: string, to: number) {
  await pickOption(await openRow(day, title), shown(to));
  await save();
}

/** No way to change the plan: no edit buttons, and a click opens no row. */
async function expectReadOnly() {
  expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();
  await userEvent.click(cellIn(dayRow(TUESDAY), WASHING));
  expect(within(tableBody()).queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  expect(api.saveDays).not.toHaveBeenCalled();
}

const isBusy = (container: HTMLElement) => container.querySelector('[aria-busy="true"]') !== null;
const tableIsBusy = () => {
  const table = document.querySelector<HTMLElement>(".ant-table-wrapper");
  return table !== null && isBusy(table);
};

/** Waits until a week's delivery days are on screen. */
async function loaded(week = 41) {
  await waitFor(() => expect(lastListRequest()).toMatchObject({ delivery_week: week }));
  await waitFor(() => expect(dayRow(TUESDAY)).toBeInTheDocument());
  await waitFor(() => expect(tableIsBusy()).toBe(false));
}

async function toNextWeek() {
  await userEvent.click(arrow("common.next"));
  await loaded(42);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  plan = [
    planned(2026, 39, TUESDAY),
    planned(2026, 39, FRIDAY, { changed_day_number: SATURDAY }),
    planned(2026, 40, TUESDAY),
    planned(2026, 40, FRIDAY),
    planned(2026, 41, TUESDAY),
    planned(2026, 41, FRIDAY, { harvesting_day: WEDNESDAY }),
    // A holiday on Friday: the shares go out on Thursday, a day earlier.
    planned(2026, 42, TUESDAY),
    planned(2026, 42, FRIDAY, {
      changed_day_number: THURSDAY, harvesting_day: WEDNESDAY, washing_day: WEDNESDAY,
      packing_day: THURSDAY,
    }),
    planned(2027, 41, TUESDAY, { packing_day: MONDAY }),
  ];
  api.days.mockReset().mockImplementation(async (params: DaysParams) => listed(params));
  api.saveDays.mockReset().mockImplementation(async (body: SaveBody, params: DaysParams) =>
    applyDays(body, params),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("ShareDays loading", () => {
  it("opens on this week and lists each delivery day with the weekdays planned for it", async () => {
    renderPage();
    await loaded();

    expect(
      screen.getByRole("heading", { name: "configuration.time_management_title" }),
    ).toBeInTheDocument();
    expect(selectedIn(YEAR)).toBe("2026");
    expect(selectedIn(WEEK)).toBe("commissioning.week_short 41");
    expect(listRequests()).toEqual([{ year: 2026, delivery_week: 41 }]);
    const titles = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent)
      .filter((title) => title !== "table.actions");
    expect(titles).toEqual([DELIVERY, MOVED_TO, WASHING, CLEANING, HARVESTING, PACKING]);
    expect(deliveryDays()).toEqual([shown(TUESDAY), shown(FRIDAY)]);
    expect(planOf(TUESDAY)).toEqual(USUAL_TUESDAY);
    expect(highlightedIn(TUESDAY)).toEqual([]);
    // Friday's shares need no cleaning, and this week they are harvested a day early.
    expect(planOf(FRIDAY)).toEqual({
      movedTo: "-", washing: shown(THURSDAY), cleaning: "-", harvesting: shown(WEDNESDAY),
      packing: shown(FRIDAY),
    });
    expect(highlightedIn(FRIDAY)).toEqual([HARVESTING]);
  });

  it("shows a spinner over the table while the days load", async () => {
    let answer!: (rows: ShareDayPlanningRow[]) => void;
    api.days.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    renderPage();

    await waitFor(() => expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 41 }));
    expect(tableIsBusy()).toBe(true);
    expect(bodyRows()).toHaveLength(0);

    answer(listed({ year: 2026, delivery_week: 41 }));

    await waitFor(() => expect(deliveryDays()).toEqual([shown(TUESDAY), shown(FRIDAY)]));
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });

  it("says there is nothing to plan when the week has no shares", async () => {
    plan = [];
    renderPage();

    await waitFor(() => expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 41 }));
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("shows no rows when the days cannot be loaded, and loads another week's", async () => {
    api.days.mockImplementation(async (params: DaysParams) => {
      if (params.delivery_week === 41) throw new Error("Network Error");
      return listed(params);
    });
    renderPage();

    await waitFor(() => expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 41 }));
    await waitFor(() => expect(tableIsBusy()).toBe(false));
    expect(bodyRows()).toHaveLength(0);

    await toNextWeek();

    expect(deliveryDays()).toEqual([shown(TUESDAY), shown(FRIDAY)]);
  });
});

// ── Choosing the week ───────────────────────────────────────────────────────

describe("ShareDays choosing the week", () => {
  it("loads next week's plan from the week arrow, with the delivery moved for a holiday", async () => {
    renderPage();
    await loaded();

    await toNextWeek();

    expect(selectedIn(WEEK)).toBe("commissioning.week_short 42");
    expect(listRequests()).toEqual([
      { year: 2026, delivery_week: 41 },
      { year: 2026, delivery_week: 42 },
    ]);
    expect(planOf(TUESDAY)).toEqual(USUAL_TUESDAY);
    expect(planOf(FRIDAY)).toEqual({
      movedTo: shown(THURSDAY), washing: shown(WEDNESDAY), cleaning: "-",
      harvesting: shown(WEDNESDAY), packing: shown(THURSDAY),
    });
    expect(highlightedIn(FRIDAY)).toEqual([MOVED_TO, WASHING, HARVESTING, PACKING]);
  });

  it("loads last week's plan from the back arrow", async () => {
    renderPage();
    await loaded();

    await userEvent.click(arrow("common.previous"));
    await loaded(40);

    expect(selectedIn(WEEK)).toBe("commissioning.week_short 40");
    expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 40 });
    expect(planOf(FRIDAY).harvesting).toBe(shown(THURSDAY));
    expect(highlightedIn(FRIDAY)).toEqual([]);
  });

  it("keeps the week when another year is chosen", async () => {
    renderPage();
    await loaded();

    await pickOption(screen.getByRole("combobox", { name: YEAR }), "2027");

    await waitFor(() => expect(lastListRequest()).toEqual({ year: 2027, delivery_week: 41 }));
    await waitFor(() => expect(deliveryDays()).toEqual([shown(TUESDAY)]));
    expect(selectedIn(WEEK)).toBe("commissioning.week_short 41");
    expect(planOf(TUESDAY).packing).toBe(shown(MONDAY));
    expect(highlightedIn(TUESDAY)).toEqual([PACKING]);
  });
});

// ── Editing ─────────────────────────────────────────────────────────────────

describe("ShareDays changing a delivery day's plan", () => {
  it("saves a changed work day for the row's delivery day and week", async () => {
    renderPage();
    await loaded();
    await toNextWeek();

    await openRow(TUESDAY, WASHING);
    // The delivery day stays locked; the day it moves to and the work days open.
    for (const title of [MOVED_TO, WASHING, CLEANING, HARVESTING, PACKING]) {
      expect(editor(title)).toBeInTheDocument();
    }
    expect(within(editingRow()).queryByRole("combobox", { name: DELIVERY })).not.toBeInTheDocument();
    expect(cellIn(editingRow(), DELIVERY)).toHaveTextContent(shown(TUESDAY));
    const offered = await optionsOf(editor(WASHING));
    expect(offered.filter((label) => label !== "")).toEqual(
      [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY].map(shown),
    );
    await userEvent.click(within(openDropdown()).getByText(shown(SATURDAY)));
    await save();

    await waitFor(() => expect(planOf(TUESDAY).washing).toBe(shown(SATURDAY)));
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(api.saveDays).toHaveBeenCalledTimes(1);
    const [body, params] = lastSave();
    expect(params).toEqual({ year: 2026, delivery_week: 42, day_number: TUESDAY });
    expect(dayFieldsOf(body)).toEqual({
      changed_day_number: null, harvesting_day: MONDAY, packing_day: TUESDAY,
      washing_day: SATURDAY, cleaning_day: TUESDAY, get_current_stock_day: TUESDAY,
    });
    // The week travels in the query only; the body carries the row's days.
    expect(body).not.toHaveProperty("year");
    expect(body).not.toHaveProperty("delivery_week");
    expect(highlightedIn(TUESDAY)).toEqual([WASHING]);
    expect(planOf(FRIDAY).movedTo).toBe(shown(THURSDAY));
  });

  it("moves a delivery day and sends the row's other days along, a missing one as null", async () => {
    renderPage();
    await loaded();
    await toNextWeek();

    await change(FRIDAY, MOVED_TO, WEDNESDAY);

    await waitFor(() => expect(planOf(FRIDAY).movedTo).toBe(shown(WEDNESDAY)));
    const [body, params] = lastSave();
    expect(params).toEqual({ year: 2026, delivery_week: 42, day_number: FRIDAY });
    expect(dayFieldsOf(body)).toEqual({
      changed_day_number: WEDNESDAY, harvesting_day: WEDNESDAY, packing_day: THURSDAY,
      washing_day: WEDNESDAY, cleaning_day: null, get_current_stock_day: FRIDAY,
    });
    expect(highlightedIn(FRIDAY)).toEqual([MOVED_TO, WASHING, HARVESTING, PACKING]);
    expect(planOf(TUESDAY)).toEqual(USUAL_TUESDAY);
  });

  it("shows the saved day as the server answers with it", async () => {
    renderPage();
    await loaded();
    await toNextWeek();

    // Back on Friday's usual day, the server no longer counts the harvesting as changed.
    await change(FRIDAY, HARVESTING, THURSDAY);

    await waitFor(() => expect(planOf(FRIDAY).harvesting).toBe(shown(THURSDAY)));
    expect(highlightedIn(FRIDAY)).toEqual([MOVED_TO, WASHING, PACKING]);
    expect(listRequests()).toHaveLength(2);
  });

  it("takes the saved day out of an answer that lists the whole week", async () => {
    api.saveDays.mockImplementationOnce(async (body: SaveBody, params: DaysParams) => {
      applyDays(body, params);
      return listed({ year: params.year, delivery_week: params.delivery_week });
    });
    renderPage();
    await loaded();
    await toNextWeek();

    await change(FRIDAY, PACKING, FRIDAY);

    await waitFor(() => expect(planOf(FRIDAY).packing).toBe(shown(FRIDAY)));
    expect(deliveryDays()).toEqual([shown(TUESDAY), shown(FRIDAY)]);
    expect(highlightedIn(FRIDAY)).toEqual([MOVED_TO, WASHING, HARVESTING]);
    expect(planOf(TUESDAY)).toEqual(USUAL_TUESDAY);
  });

  it("shows the next week's days as planned there after a save, and saves them as such", async () => {
    // Every week numbers its days alike, so week 43's Tuesday has week 42's id.
    plan.push(planned(2026, 43, TUESDAY), planned(2026, 43, FRIDAY));
    renderPage();
    await loaded();
    await toNextWeek();
    await change(TUESDAY, WASHING, SATURDAY);
    await waitFor(() => expect(planOf(TUESDAY).washing).toBe(shown(SATURDAY)));

    await userEvent.click(arrow("common.next"));
    await loaded(43);

    expect(planOf(TUESDAY)).toEqual(USUAL_TUESDAY);

    await change(TUESDAY, PACKING, WEDNESDAY);

    await waitFor(() => expect(api.saveDays).toHaveBeenCalledTimes(2));
    expect(lastSave()[1]).toEqual({ year: 2026, delivery_week: 43, day_number: TUESDAY });
    expect(lastSave()[0]).toMatchObject({ washing_day: MONDAY, packing_day: WEDNESDAY });
  });

  it("undoes a holiday move by clearing the day the delivery moved to", async () => {
    renderPage();
    await loaded();
    await toNextWeek();

    await pickOption(await openRow(FRIDAY, MOVED_TO), "");
    await save();

    await waitFor(() => expect(planOf(FRIDAY).movedTo).toBe("-"));
    const [body, params] = lastSave();
    expect(params).toEqual({ year: 2026, delivery_week: 42, day_number: FRIDAY });
    expect(body.changed_day_number).toBeNull();
    expect(highlightedIn(FRIDAY)).toEqual([WASHING, HARVESTING, PACKING]);
  });

  it("clears a work day with null, so it falls back to the usual one", async () => {
    renderPage();
    await loaded();
    await toNextWeek();

    await pickOption(await openRow(FRIDAY, WASHING), "");
    await save();

    await waitFor(() => expect(planOf(FRIDAY).washing).toBe(shown(THURSDAY)));
    expect(lastSave()[0].washing_day).toBeNull();
  });

  it("keeps the row open and shows why when the server refuses the change", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reason = "You do not have permission to perform this action.";
    api.saveDays.mockRejectedValueOnce(refusal(403, { code: "permission_denied", message: reason }));
    renderPage();
    await loaded();
    await toNextWeek();

    await change(TUESDAY, WASHING, SATURDAY);

    expect(await screen.findByText("table.save_failed_title")).toBeInTheDocument();
    expect(screen.getByText(`${reason} — table.save_failed_hint`)).toBeInTheDocument();
    expect(selectedIn(WASHING)).toBe(shown(SATURDAY));
    expect(api.saveDays).toHaveBeenCalledTimes(1);

    await userEvent.click(within(editingRow()).getByRole("button", { name: "table.cancel" }));
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument(),
    );
    expect(planOf(TUESDAY)).toEqual(USUAL_TUESDAY);
  });
});

// ── Past weeks and roles ────────────────────────────────────────────────────

describe("ShareDays read-only plans", () => {
  it("shows this week read-only, since the server refuses a week that has begun", async () => {
    renderPage();
    await loaded();

    expect(screen.getByText(WEEK_BEGUN)).toBeInTheDocument();
    expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
    expect(planOf(FRIDAY).harvesting).toBe(shown(WEDNESDAY));
    await expectReadOnly();
  });

  it("shows last week read-only too", async () => {
    renderPage();
    await loaded();

    await userEvent.click(arrow("common.previous"));
    await loaded(40);

    expect(screen.getByText(WEEK_BEGUN)).toBeInTheDocument();
    await expectReadOnly();
  });

  it("shows a week more than a week back read-only, with a note", async () => {
    renderPage();
    await loaded();

    await userEvent.click(arrow("common.previous"));
    await userEvent.click(arrow("common.previous"));
    await loaded(39);

    expect(screen.getByText(PAST_WEEK)).toBeInTheDocument();
    expect(screen.queryByText(WEEK_BEGUN)).not.toBeInTheDocument();
    expect(planOf(FRIDAY).movedTo).toBe(shown(SATURDAY));
    await expectReadOnly();
  });

  it.each(["staff", "gardener", "management"])(
    "shows next week's plan read-only to the %s role",
    async (role) => {
      auth.roles = [role];
      renderPage();
      await loaded();
      await toNextWeek();

      expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
      expect(planOf(FRIDAY).movedTo).toBe(shown(THURSDAY));
      await expectReadOnly();
    },
  );

  it.each(["office", "admin"])(
    "lets the %s role change next week's days but not add or delete one",
    async (role) => {
      auth.roles = [role];
      renderPage();
      await loaded();
      await toNextWeek();

      expect(screen.queryByText(PAST_WEEK)).not.toBeInTheDocument();
      expect(screen.queryByText(WEEK_BEGUN)).not.toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: "table.edit" })).toHaveLength(2);
      expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.add_plus_icon" })).not.toBeInTheDocument();
      expect(await openRow(FRIDAY, PACKING)).toBeInTheDocument();
    },
  );
});

// ── Explainer ───────────────────────────────────────────────────────────────

describe("ShareDays explainer", () => {
  it("explains what the share days are for", async () => {
    renderPage();
    await loaded();

    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.share_days")).toBeInTheDocument();
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("ShareDays render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await loaded();
    await flushMicrotasks();

    // About 7 commits on mount; a setState-in-render loop makes thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(70);
  });
});
