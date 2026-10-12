/**
 * ListDeliveryStations: the office's list of delivery stations, where members
 * collect their shares — number, short name, reseller link, contact details and
 * whether the station is active, edited inline. Rendered through the real
 * useCrudListPage, EditableTable and contact and active-column hooks. The
 * generated commissioning client is the mocking boundary: its list hooks are
 * real TanStack queries around spies that answer from an in-memory server,
 * whose mutations echo the saved station the way the backend does. The
 * station-days, member-information and fee dialogs, the CSV export and the CSV
 * upload are other screens; they stand in as stubs that show which station they
 * were opened for and hand the page's callbacks to the test.
 *
 * The clock is frozen on Wednesday 13 May 2026, the date the page asks for the
 * delivery days active today and the ones that start later.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DeliveryStation, SharesDeliveryDay } from "@shared/api/generated/models";
import germanErrors from "@shared/i18n/locales/de/errors.json";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

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

// Per-test tenant settings; anything unset falls back to the caller's default.
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the signed-in user's roles from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-office", roles: auth.roles } }),
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

const api = vi.hoisted(() => ({
  listStations: vi.fn(),
  createStation: vi.fn(),
  updateStation: vi.fn(),
  destroyStation: vi.fn(),
  listDeliveryDays: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) =>
    [`/api/commissioning/${path}/`, ...(params ? [params] : [])];
  const queryHook = (path: string, request: (params?: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown) {
      return useQuery({ queryKey: queryKey(path, params), queryFn: async () => request(params) });
    };
  return {
    useCommissioningDeliveryStationsList: queryHook("delivery_stations", api.listStations),
    getCommissioningDeliveryStationsListQueryKey: (params?: unknown) => queryKey("delivery_stations", params),
    commissioningDeliveryStationsCreate: (station: unknown) => api.createStation(station),
    commissioningDeliveryStationsPartialUpdate: (id: string, station: unknown) =>
      api.updateStation(id, station),
    // The generated destroy takes the id alone, whatever else the caller hands it.
    commissioningDeliveryStationsDestroy: (id: string) => api.destroyStation(id),
    useCommissioningSharesDeliveryDaysList: queryHook("shares_delivery_days", api.listDeliveryDays),
  };
});

type Row = Record<string, unknown>;
type StationDialogStubProps = {
  open: boolean;
  deliveryStation: Row | null;
  onClose: () => void;
  onSaved: () => void;
};
type StationDaysStubProps = { visible: boolean; deliveryStation: Row | null; onClose: () => void };
type ExportCsvStubProps = {
  open: boolean;
  onClose: () => void;
  columns: { dataIndex?: string }[];
  data: Row[];
  filename?: string;
};
type CsvImportButtonStubProps = {
  uploadAllowed: boolean;
  columns: { dataIndex?: string }[];
  filename: string;
  modelName: string;
  onUploadSuccess?: () => void;
};

// The props the stubbed export and upload got on their last render.
const stubs = vi.hoisted(() => ({
  exportCsv: null as ExportCsvStubProps | null,
  csvImport: null as CsvImportButtonStubProps | null,
}));

vi.mock("@features/commissioning/modals", () => {
  const stationLabel = (station: Row | null) => `${String(station?.short_name)} (${String(station?.id)})`;
  // The member information and fee dialogs save on their own, then tell the page.
  const stationDialog = (name: string) =>
    function StationDialogStub({ open, deliveryStation, onClose, onSaved }: StationDialogStubProps) {
      return open ? (
        <div role="dialog" aria-label={name}>
          <p>{`${name} of ${stationLabel(deliveryStation)}`}</p>
          <button type="button" onClick={onSaved}>{`Save ${name}`}</button>
          <button type="button" onClick={onClose}>{`Close ${name}`}</button>
        </div>
      ) : null;
    };
  return {
    DeliveryStationDetailModal: ({ visible, deliveryStation, onClose }: StationDaysStubProps) =>
      visible ? (
        <div role="dialog" aria-label="Station days">
          <p>{`Station days of ${stationLabel(deliveryStation)}`}</p>
          <button type="button" onClick={onClose}>Close station days</button>
        </div>
      ) : null,
    DeliveryStationInfoModal: stationDialog("Member information"),
    DeliveryStationFeeModal: stationDialog("Fees"),
    ExportCsv: (props: ExportCsvStubProps) => {
      stubs.exportCsv = props;
      return props.open ? (
        <div role="dialog" aria-label="Station export">
          <button type="button" onClick={props.onClose}>Close export</button>
        </div>
      ) : null;
    },
  };
});

// Its button stands for a CSV the import endpoint took in full.
vi.mock("@shared/modals", () => ({
  CsvImportButton: (props: CsvImportButtonStubProps) => {
    stubs.csvImport = props;
    return props.uploadAllowed ? (
      <button type="button" onClick={() => props.onUploadSuccess?.()}>Import delivery stations</button>
    ) : null;
  },
}));

import ListDeliveryStations from "../ListDeliveryStations";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 4, 13, 10, 0);
const TODAY = "2026-05-13";

// Backend day numbers: 0 = Monday … 6 = Sunday.
const deliveryDay = (id: string, dayNumber: number, validFrom: string): SharesDeliveryDay => ({
  id,
  day_number: dayNumber as SharesDeliveryDay["day_number"],
  valid_from: validFrom,
  valid_until: null,
});
// Tuesdays and Fridays are delivery days today; Saturdays start in June.
const TUESDAY = deliveryDay("day-tue", 1, "2026-01-05");
const FRIDAY = deliveryDay("day-fri", 4, "2026-01-05");
const SATURDAY = deliveryDay("day-sat", 5, "2026-06-01");

/** A station as the list endpoint carries it. */
function station(overrides: Partial<DeliveryStation> & { id: string }): DeliveryStation {
  return {
    can_be_deleted: true, tour_assignment_missing: false, linked_reseller_can_be_deleted: true,
    is_active: true, short_name: null, number: null, is_also_reseller: false, is_also_seller: false,
    linked_reseller: null, company_name: null, first_name: null, last_name: null,
    address: "", zip_code: "", city: "", email: null, phone: null,
    ...overrides,
  };
}

// Has deliveries, so the backend protects it; also a reseller with orders.
const FARM_SHOP = station({
  id: "st-farm-shop", number: 1, short_name: "Farm shop", company_name: "Hofladen Gruber",
  first_name: "Anna", last_name: "Gruber", address: "Dorfstraße 1", zip_code: "4020", city: "Linz",
  email: "hofladen@example.com", phone: "+43 732 100", can_be_deleted: false,
  is_also_reseller: true, linked_reseller: "res-hofladen", linked_reseller_can_be_deleted: false,
});
const SCHOOL = station({
  id: "st-school", number: 2, short_name: "School", company_name: "Volksschule Urfahr",
  address: "Schulweg 4", zip_code: "4040", city: "Linz", email: "direktion@schule.example",
  phone: "+43 732 200",
});
// Run by a family, without a number of its own.
const CHURCH_HALL = station({
  id: "st-church-hall", short_name: "Church hall", first_name: "Maria", last_name: "Huber",
  address: "Kirchplatz 2", zip_code: "4400", city: "Steyr", phone: "+43 7252 300",
});
// Closed for good.
const OLD_MILL = station({
  id: "st-old-mill", number: 7, short_name: "Old mill", address: "Mühlgasse 9", zip_code: "4470",
  city: "Enns", is_active: false,
});

// What the server currently holds; the list requests answer from it.
let serverStations: DeliveryStation[] = [];

/** A request body as the backend takes it in: values left undefined don't
 *  survive the JSON encoding, and the table's row key is no station field. */
const sentFields = ({ key: _key, ...fields }: Row): Row =>
  Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined));

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Row) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  tenantSettings.values = {};
  Object.assign(stubs, { exportCsv: null, csvImport: null });
  serverStations = [FARM_SHOP, SCHOOL, CHURCH_HALL, OLD_MILL];
  api.listStations.mockReset().mockImplementation(async () => [...serverStations]);
  api.listDeliveryDays.mockReset().mockImplementation(async (params?: Row) =>
    params?.future ? [SATURDAY] : [TUESDAY, FRIDAY],
  );
  api.createStation.mockReset().mockImplementation(async (payload: Row) => {
    const saved = station({ ...sentFields(payload), id: "st-new" });
    serverStations = [...serverStations, saved];
    return saved;
  });
  api.updateStation.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = serverStations.find((each) => each.id === id);
    if (!current) throw httpError(404, { code: "delivery_station.not_found", message: "Not found." });
    const saved = { ...current, ...sentFields(payload), id } as DeliveryStation;
    serverStations = serverStations.map((each) => (each.id === id ? saved : each));
    return saved;
  });
  api.destroyStation.mockReset().mockImplementation(async (id: string) => {
    serverStations = serverStations.filter((each) => each.id !== id);
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const defaultOptions = { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } };
  const queryClient = new QueryClient({ defaultOptions });
  render(
    <QueryClientProvider client={queryClient}>{profiler.wrap(<ListDeliveryStations />)}</QueryClientProvider>,
  );
  return { user, profiler };
}

/** Renders the page and waits until the stations are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Farm shop");
  return rendered;
}

const PAGE_TITLE = "delivery_stations.list_delivery_stations";
const ACTIVE = "commissioning.is_active";
const RESELLER = "delivery_stations.is_also_reseller";
const NUMBER = "#";
const SHORT_NAME = "delivery_stations.short_name";
const DAYS = "delivery_stations.delivery_days";
const INFOS = "delivery_stations.infos";
const contact = (field: string) => `delivery_stations.${field}`;
const CONTACT_TITLES = ["company_name", "first_name", "last_name", "address", "zip_code", "city", "email", "phone"]
  .map(contact);
const DUPLICATE = "validation.unique.number — table.save_failed_hint";

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

const columnTitles = () =>
  Array.from(document.querySelectorAll(".ant-table-thead > tr > th")).map((th) => th.textContent?.trim() ?? "");

function rowAround(element: HTMLElement, what: string): HTMLElement {
  const row = element.closest("tr");
  if (!row) throw new Error(`No table row ${what}`);
  return row;
}
const rowOf = (text: string) => rowAround(screen.getByText(text), `shows ${text}`);
/** The row being edited inline — the one offering a save button. */
const editingRow = () => rowAround(screen.getByRole("button", { name: "table.save" }), "is being edited");

function cellOf(row: HTMLElement, columnTitle: string): HTMLElement {
  const index = columnTitles().indexOf(columnTitle);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${columnTitle}`);
  return cell;
}

/** The text of each of `titles`' cells in `row`, by column title. */
const cellTexts = (row: HTMLElement, titles: string[]) =>
  Object.fromEntries(titles.map((title) => [title, cellOf(row, title).textContent]));

const shownNames = () => bodyRows().map((row) => cellOf(row, SHORT_NAME).textContent);

/** The read-only checkbox a row shows for one of its flags. */
const flag = (row: HTMLElement, columnTitle: string) => within(cellOf(row, columnTitle)).getByRole("checkbox");

// The station-days button carries the same label as the row's own edit
// button, so each is looked up in its own cell.
const rowEditButton = (name: string) =>
  within(cellOf(rowOf(name), "table.actions")).getByRole("button", { name: "table.edit" });
// Named after its column, so it doesn't read as the row's own edit button.
const daysButton = (row: HTMLElement) => within(cellOf(row, DAYS)).queryByRole("button", { name: DAYS });
const infoButton = (row: HTMLElement) =>
  within(row).queryByRole("button", { name: "delivery_stations.member_info_title" });
const feeButton = (row: HTMLElement) => within(row).queryByRole("button", { name: "delivery_stations.fee_title" });
const deleteButton = (name: string) => within(rowOf(name)).queryByRole("button", { name: "table.delete" });
const addButton = () => screen.queryByRole("button", { name: /table\.add_record/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const pageTitle = () => screen.getByRole("heading", { level: 1, name: PAGE_TITLE });
const dialog = (name: string) => screen.queryByRole("dialog", { name });

type User = ReturnType<typeof userEvent.setup>;

const editCheckbox = (name: string) => within(editingRow()).queryByRole("checkbox", { name });
const editRow = (user: User, name: string) => user.click(rowEditButton(name));
const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));
const toggleHideInactive = (user: User) => user.click(screen.getByText("commissioning.hide_inactive"));

async function deleteRow(user: User, name: string) {
  await user.click(deleteButton(name)!);
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  const input = within(editingRow()).getByLabelText(label);
  await user.clear(input);
  await user.type(input, text);
}

/** Opens a new row and fills in the short name and address a station needs. */
async function startNewStation(user: User, shortName: string) {
  await user.click(addButton()!);
  await typeInto(user, SHORT_NAME, shortName);
  await typeInto(user, contact("address"), "Bahnhofstraße 12");
  await typeInto(user, contact("zip_code"), "4600");
  await typeInto(user, contact("city"), "Wels");
}

const created = () => sentFields(api.createStation.mock.lastCall?.[0] as Row);
const updated = () => sentFields(api.updateStation.mock.lastCall?.[1] as Row);
const createdOnce = () => waitFor(() => expect(api.createStation).toHaveBeenCalledTimes(1));
const updatedOnce = () => waitFor(() => expect(api.updateStation).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListDeliveryStations loading and layout", () => {
  it("loads every station, inactive ones included, with one unfiltered request", async () => {
    renderPage();

    expect(await screen.findByText("Farm shop")).toBeInTheDocument();
    expect(api.listStations).toHaveBeenCalledTimes(1);
    expect(api.listStations.mock.calls[0][0]).toBeUndefined();
  });

  it("asks for the delivery days active today and the ones that start later", async () => {
    await renderLoaded();

    await waitFor(() => expect(api.listDeliveryDays).toHaveBeenCalledTimes(2));
    expect(api.listDeliveryDays).toHaveBeenCalledWith({ active_at_date: TODAY });
    expect(api.listDeliveryDays).toHaveBeenCalledWith({ active_at_date: TODAY, future: true });
  });

  it("shows a spinner over the table while the stations load", async () => {
    let deliver: (rows: DeliveryStation[]) => void = () => {};
    api.listStations.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([SCHOOL]);

    expect(await screen.findByText("School")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(pageTitle()).toBeVisible();
    expect(columnTitles()).toEqual([
      "table.actions", ACTIVE, RESELLER, NUMBER, SHORT_NAME, DAYS, INFOS, ...CONTACT_TITLES,
    ]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_delivery_stations")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when there are no stations", async () => {
    serverStations = [];
    renderPage();

    await waitFor(() => expect(api.listStations).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the stations fail to load", async () => {
    api.listStations.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listStations).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(pageTitle()).toBeVisible();
    expect(addButton()).toBeEnabled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Rows ────────────────────────────────────────────────────────────────────

describe("ListDeliveryStations rows", () => {
  it("shows each station's number, short name and contact details", async () => {
    await renderLoaded();

    expect(cellTexts(rowOf("Farm shop"), [NUMBER, SHORT_NAME, ...CONTACT_TITLES])).toEqual({
      [NUMBER]: "1", [SHORT_NAME]: "Farm shop", [contact("company_name")]: "Hofladen Gruber",
      [contact("first_name")]: "Anna", [contact("last_name")]: "Gruber", [contact("address")]: "Dorfstraße 1",
      [contact("zip_code")]: "4020", [contact("city")]: "Linz", [contact("email")]: "hofladen@example.com",
      [contact("phone")]: "+43 732 100",
    });
    const churchHall = [NUMBER, contact("company_name"), contact("first_name"), contact("email")];
    expect(cellTexts(rowOf("Church hall"), churchHall)).toEqual({
      [NUMBER]: "", [contact("company_name")]: "", [contact("first_name")]: "Maria", [contact("email")]: "",
    });
  });

  it("ticks whether each station is active and also a reseller", async () => {
    await renderLoaded();

    const farmShop = rowOf("Farm shop");
    expect(flag(farmShop, ACTIVE)).toBeChecked();
    expect(flag(farmShop, RESELLER)).toBeChecked();
    expect(flag(rowOf("School"), ACTIVE)).toBeChecked();
    expect(flag(rowOf("School"), RESELLER)).not.toBeChecked();
  });

  it("gives every station a button to its delivery days and, for the office, its member information and fees", async () => {
    await renderLoaded();

    expect(bodyRows()).toHaveLength(3);
    for (const row of bodyRows()) {
      expect(daysButton(row)).toBeEnabled();
      expect(infoButton(row)).toBeEnabled();
      expect(feeButton(row)).toBeEnabled();
    }
  });
});

// ── Filters ─────────────────────────────────────────────────────────────────

describe("ListDeliveryStations filters", () => {
  it("hides inactive stations until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(shownNames()).toEqual(["Farm shop", "School", "Church hall"]);

    await toggleHideInactive(user);

    expect(shownNames()).toEqual(["Farm shop", "School", "Church hall", "Old mill"]);
    expect(flag(rowOf("Old mill"), ACTIVE)).not.toBeChecked();
  });

  it("finds stations by their contact details", async () => {
    const { user } = await renderLoaded();
    const search = screen.getByRole("searchbox", { name: "table.search_placeholder" });

    await user.type(search, "STEYR");

    expect(shownNames()).toEqual(["Church hall"]);

    await user.clear(search);
    await user.type(search, "volksschule");

    expect(shownNames()).toEqual(["School"]);
  });
});

// ── New station ─────────────────────────────────────────────────────────────

describe("ListDeliveryStations new station", () => {
  it("adds an active station with its number and contact, then offers its information and fees", async () => {
    const { user } = await renderLoaded();

    await startNewStation(user, "Station Wels");
    expect(editCheckbox(ACTIVE)).toBeChecked();
    expect(editCheckbox(RESELLER)).not.toBeChecked();
    expect(infoButton(editingRow())).not.toBeInTheDocument();
    expect(feeButton(editingRow())).not.toBeInTheDocument();
    expect(daysButton(editingRow())).not.toBeInTheDocument();
    await typeInto(user, NUMBER, "4");
    await typeInto(user, contact("company_name"), "Bahnhofcafé");
    await saveRow(user);

    await createdOnce();
    expect(created()).toEqual({
      is_active: true, is_also_reseller: false, number: "4", short_name: "Station Wels",
      company_name: "Bahnhofcafé", address: "Bahnhofstraße 12", zip_code: "4600", city: "Wels",
    });
    const wels = await waitFor(() => rowOf("Station Wels"));
    expect(cellTexts(wels, [NUMBER, contact("company_name"), contact("city")])).toEqual({
      [NUMBER]: "4", [contact("company_name")]: "Bahnhofcafé", [contact("city")]: "Wels",
    });
    expect(flag(wels, ACTIVE)).toBeChecked();
    expect(daysButton(wels)).toBeEnabled();
    expect(infoButton(wels)).toBeEnabled();
    expect(feeButton(wels)).toBeEnabled();
    expect(api.listStations).toHaveBeenCalledTimes(1);
  });

  it("refuses a new station without a short name and an address", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(4);
    expect(api.createStation).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new station", async () => {
    silenceConsoleErrors();
    const message = "Ensure this field has no more than 5 characters.";
    api.createStation.mockRejectedValue(
      httpError(400, { code: "validation_error", message, details: { zip_code: [message] } }),
    );
    const { user } = await renderLoaded();

    await startNewStation(user, "Station Wels");
    await typeInto(user, contact("zip_code"), "A-4600");
    await saveRow(user);

    expect(await screen.findByText(`${contact("zip_code")}: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(within(editingRow()).getByLabelText(contact("zip_code"))).toBeInvalid();
    expect(within(editingRow()).getByLabelText(SHORT_NAME)).toHaveValue("Station Wels");
    expect(bodyRows()).toHaveLength(4);
    expect(api.listStations).toHaveBeenCalledTimes(1);
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    expect(within(editingRow()).getByLabelText(SHORT_NAME)).toHaveValue("");
    expect(bodyRows()).toHaveLength(4);
  });
});

// ── Number check ────────────────────────────────────────────────────────────

describe("ListDeliveryStations number check", () => {
  it("refuses a new station with another station's number, and takes a free one", async () => {
    const { user } = await renderLoaded();

    await startNewStation(user, "Station Wels");
    await typeInto(user, NUMBER, "2");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(within(editingRow()).getByLabelText(NUMBER)).toBeInvalid();
    expect(api.createStation).not.toHaveBeenCalled();

    await typeInto(user, NUMBER, "5");
    await saveRow(user);

    await createdOnce();
    expect(created()).toMatchObject({ number: "5", short_name: "Station Wels" });
    expect(screen.queryByText(DUPLICATE)).not.toBeInTheDocument();
  });

  it("refuses to give a station a number another station has", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Church hall");
    await typeInto(user, NUMBER, "1");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(api.updateStation).not.toHaveBeenCalled();
  });

  it("refuses the number of an inactive station the list shows", async () => {
    const { user } = await renderLoaded();
    await toggleHideInactive(user);

    await startNewStation(user, "Station Wels");
    await typeInto(user, NUMBER, "7");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(api.createStation).not.toHaveBeenCalled();
  });

  it("refuses the number of an inactive station the list hides", async () => {
    const { user } = await renderLoaded();
    expect(screen.queryByText("Old mill")).not.toBeInTheDocument();

    await startNewStation(user, "Station Wels");
    await typeInto(user, NUMBER, "7");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(api.createStation).not.toHaveBeenCalled();
  });

  it("lets more than one station go without a number", async () => {
    const { user } = await renderLoaded();
    expect(cellOf(rowOf("Church hall"), NUMBER).textContent).toBe("");

    await startNewStation(user, "Station Wels");
    await saveRow(user);

    await createdOnce();
    expect(created()).not.toHaveProperty("number");
    expect(await waitFor(() => rowOf("Station Wels"))).toBeInTheDocument();
    expect(screen.queryByText(DUPLICATE)).not.toBeInTheDocument();
  });
});

// ── Editing and deleting ────────────────────────────────────────────────────

describe("ListDeliveryStations editing and deleting", () => {
  it("saves a changed station under its id, keeping its own number, without reloading the list", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "School");
    expect(within(editingRow()).getByLabelText(NUMBER)).toHaveValue("2");
    await typeInto(user, contact("phone"), "+43 732 299");
    await typeInto(user, contact("email"), "kanzlei@schule.example");
    await user.click(editCheckbox(RESELLER)!);
    await saveRow(user);

    await updatedOnce();
    expect(api.updateStation.mock.calls[0][0]).toBe("st-school");
    expect(updated()).toEqual({
      ...SCHOOL, phone: "+43 732 299", email: "kanzlei@schule.example", is_also_reseller: true,
    });
    expect(await screen.findByText("kanzlei@schule.example")).toBeInTheDocument();
    expect(cellOf(rowOf("School"), contact("phone"))).toHaveTextContent("+43 732 299");
    expect(flag(rowOf("School"), RESELLER)).toBeChecked();
    expect(screen.queryByText(DUPLICATE)).not.toBeInTheDocument();
    expect(api.listStations).toHaveBeenCalledTimes(1);
  });

  it("locks the short name, address and reseller link of a station in use, and offers no delete", async () => {
    const { user } = await renderLoaded();
    expect(deleteButton("Farm shop")).not.toBeInTheDocument();

    await editRow(user, "Farm shop");
    for (const label of [SHORT_NAME, contact("address"), contact("zip_code"), contact("city")]) {
      expect(within(editingRow()).queryByLabelText(label)).not.toBeInTheDocument();
    }
    expect(editCheckbox(RESELLER)).not.toBeInTheDocument();
    expect(flag(editingRow(), RESELLER)).toBeChecked();
    await typeInto(user, contact("email"), "laden@hofladen.example");
    await saveRow(user);

    await updatedOnce();
    expect(api.updateStation.mock.calls[0][0]).toBe("st-farm-shop");
    expect(updated()).toEqual({ ...FARM_SHOP, email: "laden@hofladen.example" });
  });

  it("lets the office drop the reseller link while nothing depends on the reseller", async () => {
    serverStations = [{ ...SCHOOL, is_also_reseller: true, linked_reseller: "res-school" }, FARM_SHOP];
    const { user } = await renderLoaded();

    await editRow(user, "School");
    const reseller = editCheckbox(RESELLER)!;
    expect(reseller).toBeChecked();
    await user.click(reseller);
    await saveRow(user);

    await updatedOnce();
    expect(updated()).toMatchObject({ is_also_reseller: false });
    await waitFor(() => expect(flag(rowOf("School"), RESELLER)).not.toBeChecked());
  });

  it("keeps the per-day flags a station row carries out of what it saves", async () => {
    // One flag per delivery day, named after its id, for the days active
    // today and the ones that start later.
    const dayFlags = { [TUESDAY.id!]: true, [FRIDAY.id!]: false, [SATURDAY.id!]: true };
    serverStations = [{ ...SCHOOL, ...dayFlags } as DeliveryStation, FARM_SHOP];
    const { user } = await renderLoaded();
    await waitFor(() => expect(api.listDeliveryDays).toHaveBeenCalledTimes(2));

    await editRow(user, "School");
    await typeInto(user, contact("phone"), "+43 732 299");
    await saveRow(user);

    await updatedOnce();
    expect(updated()).toEqual({ ...SCHOOL, phone: "+43 732 299" });
  });

  it("saves a station while the delivery days can't be loaded", async () => {
    api.listDeliveryDays.mockRejectedValue(httpError(500, { message: "Boom" }));
    const { user } = await renderLoaded();
    await waitFor(() => expect(api.listDeliveryDays).toHaveBeenCalledTimes(2));

    await editRow(user, "School");
    await typeInto(user, contact("phone"), "+43 732 299");
    await saveRow(user);

    await updatedOnce();
    expect(updated()).toEqual({ ...SCHOOL, phone: "+43 732 299" });
    expect(await screen.findByText("+43 732 299")).toBeInTheDocument();
  });

  it("removes a station after confirmation and reloads the list", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "School");

    await waitFor(() => expect(api.destroyStation).toHaveBeenCalledWith("st-school"));
    await waitFor(() => expect(api.listStations).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("School")).not.toBeInTheDocument();
    expect(shownNames()).toEqual(["Farm shop", "Church hall"]);
  });

  it("shows why the server refused to delete a station and keeps it", async () => {
    silenceConsoleErrors();
    api.destroyStation.mockRejectedValue(
      httpError(409, {
        code: "delivery_station.in_use",
        message: "The delivery station still has deliveries.",
        details: { station: "School", delivery_count: 12 },
      }),
    );
    const { user } = await renderLoaded();

    await deleteRow(user, "School");

    expect(await screen.findByText(germanErrors.delivery_station.in_use)).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("School")).toBeInTheDocument();
    expect(api.listStations).toHaveBeenCalledTimes(1);
  });
});

// ── Station dialogs ─────────────────────────────────────────────────────────

describe("ListDeliveryStations station dialogs", () => {
  it("opens the delivery days of the station whose days button is clicked", async () => {
    const { user } = await renderLoaded();
    expect(dialog("Station days")).not.toBeInTheDocument();

    await user.click(daysButton(rowOf("Church hall"))!);

    expect(dialog("Station days")).toHaveTextContent("Station days of Church hall (st-church-hall)");
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close station days" }));
    expect(dialog("Station days")).not.toBeInTheDocument();

    await user.click(daysButton(rowOf("School"))!);

    expect(dialog("Station days")).toHaveTextContent("Station days of School (st-school)");
  });

  it.each([
    ["member information", infoButton, "Member information"],
    ["fees", feeButton, "Fees"],
  ])("opens the %s dialog of the row's station and closes it, saved or not", async (_what, button, name) => {
    const { user } = await renderLoaded();

    await user.click(button(rowOf("School"))!);

    expect(dialog(name)).toHaveTextContent(`${name} of School (st-school)`);
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `Close ${name}` }));
    expect(dialog(name)).not.toBeInTheDocument();

    await user.click(button(rowOf("Farm shop"))!);

    expect(dialog(name)).toHaveTextContent(`${name} of Farm shop (st-farm-shop)`);
    await user.click(screen.getByRole("button", { name: `Save ${name}` }));
    expect(dialog(name)).not.toBeInTheDocument();
  });
});

// ── CSV ─────────────────────────────────────────────────────────────────────

describe("ListDeliveryStations CSV", () => {
  it("exports every station, inactive ones included, with the list's columns under its name", async () => {
    const { user } = await renderLoaded();
    expect(dialog("Station export")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /commissioning\.csv_export_delivery_stations/ }));

    expect(dialog("Station export")).toBeInTheDocument();
    expect(stubs.exportCsv?.filename).toBe(PAGE_TITLE);
    expect(stubs.exportCsv?.data.map((row) => row.id)).toEqual([
      "st-farm-shop", "st-school", "st-church-hall", "st-old-mill",
    ]);
    expect(stubs.exportCsv?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining([
        "is_active", "is_also_reseller", "number", "short_name", "company_name", "first_name", "last_name",
        "address", "zip_code", "city", "email", "phone",
      ]),
    );

    await user.click(screen.getByRole("button", { name: "Close export" }));

    expect(dialog("Station export")).not.toBeInTheDocument();
  });

  it("offers no CSV upload unless the tenant allows uploads", async () => {
    await renderLoaded();

    expect(screen.queryByRole("button", { name: "Import delivery stations" })).not.toBeInTheDocument();
  });

  it("uploads stations from a template of the list's columns and reloads the list", async () => {
    tenantSettings.values = { allow_upload_for_data_lists: true };
    const { user } = await renderLoaded();
    expect(stubs.csvImport).toMatchObject({
      modelName: "delivery_station",
      filename: "commissioning.delivery_stations_template.csv",
    });
    expect(stubs.csvImport?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining(["number", "short_name", "company_name", "address", "zip_code", "city", "email"]),
    );

    serverStations = [...serverStations, station({ id: "st-wels", short_name: "Station Wels", city: "Wels" })];
    await user.click(screen.getByRole("button", { name: "Import delivery stations" }));

    expect(await screen.findByText("Station Wels")).toBeInTheDocument();
    expect(api.listStations).toHaveBeenCalledTimes(2);
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ListDeliveryStations roles", () => {
  it.each(["office", "admin"])(
    "lets the %s add, edit and delete stations and open their information and fees",
    async (role) => {
      auth.roles = [role];
      await renderLoaded();

      expect(addButton()).toBeEnabled();
      expect(rowEditButton("School")).toBeEnabled();
      expect(deleteButton("School")).toBeEnabled();
      expect(infoButton(rowOf("School"))).toBeEnabled();
      expect(feeButton(rowOf("School"))).toBeEnabled();
    },
  );

  it.each(["management", "staff", "gardener"])(
    "shows the stations read-only to the %s, who may still look at their delivery days",
    async (role) => {
      auth.roles = [role];
      const { user } = await renderLoaded();

      expect(addButton()).not.toBeInTheDocument();
      expect(columnTitles()).not.toContain("table.actions");
      expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
      expect(infoButton(rowOf("School"))).not.toBeInTheDocument();
      expect(feeButton(rowOf("School"))).not.toBeInTheDocument();

      await user.click(screen.getByText("Volksschule Urfahr"));
      await user.keyboard("+");

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();

      await user.click(daysButton(rowOf("School"))!);

      expect(dialog("Station days")).toHaveTextContent("Station days of School (st-school)");
    },
  );

  it.each(["management", "staff", "gardener"])(
    "offers no CSV upload to the %s, whom the import refuses",
    async (role) => {
      auth.roles = [role];
      tenantSettings.values = { allow_upload_for_data_lists: true };
      await renderLoaded();

      expect(screen.queryByRole("button", { name: "csv_upload.open" })).not.toBeInTheDocument();
    },
  );
});
