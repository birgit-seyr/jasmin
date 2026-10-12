/**
 * DeliveryStationDetailModal: the station days of one delivery station — on
 * which delivery days the station is served and from when, with its capacity,
 * pickup times and special instructions — edited inline. Rendered through the
 * real EditableTable, time-bound and status column hooks and the rich-text
 * editor modal; the generated commissioning client is the mocking boundary,
 * its list hooks real TanStack queries around spies that answer from an
 * in-memory server. Quill is replaced by a plain textarea.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), which decides
 * the window the capacity floor is read from, which station days are past,
 * active or upcoming, and which Mondays a new station day may start on.
 */

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DeliveryStationDay } from "@shared/api/generated/models";
import i18n from "@shared/i18n";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// The canonical mock, with one `t` for every render as react-i18next keeps it:
// the special-instructions editor re-validates its text whenever `t` changes,
// so a new `t` per render would re-render it forever. A spy, so a test can see
// the values a message is filled with.
const i18nMock = vi.hoisted(() => ({
  t: vi.fn((key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
  ),
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

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const notify = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  validationError: vi.fn(),
}));
vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  notify,
}));

vi.mock("react-quill-new", () => ({
  default: (props: { value: string; onChange: (content: string) => void }) => (
    <textarea
      aria-label="Text"
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
    />
  ),
}));

const api = vi.hoisted(() => ({
  deliveryDays: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const stationDaysKey = (params?: unknown) => [
    "/api/commissioning/delivery_stations_days/",
    ...(params ? [params] : []),
  ];
  return {
    useCommissioningSharesDeliveryDaysList: (params?: unknown) =>
      useQuery({
        queryKey: ["/api/commissioning/shares_delivery_days/", params],
        queryFn: () => api.deliveryDays(params),
      }),
    getCommissioningDeliveryStationsDaysListQueryKey: stationDaysKey,
    useCommissioningDeliveryStationsDaysList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: stationDaysKey(params),
        queryFn: () => api.list(params),
        enabled: options?.query?.enabled,
      }),
    commissioningDeliveryStationsDaysCreate: (day: unknown) => api.create(day),
    commissioningDeliveryStationsDaysPartialUpdate: (id: string, day: unknown) =>
      api.update(id, day),
    commissioningDeliveryStationsDaysDestroy: (id: string) => api.destroy(id),
  };
});

import DeliveryStationDetailModal from "../DeliveryStationDetailModal";
import {
  NOW,
  type Station,
  STATION,
  DELIVERY_DAYS,
  stationDay,
  TUESDAY_2025,
  TUESDAY,
  THURSDAY,
} from "./deliveryStationDetailModal.fixtures";

// ── Fixtures ────────────────────────────────────────────────────────────────

// What the server currently holds; the list request answers from it.
let serverDays: DeliveryStationDay[] = [];

// ── Helpers ─────────────────────────────────────────────────────────────────

function CurrentPath() {
  return <output aria-label="Current path">{useLocation().pathname}</output>;
}

function renderModal({
  station = STATION,
  visible = true,
}: { station?: Station | null; visible?: boolean } = {}) {
  const onClose = vi.fn();
  const onQueryError = vi.fn();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    // The app reports every failed load from its query cache.
    queryCache: new QueryCache({ onError: onQueryError }),
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/commissioning/delivery-stations"]}>
        {profiler.wrap(
          <DeliveryStationDetailModal
            visible={visible}
            onClose={onClose}
            deliveryStation={station}
          />,
        )}
        <CurrentPath />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onClose, onQueryError, profiler };
}

async function renderLoaded() {
  const rendered = renderModal();
  await screen.findByText("29.12.2025");
  return rendered;
}

// The accessible names of the inputs of a row being edited.
const DELIVERY_DAY = "configuration.delivery_day";
const VALID_FROM = "configuration.valid_from";
const VALID_UNTIL = "configuration.valid_until";
const CAPACITY = "commissioning.capacity";
const PICKUP_END = "delivery.pickup_time_end";
const EXTRA_DAYS = "delivery.additional_pickup_days";

// Column headers; a header with a tooltip carries its text in its name.
const HEADER = {
  actions: /^table\.actions$/,
  tour: /^delivery_stations\.tour_assignment_missing/,
  deliveryDay: /^configuration\.delivery_day/,
  validFrom: /^configuration\.valid_from/,
  validUntil: /^configuration\.valid_until/,
  capacity: /^commissioning\.capacity/,
  peak: /^commissioning\.peak_occupancy/,
  pickupBegin: /^delivery\.pickup_time_begin/,
  pickupEnd: /^delivery\.pickup_time_end/,
  extraDays: /^delivery\.additional_pickup_days/,
  instructions: /^delivery\.special_instructions/,
};

const DISABLED_CELL = "ant-picker-cell-disabled";

function bodyRows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"),
  );
}

/** A row's cell in the column whose header matches `header`. */
function cellOf(row: HTMLElement, header: RegExp): HTMLElement {
  const index = (
    screen.getByRole("columnheader", { name: header }) as HTMLTableCellElement
  ).cellIndex;
  return (row as HTMLTableRowElement).cells[index];
}

const textOf = (row: HTMLElement, header: RegExp) =>
  cellOf(row, header).textContent;

/** The row of the station day starting on this date, as the table shows it. */
function rowStarting(displayedDate: string): HTMLElement {
  const row = bodyRows().find(
    (item) => textOf(item, HEADER.validFrom) === displayedDate,
  );
  if (!row) throw new Error(`No station day starts on ${displayedDate}`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

/** The validity status a row's status dot announces. */
const statusOf = (row: HTMLElement) =>
  within(row).getByRole("img", { name: /^members\./ }).getAttribute("aria-label");

/** The date picker dropdown open right now; a closed one stays in the DOM. */
function openCalendar(): HTMLElement {
  const open = Array.from(
    document.querySelectorAll<HTMLElement>(".ant-picker-dropdown"),
  ).filter((dropdown) => !dropdown.classList.contains("ant-picker-dropdown-hidden"));
  const calendar = open[open.length - 1];
  if (!calendar) throw new Error("No date picker is open");
  return calendar;
}

function calendarCell(isoDate: string): HTMLElement {
  const cell = openCalendar().querySelector<HTMLElement>(`td[title="${isoDate}"]`);
  if (!cell) throw new Error(`No calendar cell for ${isoDate}`);
  return cell;
}

async function openPicker(label: string) {
  await userEvent.click(within(editingRow()).getByLabelText(label));
}

async function pickDate(label: string, isoDate: string) {
  await openPicker(label);
  await userEvent.click(calendarCell(isoDate));
}

async function openDeliveryDays() {
  await userEvent.click(
    within(editingRow()).getByRole("combobox", { name: DELIVERY_DAY }),
  );
}

/** The option the open delivery-day select offers for this weekday. */
function offeredDay(weekday: string): HTMLElement {
  const option = Array.from(
    document.querySelectorAll<HTMLElement>(
      ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
    ),
  ).find((item) => item.textContent?.includes(weekday));
  if (!option) throw new Error(`No ${weekday} is offered`);
  return option;
}

async function pickDeliveryDay(weekday: string) {
  await openDeliveryDays();
  await userEvent.click(await waitFor(() => offeredDay(weekday)));
}

async function typeInto(label: string, text: string) {
  const input = within(editingRow()).getByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, text);
}

async function startNewDay() {
  await userEvent.click(
    screen.getByRole("button", { name: /table\.add_record/ }),
  );
}

async function editRow(row: HTMLElement) {
  await userEvent.click(
    within(cellOf(row, HEADER.actions)).getByRole("button", { name: "table.edit" }),
  );
}

async function save() {
  await userEvent.click(screen.getByRole("button", { name: "table.save" }));
}

const editorText = () => screen.queryByRole("textbox", { name: "Text" });

/** Opens a row's special instructions; resolves to the editor dialog. */
// The office edits the pickup info ("table.edit"); the other roles read it
// ("common.view").
async function openInstructions(row: HTMLElement, button = "table.edit"): Promise<HTMLElement> {
  await userEvent.click(within(cellOf(row, HEADER.instructions)).getByRole("button", { name: button }));
  // Under test AntD gives every modal title the same id, so the two dialogs
  // share an accessible name; the instructions are the one with their title.
  return waitFor(() => {
    const editor = screen
      .getAllByRole("dialog")
      .find((dialog) =>
        within(dialog).queryByText(/^commissioning\.special_instructions/),
      );
    if (!editor) throw new Error("The instructions editor is not open");
    return editor;
  });
}

/** Expects the save refused with `message`, above the table and on a field. */
async function expectRefused(message: string, field: RegExp) {
  expect(await screen.findByText(`${message} — table.save_failed_hint`)).toBeInTheDocument();
  expect(within(cellOf(editingRow(), field)).getByRole("alert")).toHaveTextContent(message);
}

/** The message the backend's refusal with this code is shown in. */
function backendMessage(code: string, details: Record<string, unknown>): string {
  const message = i18n.t(`errors.${code}`, details);
  expect(message).not.toBe(`errors.${code}`);
  return message;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  auth.roles = ["office"];
  Object.values(notify).forEach((spy) => spy.mockClear());
  i18nMock.t.mockClear();
  serverDays = [TUESDAY, THURSDAY, TUESDAY_2025];
  api.deliveryDays.mockReset().mockImplementation(async () => DELIVERY_DAYS);
  api.list
    .mockReset()
    .mockImplementation(async () => serverDays.map((day) => ({ ...day })));
  api.create.mockReset().mockImplementation(async (day: DeliveryStationDay) => {
    const saved = { ...day, id: "sd-new", capacity_by_week: {}, can_be_deleted: true };
    serverDays = [saved, ...serverDays];
    return saved;
  });
  api.update
    .mockReset()
    .mockImplementation(async (id: string, patch: Partial<DeliveryStationDay>) => {
      const current = serverDays.find((row) => row.id === id);
      const saved = { ...current, ...patch, id } as DeliveryStationDay;
      serverDays = serverDays.map((row) => (row.id === id ? saved : row));
      return saved;
    });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    serverDays = serverDays.filter((row) => row.id !== id);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Station days ────────────────────────────────────────────────────────────

describe("DeliveryStationDetailModal station days", () => {
  it("loads the station's days with their bookings from the current week on", async () => {
    await renderLoaded();

    expect(api.list).toHaveBeenCalledTimes(1);
    expect(api.list).toHaveBeenCalledWith({
      delivery_station: "station-mill",
      year: 2026,
      delivery_week: 41,
      num_weeks: 104,
    });
    const title = "delivery.station_delivery_days_details Mill";
    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);
  });

  it("names the station after its contact when it has no short name", async () => {
    renderModal({ station: { id: "station-mill", contact: { name: "Old Mill" } } });

    const title = "delivery.station_delivery_days_details Old Mill";
    expect(await screen.findByRole("dialog", { name: title })).toBeInTheDocument();
  });

  it("shows a spinner until the station's days have arrived", async () => {
    let answer: (days: DeliveryStationDay[]) => void = () => {};
    api.list.mockImplementationOnce(
      () =>
        new Promise<DeliveryStationDay[]>((resolve) => {
          answer = resolve;
        }),
    );
    renderModal();

    const dialog = await screen.findByRole("dialog");
    const spinner = () => dialog.querySelector(".loading-placeholder .ant-spin");
    await waitFor(() => expect(spinner()).toBeTruthy());
    expect(within(dialog).queryByRole("table")).not.toBeInTheDocument();

    answer(serverDays);

    expect(await screen.findByText("29.12.2025")).toBeInTheDocument();
    expect(dialog.querySelector(".loading-placeholder")).toBeNull();
  });

  it("asks for nothing while it is closed or has no station", async () => {
    renderModal({ visible: false });
    renderModal({ station: null });
    await flushMicrotasks();

    expect(api.list).not.toHaveBeenCalled();
  });

  it("names the columns of a station day", async () => {
    await renderLoaded();

    for (const header of Object.values(HEADER)) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
  });

  it("shows each day's delivery day, validity, capacity, pickup times and extra pickup days", async () => {
    await renderLoaded();

    const tuesday = rowStarting("29.12.2025");
    const tuesdayDay = cellOf(tuesday, HEADER.deliveryDay);
    expect(within(tuesdayDay).getByText("configuration.acronym_tuesday")).toBeInTheDocument();
    expect(within(tuesdayDay).getByText("commissioning.valid_from 06.01.2025")).toBeInTheDocument();
    expect(textOf(tuesday, HEADER.validUntil)).toBe("");
    expect(textOf(tuesday, HEADER.capacity)).toBe("20");
    expect(textOf(tuesday, HEADER.pickupBegin)).toBe("14:00");
    expect(textOf(tuesday, HEADER.pickupEnd)).toBe("18:30");
    expect(textOf(tuesday, HEADER.extraDays)).toBe("1");

    const thursday = rowStarting("19.01.2026");
    const thursdayDay = cellOf(thursday, HEADER.deliveryDay);
    expect(within(thursdayDay).getByText("configuration.acronym_thursday")).toBeInTheDocument();
    expect(textOf(thursday, HEADER.validUntil)).toBe("25.10.2026");
    expect(textOf(thursday, HEADER.capacity)).toBe("10");
    expect(textOf(thursday, HEADER.pickupBegin)).toBe("-");
    expect(textOf(thursday, HEADER.pickupEnd)).toBe("-");
  });

  it("shows the busiest week to come as the peak occupancy, leaving past weeks out", async () => {
    await renderLoaded();

    // Week 40 had 19 bookings but is over; 14 in week 43 are the most to come.
    expect(textOf(rowStarting("29.12.2025"), HEADER.peak)).toBe(
      "14 (commissioning.KW 43/2026)",
    );
    expect(textOf(rowStarting("19.01.2026"), HEADER.peak)).toBe("0");
    expect(textOf(rowStarting("06.01.2025"), HEADER.peak)).toBe("0");
  });

  it("shows the dates in the tenant's own format", async () => {
    tenantSettings.values = { date_format: "MM/DD/YYYY" };
    renderModal();
    await screen.findByText("12/29/2025");

    expect(
      within(cellOf(rowStarting("12/29/2025"), HEADER.deliveryDay)).getByText(
        "commissioning.valid_from 01/06/2025",
      ),
    ).toBeInTheDocument();
    expect(textOf(rowStarting("01/19/2026"), HEADER.validUntil)).toBe("10/25/2026");
  });

  it("shows the pickup times in the tenant's own time format", async () => {
    tenantSettings.values = { time_format: "hh:mm A" };
    await renderLoaded();

    const tuesday = rowStarting("29.12.2025");
    expect(textOf(tuesday, HEADER.pickupBegin)).toBe("02:00 PM");
    expect(textOf(tuesday, HEADER.pickupEnd)).toBe("06:30 PM");
    expect(textOf(rowStarting("19.01.2026"), HEADER.pickupBegin)).toBe("-");
  });

  it("says for each station day whether it is on a delivery tour", async () => {
    serverDays = [
      { ...TUESDAY, tour_assignment_missing: false },
      { ...THURSDAY, tour_assignment_missing: true },
    ];
    await renderLoaded();

    expect(
      within(cellOf(rowStarting("29.12.2025"), HEADER.tour)).getByRole("button", {
        name: "delivery_stations.tour_assigned",
      }),
    ).toBeInTheDocument();
    expect(
      within(cellOf(rowStarting("19.01.2026"), HEADER.tour)).getByRole("button", {
        name: "delivery_stations.tour_not_assigned",
      }),
    ).toBeInTheDocument();
  });

  it("lists upcoming station days first, then active, then ended ones, each marked", async () => {
    serverDays = [
      TUESDAY_2025,
      stationDay({ id: "sd-sat", delivery_day: "sdd-sat", valid_from: "2026-11-02" }),
      TUESDAY,
    ];
    renderModal();
    await screen.findByText("02.11.2026");

    const rows = bodyRows();
    expect(rows.map(statusOf)).toEqual([
      "members.future_active",
      "members.currently_active",
      "members.currently_inactive",
    ]);
    expect(rows.map((row) => textOf(row, HEADER.validFrom))).toEqual([
      "02.11.2026",
      "29.12.2025",
      "06.01.2025",
    ]);
  });

  it("opens the delivery tours from a station day's tour status", async () => {
    await renderLoaded();

    await userEvent.click(
      within(cellOf(rowStarting("29.12.2025"), HEADER.tour)).getByRole("button"),
    );

    expect(screen.getByRole("status", { name: "Current path" })).toHaveTextContent(
      "/commissioning/delivery-tours",
    );
  });

  it("closes from its footer", async () => {
    const { onClose } = await renderLoaded();

    await userEvent.click(screen.getByRole("button", { name: "common.close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("settles after opening instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});

// ── New station day ─────────────────────────────────────────────────────────

describe("DeliveryStationDetailModal new station day", () => {
  it("offers the delivery days with the date each runs from", async () => {
    await renderLoaded();
    await startNewDay();

    await openDeliveryDays();

    const thursday = await waitFor(() => offeredDay("configuration.acronym_thursday"));
    expect(thursday).toHaveTextContent("commissioning.valid_from 12.01.2026");
    expect(offeredDay("configuration.acronym_saturday")).toHaveTextContent(
      "commissioning.valid_from 02.11.2026",
    );
  });

  it("only offers Mondays from next Monday on as the start, and Sundays after it as the end", async () => {
    await renderLoaded();
    await startNewDay();

    await openPicker(VALID_FROM);

    // This week's Monday is past; next Monday is the first one open.
    expect(calendarCell("2026-10-05")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-12")).not.toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-13")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-19")).not.toHaveClass(DISABLED_CELL);
    await userEvent.click(calendarCell("2026-10-12"));

    await openPicker(VALID_UNTIL);

    expect(calendarCell("2026-10-11")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-17")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-18")).not.toHaveClass(DISABLED_CELL);
  });

  it("adds a station day for the station and shows it", async () => {
    await renderLoaded();
    await startNewDay();

    await pickDeliveryDay("configuration.acronym_saturday");
    await pickDate(VALID_FROM, "2026-11-02");
    await typeInto(CAPACITY, "12");
    await typeInto(EXTRA_DAYS, "1");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const payload = api.create.mock.calls[0][0];
    expect(payload).toEqual(
      expect.objectContaining({
        delivery_station: "station-mill",
        delivery_day: "sdd-sat",
        valid_from: "2026-11-02",
      }),
    );
    expect(Number(payload.capacity)).toBe(12);
    expect(Number(payload.additional_pickup_days)).toBe(1);
    const added = await waitFor(() => rowStarting("02.11.2026"));
    expect(statusOf(added)).toBe("members.future_active");
    const addedDay = cellOf(added, HEADER.deliveryDay);
    expect(within(addedDay).getByText("configuration.acronym_saturday")).toBeInTheDocument();
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });

  it("offers a day the station serves already and takes its open station day over once agreed", async () => {
    await renderLoaded();
    await startNewDay();

    await pickDeliveryDay("configuration.acronym_tuesday");
    await pickDate(VALID_FROM, "2026-10-19");
    await typeInto(CAPACITY, "24");
    await save();

    await userEvent.click(
      await screen.findByRole("button", { name: "delivery_stations.takeover_confirm" }),
    );
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({ delivery_day: "sdd-tue", valid_from: "2026-10-19" }),
    );
  });

  it("refuses to save a new station day without a delivery day, start and capacity", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderLoaded();
    await startNewDay();

    await save();

    const banner = "table.save_failed_generic — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(3);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("refuses a period that overlaps the delivery day's earlier station day, in the backend's words", async () => {
    await renderLoaded();
    await startNewDay();
    await pickDeliveryDay("configuration.acronym_thursday");
    await pickDate(VALID_FROM, "2026-10-19");
    await typeInto(CAPACITY, "12");

    await save();

    const message = backendMessage("time_bound.overlap", {
      existing_valid_from: "2026-01-19",
      existing_valid_until: "2026-10-25",
    });
    await expectRefused(message, HEADER.validFrom);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("accepts a new station day that starts the day after the delivery day's last one ends", async () => {
    await renderLoaded();
    await startNewDay();
    await pickDeliveryDay("configuration.acronym_thursday");
    await pickDate(VALID_FROM, "2026-10-26");
    await typeInto(CAPACITY, "12");

    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({ delivery_day: "sdd-thu", valid_from: "2026-10-26" }),
    );
    expect(await screen.findByText("26.10.2026")).toBeInTheDocument();
    expect(textOf(rowStarting("19.01.2026"), HEADER.validUntil)).toBe("25.10.2026");
  });
});

// ── Saved station days ──────────────────────────────────────────────────────

describe("DeliveryStationDetailModal saved station days", () => {
  it("keeps a saved station day's delivery day and start", async () => {
    await renderLoaded();

    await editRow(rowStarting("29.12.2025"));

    const row = editingRow();
    expect(within(row).queryByRole("combobox", { name: DELIVERY_DAY })).not.toBeInTheDocument();
    expect(textOf(row, HEADER.deliveryDay)).toMatch(/^configuration\.acronym_tuesday/);
    expect(within(row).queryByLabelText(VALID_FROM)).not.toBeInTheDocument();
    expect(textOf(row, HEADER.validFrom)).toBe("29.12.2025");
    expect(within(row).getByLabelText(VALID_UNTIL)).toBeInTheDocument();
    expect(within(row).getByLabelText(CAPACITY)).toHaveValue("20");
  });

  it("lets a saved start move back to its delivery day's start while the tenant is onboarding", async () => {
    tenantSettings.values = { onboarding_mode: true };
    await renderLoaded();

    await editRow(rowStarting("19.01.2026"));
    await openPicker(VALID_FROM);

    // Thursday deliveries begin on 12 January; later Mondays stay closed.
    expect(calendarCell("2026-01-05")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-01-12")).not.toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-01-19")).not.toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-01-26")).toHaveClass(DISABLED_CELL);
    await userEvent.click(calendarCell("2026-01-12"));
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "sd-thu",
      expect.objectContaining({ valid_from: "2026-01-12" }),
    );
  });

  it("refuses a capacity below the busiest week to come before asking the server", async () => {
    await renderLoaded();
    await editRow(rowStarting("29.12.2025"));

    await typeInto(CAPACITY, "13");
    await save();

    const banner = "commissioning.capacity_below_peak — table.save_failed_hint";
    expect(await screen.findByText(banner)).toBeInTheDocument();
    expect(i18nMock.t).toHaveBeenCalledWith("commissioning.capacity_below_peak", {
      peak: 14,
      week: "43/2026",
    });
    expect(notify.validationError).toHaveBeenCalledWith(
      "commissioning.capacity_below_peak",
    );
    expect(within(editingRow()).getByLabelText(CAPACITY)).toHaveValue("13");
    expect(api.update).not.toHaveBeenCalled();

    await typeInto(CAPACITY, "14");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    const [id, patch] = api.update.mock.calls[0];
    expect(id).toBe("sd-tue");
    expect(Number(patch.capacity)).toBe(14);
    await waitFor(() => expect(textOf(rowStarting("29.12.2025"), HEADER.capacity)).toBe("14"));
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });

  it("refuses an end that reaches into the delivery day's open station day, in the backend's words", async () => {
    await renderLoaded();
    await editRow(rowStarting("06.01.2025"));

    await pickDate(VALID_UNTIL, "2026-01-04");
    await save();

    const message = backendMessage("time_bound.overlap", {
      existing_valid_from: "2025-12-29",
      existing_valid_until: null,
      context: "open",
    });
    await expectRefused(message, HEADER.validUntil);
    expect(api.update).not.toHaveBeenCalled();
  });

  it("saves a new pickup end and extra pickup days when Enter is pressed", async () => {
    await renderLoaded();
    await editRow(rowStarting("29.12.2025"));

    await typeInto(EXTRA_DAYS, "2");
    await typeInto(PICKUP_END, "19:15{Enter}");

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    const [id, patch] = api.update.mock.calls[0];
    expect(id).toBe("sd-tue");
    expect(patch).toEqual(
      expect.objectContaining({
        pickup_time_begin: "14:00:00",
        pickup_time_end: "19:15:00",
      }),
    );
    expect(Number(patch.additional_pickup_days)).toBe(2);
    await waitFor(() => expect(textOf(rowStarting("29.12.2025"), HEADER.pickupEnd)).toBe("19:15"));
  });

  it("deletes a station day that is not in use after confirmation", async () => {
    await renderLoaded();

    expect(
      within(rowStarting("29.12.2025")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(rowStarting("19.01.2026")).getByRole("button", { name: "table.delete" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith("sd-thu"));
    await waitFor(() => expect(screen.queryByText("19.01.2026")).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(2);
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });
});

// ── Special instructions ────────────────────────────────────────────────────

describe("DeliveryStationDetailModal special instructions", () => {
  it("opens a station day's instructions, saves the new text and closes", async () => {
    await renderLoaded();

    const editor = await openInstructions(rowStarting("29.12.2025"));
    expect(within(editor).getByText("commissioning.special_instructions Mill")).toBeInTheDocument();
    const text = within(editor).getByRole("textbox", { name: "Text" });
    expect(text).toHaveValue("<p>Key in the mailbox.</p>");
    await userEvent.clear(text);
    await userEvent.type(text, "Key at the bakery.");
    await userEvent.click(within(editor).getByRole("button", { name: /common\.save/ }));

    await waitFor(() => expect(editorText()).not.toBeInTheDocument());
    expect(api.update).toHaveBeenCalledWith("sd-tue", {
      special_instructions: "Key at the bakery.",
    });
    expect(notify.success).toHaveBeenCalledWith("common.saved_successfully");
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));

    const reopened = await openInstructions(rowStarting("29.12.2025"));
    expect(within(reopened).getByRole("textbox", { name: "Text" })).toHaveValue(
      "Key at the bakery.",
    );
  });

  it("opens empty for a station day without instructions", async () => {
    await renderLoaded();

    const editor = await openInstructions(rowStarting("19.01.2026"));

    expect(within(editor).getByRole("textbox", { name: "Text" })).toHaveValue("");
  });

  it("keeps the editor open with the text when the save fails, and says why", async () => {
    api.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          code: "validation_error",
          message: "Ensure this field has no more than 2000 characters.",
        },
      },
    });
    await renderLoaded();

    const editor = await openInstructions(rowStarting("29.12.2025"));
    const text = within(editor).getByRole("textbox", { name: "Text" });
    await userEvent.clear(text);
    await userEvent.type(text, "Key at the bakery.");
    const saveButton = within(editor).getByRole("button", { name: /common\.save/ });
    await userEvent.click(saveButton);

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith(
        "Ensure this field has no more than 2000 characters.",
      ),
    );
    await waitFor(() => expect(saveButton).not.toHaveClass("ant-btn-loading"));
    expect(within(editor).getByRole("textbox", { name: "Text" })).toHaveValue(
      "Key at the bakery.",
    );
    expect(notify.success).not.toHaveBeenCalled();
    expect(api.list).toHaveBeenCalledTimes(1);

    await userEvent.click(saveButton);

    await waitFor(() => expect(editorText()).not.toBeInTheDocument());
    expect(api.update).toHaveBeenLastCalledWith("sd-tue", {
      special_instructions: "Key at the bakery.",
    });
  });
});

// ── Empty and failed loads ──────────────────────────────────────────────────

describe("DeliveryStationDetailModal without station days", () => {
  it("says so when the station has no station days yet", async () => {
    serverDays = [];
    renderModal();

    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("reports a failed load and stops waiting for it", async () => {
    api.list.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 500, data: { message: "Server error" } },
    });
    const { onQueryError } = renderModal();

    await waitFor(() => expect(onQueryError).toHaveBeenCalledTimes(1));
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(dialog.querySelector(".loading-placeholder")).toBeNull());
    expect(bodyRows()).toHaveLength(0);
  });
});

// ── Read-only roles ─────────────────────────────────────────────────────────

describe("DeliveryStationDetailModal for read-only roles", () => {
  it.each([{ roles: ["staff"] }, { roles: ["gardener"] }, { roles: ["management"] }])(
    "shows the station days read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      await renderLoaded();

      expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("columnheader", { name: HEADER.actions })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();

      await userEvent.click(cellOf(rowStarting("29.12.2025"), HEADER.capacity));

      expect(screen.queryByLabelText(CAPACITY)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    },
  );

  it.each([{ roles: ["staff"] }, { roles: ["gardener"] }, { roles: ["management"] }])(
    "lets $roles read the pickup info but not edit it",
    async ({ roles }) => {
      auth.roles = roles;
      await renderLoaded();

      expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();
      // Only the Tuesday has pickup info; the other days offer nothing to open.
      expect(screen.getAllByRole("button", { name: "common.view" })).toHaveLength(1);

      const info = await openInstructions(rowStarting("29.12.2025"), "common.view");
      expect(within(info).getByText("commissioning.special_instructions Mill")).toBeInTheDocument();
      expect(within(info).getByText("Key in the mailbox.")).toBeInTheDocument();
      expect(within(info).queryByRole("textbox")).not.toBeInTheDocument();
      expect(within(info).queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    },
  );
});
