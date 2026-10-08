/**
 * ListCrates: the crates the farm packs and delivers in — number, name, short
 * name and note, and whether the crate is still used — edited inline, with
 * each crate's prices one click away. Rendered through the real
 * useCrudListPage, EditableTable, active and note column hooks and the CSV
 * column picker. The generated commissioning client is the mocking boundary:
 * its list hook is a real TanStack query around a spy that answers from an
 * in-memory farm, whose mutations check a crate the way the backend's
 * serializer does and echo the saved crate. The price editor and the price
 * export are other screens; they stand in as stubs that show what they were
 * opened for. A download is recorded, not saved.
 *
 * The clock is frozen on Wednesday 7 October 2026.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Crate } from "@shared/api/generated/models";
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

// The tenant's settings, per test; an unset setting falls back to the caller's default.
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

const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({ useIsMobile: () => viewport.mobile }));

const api = vi.hoisted(() => ({
  listCrates: vi.fn(), createCrate: vi.fn(), updateCrate: vi.fn(), destroyCrate: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => ["/api/commissioning/crates/", ...(params ? [params] : [])];
  return {
    useCommissioningCratesList: function useCratesList(params?: unknown) {
      return useQuery({ queryKey: queryKey(params), queryFn: async () => api.listCrates(params) });
    },
    getCommissioningCratesListQueryKey: queryKey,
    commissioningCratesCreate: (crate: unknown) => api.createCrate(crate),
    commissioningCratesPartialUpdate: (id: string, crate: unknown) => api.updateCrate(id, crate),
    // The generated destroy takes the id alone, whatever else the caller hands it.
    commissioningCratesDestroy: (id: string) => api.destroyCrate(id),
  };
});

type PriceModalStubProps = {
  visible: boolean;
  onClose: () => void;
  crate: string | null;
  crate_name: string;
  onSave?: () => void;
};
type DialogStubProps = { open: boolean; onClose: () => void };

// The page needs only these three; the barrel would also load every other
// modal of the app. The list export is the real column picker.
vi.mock("@features/commissioning/modals", async () => ({
  ExportCsv: (await import("@features/commissioning/modals/csv/ExportCsv")).default,
  ExportCsvPricesCrate: ({ open, onClose }: DialogStubProps) =>
    open ? (
      <div role="dialog" aria-label="Crate price export">
        <button type="button" onClick={onClose}>Close price export</button>
      </div>
    ) : null,
  CratePriceModal: ({ visible, onClose, crate, crate_name, onSave }: PriceModalStubProps) =>
    visible ? (
      <div role="dialog" aria-label="Prices">
        <p>{`Prices of ${crate_name} (${crate})`}</p>
        <button type="button" onClick={onSave}>Save a price</button>
        <button type="button" onClick={onClose}>Close prices</button>
      </div>
    ) : null,
}));

const downloads = vi.hoisted(() => ({ files: [] as { blob: Blob; filename: string }[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (blob: Blob, filename: string) => downloads.files.push({ blob, filename }),
}));

import ListCrates from "../ListCrates";

// ── Fixtures ────────────────────────────────────────────────────────────────

type Row = Record<string, unknown>;

const NOW = new Date(2026, 9, 7, 12, 0);

/** A crate as the list endpoint carries it. */
const crate = (fields: Partial<Crate> & { id: string; name: string }): Crate => ({
  is_active: true, number: null, short_name: null, note: null, can_be_deleted: true, ...fields,
});

// Already on offers and deliveries, so the backend protects it.
const EURO = crate({
  id: "crate-euro", number: 1, name: "Euro crate", short_name: "E1", note: "Stackable 60 x 40 cm",
  can_be_deleted: false,
});
const HALF = crate({ id: "crate-half", number: 2, name: "Half crate", short_name: "E2" });
// Without a number of its own.
const BANANA = crate({ id: "crate-banana", name: "Banana box", short_name: "BB", note: "From the wholesaler" });
// No longer used.
const WOODEN = crate({ id: "crate-wooden", number: 7, name: "Wooden crate", short_name: "WC", is_active: false });

// The fields a client can write; the serializer ignores everything else.
const WRITABLE = ["is_active", "name", "number", "short_name", "note"];

/** The writable fields a request body carries, as the JSON encoding leaves them. */
const writableFields = (payload: Row): Row =>
  Object.fromEntries(
    Object.entries(payload).filter(([field, value]) => WRITABLE.includes(field) && value !== undefined),
  );

/** What the backend's crate serializer says about ``fields``; empty when it takes them. */
function crateErrors(fields: Row, creating: boolean): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  if (!("name" in fields)) {
    if (creating) errors.name = ["This field is required."];
  } else if (fields.name === null) {
    errors.name = ["This field may not be null."];
  } else if (String(fields.name).trim() === "") {
    errors.name = ["This field may not be blank."];
  }
  if ("number" in fields && fields.number !== null && !/^\d+$/.test(String(fields.number))) {
    errors.number = ["A valid integer is required."];
  }
  if (typeof fields.short_name === "string" && fields.short_name.length > 50) {
    errors.short_name = ["Ensure this field has no more than 50 characters."];
  }
  return errors;
}

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Row) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

function refuseIfInvalid(errors: Record<string, string[]>) {
  const fields = Object.keys(errors);
  if (fields.length === 0) return;
  throw httpError(400, {
    code: "validation_error", message: errors[fields[0]][0], details: errors,
    ...(fields.length === 1 ? { field: fields[0] } : {}),
  });
}

/** The fields as the server stores them: a number is an integer. */
const storedFields = (fields: Row): Row =>
  "number" in fields ? { ...fields, number: fields.number === null ? null : Number(fields.number) } : fields;

// What the server currently holds; the list requests answer from it.
let serverCrates: Crate[] = [];

const stored = (id: string) => serverCrates.find((each) => each.id === id);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  tenantSettings.values = {};
  viewport.mobile = false;
  downloads.files = [];
  serverCrates = [EURO, HALF, BANANA, WOODEN];
  let createdCount = 0;
  api.listCrates.mockReset().mockImplementation(async () => [...serverCrates]);
  api.createCrate.mockReset().mockImplementation(async (payload: Row) => {
    const fields = writableFields(payload);
    refuseIfInvalid(crateErrors(fields, true));
    createdCount += 1;
    const saved = crate({ ...storedFields(fields), id: `crate-new-${createdCount}` } as Crate & { id: string; name: string });
    serverCrates = [...serverCrates, saved];
    return saved;
  });
  api.updateCrate.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = stored(id);
    if (!current) throw httpError(404, { code: "crate.not_found", message: "Not found." });
    const fields = writableFields(payload);
    refuseIfInvalid(crateErrors(fields, false));
    const saved = { ...current, ...storedFields(fields), id } as Crate;
    serverCrates = serverCrates.map((each) => (each.id === id ? saved : each));
    return saved;
  });
  api.destroyCrate.mockReset().mockImplementation(async (id: string) => {
    const current = stored(id);
    if (current?.can_be_deleted === false) {
      throw httpError(409, {
        code: "crate.in_use", message: `Crate '${current.short_name}' is still in use and cannot be deleted.`,
        details: { id },
      });
    }
    serverCrates = serverCrates.filter((each) => each.id !== id);
  });
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
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListCrates />)}</QueryClientProvider>);
  return { user, profiler };
}

/** Renders the page and waits until the crates are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Euro crate");
  return rendered;
}

const TITLE = "commissioning.list_crates";
const ACTIVE = "commissioning.is_active";
const NUMBER = "#";
const NAME = "resellers.name";
const SHORT_NAME = "resellers.short_name";
const NOTE = "resellers.note";
const PRICES = "commissioning.prices";
const DUPLICATE_NAME = "validation.unique.name — table.save_failed_hint";

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

/** The text of each of ``titles``' cells in ``row``, by column title. */
const cellTexts = (row: HTMLElement, titles: string[]) =>
  Object.fromEntries(titles.map((title) => [title, cellOf(row, title).textContent]));

const shownNames = () => bodyRows().map((row) => cellOf(row, NAME).textContent);

/** The read-only checkbox a row shows for its active flag. */
const activeFlag = (row: HTMLElement) => within(cellOf(row, ACTIVE)).getByRole("checkbox");

const rowButton = (text: string, name: string) => within(rowOf(text)).getByRole("button", { name });
const deleteButton = (text: string) => within(rowOf(text)).queryByRole("button", { name: "table.delete" });
const addButton = () => screen.queryByRole("button", { name: /table\.add_plus_icon/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const heading = () => screen.getByRole("heading", { level: 1, name: TITLE });
const dialog = (name: string) => screen.queryByRole("dialog", { name });

type User = ReturnType<typeof userEvent.setup>;

const input = (label: string) => within(editingRow()).getByLabelText(label);
const activeCheckbox = () => within(editingRow()).getByRole("checkbox", { name: ACTIVE });

// The table puts the cursor into a row a frame after the row opens for editing
// — a new row's number, an existing row's active flag — so a test waits for it
// before typing, and no keystroke lands in another field.
const cursorIn = (field: () => HTMLElement) => waitFor(() => expect(field()).toHaveFocus());

async function startNewRow(user: User) {
  await user.click(addButton()!);
  await cursorIn(() => input(NUMBER));
}

async function editRow(user: User, name: string) {
  await user.click(rowButton(name, "table.edit"));
  await cursorIn(activeCheckbox);
}

const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function deleteRow(user: User, name: string) {
  await user.click(deleteButton(name)!);
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  await user.clear(input(label));
  await user.type(input(label), text);
}

const toggleHideInactive = (user: User) => user.click(screen.getByText("commissioning.hide_inactive"));

const createdOnce = () => waitFor(() => expect(api.createCrate).toHaveBeenCalledTimes(1));
const updatedOnce = () => waitFor(() => expect(api.updateCrate).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

const readText = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });

/** A downloaded CSV in the tenant's default format, each line as its cells by header. */
async function csvRecords(blob: Blob): Promise<{ header: string[]; records: Record<string, string>[] }> {
  const [header, ...lines] = (await readText(blob))
    .replace(/^\uFEFF/, "")
    .split("\n")
    .map((line) => line.split(";"));
  return {
    header,
    records: lines.map((cells) => Object.fromEntries(header.map((title, index) => [title, cells[index]]))),
  };
}

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListCrates loading and layout", () => {
  it("loads every crate, inactive ones included, with one unfiltered request", async () => {
    renderPage();

    expect(await screen.findByText("Euro crate")).toBeInTheDocument();
    expect(api.listCrates).toHaveBeenCalledTimes(1);
    expect(api.listCrates.mock.calls[0][0]).toBeUndefined();
  });

  it("shows a spinner over the table while the crates load", async () => {
    let deliver: (crates: Crate[]) => void = () => {};
    api.listCrates.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([HALF]);

    expect(await screen.findByText("Half crate")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(heading()).toBeVisible();
    // The price buttons' column has no title.
    expect(columnTitles()).toEqual(["table.actions", ACTIVE, NUMBER, NAME, SHORT_NAME, "", NOTE]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_crates")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when there are no crates", async () => {
    serverCrates = [];
    renderPage();

    await waitFor(() => expect(api.listCrates).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the crates fail to load", async () => {
    api.listCrates.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listCrates).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(heading()).toBeVisible();
    expect(addButton()).toBeEnabled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Rows ────────────────────────────────────────────────────────────────────

describe("ListCrates rows", () => {
  it("shows each crate's number, name, short name and note", async () => {
    await renderLoaded();

    expect(cellTexts(rowOf("Euro crate"), [NUMBER, SHORT_NAME, NOTE])).toEqual({
      [NUMBER]: "1", [SHORT_NAME]: "E1", [NOTE]: "Stackable 60 x 40 cm",
    });
    expect(cellTexts(rowOf("Banana box"), [NUMBER, SHORT_NAME, NOTE])).toEqual({
      [NUMBER]: "", [SHORT_NAME]: "BB", [NOTE]: "From the wholesaler",
    });
    expect(activeFlag(rowOf("Euro crate"))).toBeChecked();
    expect(rowButton("Half crate", PRICES)).toBeEnabled();
  });

  it("hides the crates no longer used until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(shownNames()).toEqual(["Euro crate", "Half crate", "Banana box"]);

    await toggleHideInactive(user);

    expect(shownNames()).toEqual(["Euro crate", "Half crate", "Banana box", "Wooden crate"]);
    expect(activeFlag(rowOf("Wooden crate"))).not.toBeChecked();
  });

  it("sorts the crates by name from the column header", async () => {
    const { user } = await renderLoaded();

    await user.click(within(document.querySelector<HTMLElement>(".ant-table-thead")!).getByText(NAME));

    expect(shownNames()).toEqual(["Banana box", "Euro crate", "Half crate"]);
  });
});

// ── New crate ───────────────────────────────────────────────────────────────

describe("ListCrates new crate", () => {
  it("adds an active crate with its number, name, short name and note, without reloading the list", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    expect(activeCheckbox()).toBeChecked();
    expect(within(editingRow()).getByRole("button", { name: PRICES })).toBeDisabled();
    await typeInto(user, NUMBER, "3");
    await typeInto(user, NAME, "Pallet box");
    await typeInto(user, SHORT_NAME, "PB");
    await typeInto(user, NOTE, "For potatoes");
    await saveRow(user);

    await createdOnce();
    expect(api.createCrate.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        is_active: true, number: "3", name: "Pallet box", short_name: "PB", note: "For potatoes",
      }),
    );
    // A crate has no validity of its own; its prices do.
    expect(api.createCrate.mock.calls[0][0]).not.toHaveProperty("valid_from");
    expect(stored("crate-new-1")).toEqual(
      crate({ id: "crate-new-1", number: 3, name: "Pallet box", short_name: "PB", note: "For potatoes" }),
    );
    const pallet = await waitFor(() => rowOf("Pallet box"));
    expect(cellTexts(pallet, [NUMBER, SHORT_NAME, NOTE])).toEqual({
      [NUMBER]: "3", [SHORT_NAME]: "PB", [NOTE]: "For potatoes",
    });
    expect(activeFlag(pallet)).toBeChecked();
    await user.click(within(pallet).getByRole("button", { name: PRICES }));
    expect(dialog("Prices")).toHaveTextContent("Prices of Pallet box (crate-new-1)");
    expect(api.listCrates).toHaveBeenCalledTimes(1);
  });

  it("adds a crate with a name and no short name", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NAME, "Pallet box");
    await saveRow(user);

    await createdOnce();
    expect(stored("crate-new-1")).toMatchObject({ name: "Pallet box", number: null });
    expect(await screen.findByText("Pallet box")).toBeInTheDocument();
  });

  it("refuses a new crate with a short name but no name, marking the name", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, SHORT_NAME, "PB");
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(input(NAME)).toBeInvalid();
    expect(input(SHORT_NAME)).not.toBeInvalid();
    expect(api.createCrate).not.toHaveBeenCalled();
  });

  it("refuses a new crate without a name or a short name and sends nothing", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NOTE, "For potatoes");
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(input(NOTE)).toHaveValue("For potatoes");
    expect(api.createCrate).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new crate, and keeps what was typed", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    const tooLong = "P".repeat(51);

    await startNewRow(user);
    await typeInto(user, NAME, "Pallet box");
    await typeInto(user, SHORT_NAME, tooLong);
    await saveRow(user);

    const message = "Ensure this field has no more than 50 characters.";
    expect(await screen.findByText(`${SHORT_NAME}: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(input(SHORT_NAME)).toBeInvalid();
    expect(input(NAME)).toHaveValue("Pallet box");
    expect(bodyRows()).toHaveLength(4);
    expect(api.listCrates).toHaveBeenCalledTimes(1);
  });

  it("refuses a name another crate on the list has, and takes a free one", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NAME, "Half crate");
    await typeInto(user, SHORT_NAME, "H2");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE_NAME)).toBeVisible();
    expect(input(NAME)).toBeInvalid();
    expect(api.createCrate).not.toHaveBeenCalled();

    await typeInto(user, NAME, "Half crate, deep");
    await saveRow(user);

    await createdOnce();
    expect(api.createCrate.mock.calls[0][0]).toEqual(
      expect.objectContaining({ name: "Half crate, deep", short_name: "H2" }),
    );
    expect(screen.queryByText(DUPLICATE_NAME)).not.toBeInTheDocument();
  });

  it("refuses the name of a crate no longer used, though the list hides it", async () => {
    const { user } = await renderLoaded();
    expect(screen.queryByText("Wooden crate")).not.toBeInTheDocument();

    await startNewRow(user);
    await typeInto(user, NAME, "Wooden crate");
    await typeInto(user, SHORT_NAME, "W2");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE_NAME)).toBeVisible();
    expect(api.createCrate).not.toHaveBeenCalled();
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    await cursorIn(() => input(NUMBER));
    expect(input(NAME)).toHaveValue("");
    expect(bodyRows()).toHaveLength(4);
  });
});

// ── Editing and deleting ────────────────────────────────────────────────────

describe("ListCrates editing and deleting", () => {
  it("saves a changed crate under its id without reloading the list", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Half crate");
    expect(input(NUMBER)).toHaveValue("2");
    await typeInto(user, SHORT_NAME, "E2-H");
    await typeInto(user, NOTE, "Holds 12 kg");
    await saveRow(user);

    await updatedOnce();
    expect(api.updateCrate.mock.calls[0][0]).toBe("crate-half");
    expect(api.updateCrate.mock.calls[0][1]).toEqual(
      expect.objectContaining({ is_active: true, name: "Half crate", short_name: "E2-H", note: "Holds 12 kg" }),
    );
    expect(stored("crate-half")).toEqual({ ...HALF, short_name: "E2-H", note: "Holds 12 kg" });
    expect(await screen.findByText("Holds 12 kg")).toBeInTheDocument();
    expect(cellTexts(rowOf("Half crate"), [NUMBER, SHORT_NAME])).toEqual({ [NUMBER]: "2", [SHORT_NAME]: "E2-H" });
    expect(api.listCrates).toHaveBeenCalledTimes(1);
  });

  it("clears a crate's number", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Half crate");
    await user.clear(input(NUMBER));
    await saveRow(user);

    await updatedOnce();
    expect(api.updateCrate.mock.calls[0][1]).toEqual(expect.objectContaining({ number: null }));
    expect(api.updateCrate.mock.calls[0][1]).not.toHaveProperty("valid_from");
    expect(stored("crate-half")).toEqual({ ...HALF, number: null });
    await waitFor(() => expect(cellOf(rowOf("Half crate"), NUMBER)).toHaveTextContent(""));
  });

  it("gives a crate a new number", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Banana box");
    await typeInto(user, NUMBER, "4");
    await saveRow(user);

    await updatedOnce();
    expect(stored("crate-banana")).toEqual({ ...BANANA, number: 4 });
    await waitFor(() => expect(cellOf(rowOf("Banana box"), NUMBER)).toHaveTextContent("4"));
  });

  it("retires a crate when the office unticks it as active", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Half crate");
    await user.click(activeCheckbox());
    await saveRow(user);

    await updatedOnce();
    expect(api.updateCrate).toHaveBeenCalledWith(
      "crate-half", expect.objectContaining({ name: "Half crate", is_active: false }),
    );
    expect(stored("crate-half")?.is_active).toBe(false);
  });

  it("offers no delete for a crate in use, but lets the office edit it", async () => {
    await renderLoaded();

    expect(deleteButton("Euro crate")).not.toBeInTheDocument();
    expect(rowButton("Euro crate", "table.edit")).toBeEnabled();
    expect(deleteButton("Half crate")).toBeEnabled();
  });

  it("removes a crate after confirmation and reloads the list", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "Half crate");

    await waitFor(() => expect(api.destroyCrate).toHaveBeenCalledWith("crate-half"));
    await waitFor(() => expect(api.listCrates).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Half crate")).not.toBeInTheDocument();
    expect(shownNames()).toEqual(["Euro crate", "Banana box"]);
  });

  it("shows why the server refused to delete a crate and keeps it", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    // The crate has gone into use since the list was loaded.
    serverCrates = serverCrates.map((each) => (each.id === HALF.id ? { ...each, can_be_deleted: false } : each));

    await deleteRow(user, "Half crate");

    expect(await screen.findByText(germanErrors.crate.in_use)).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(rowOf("Half crate")).toBeInTheDocument();
    expect(api.listCrates).toHaveBeenCalledTimes(1);
  });
});

// ── Prices ──────────────────────────────────────────────────────────────────

describe("ListCrates prices", () => {
  it("opens the prices of the crate whose price button is clicked", async () => {
    const { user } = await renderLoaded();
    expect(dialog("Prices")).not.toBeInTheDocument();

    await user.click(rowButton("Euro crate", PRICES));

    expect(dialog("Prices")).toHaveTextContent("Prices of Euro crate (crate-euro)");
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close prices" }));
    expect(dialog("Prices")).not.toBeInTheDocument();

    await user.click(rowButton("Banana box", PRICES));

    expect(dialog("Prices")).toHaveTextContent("Prices of Banana box (crate-banana)");
  });

  it("reloads the crates once a price is saved", async () => {
    const { user } = await renderLoaded();
    await user.click(rowButton("Euro crate", PRICES));

    await user.click(screen.getByRole("button", { name: "Save a price" }));

    await waitFor(() => expect(api.listCrates).toHaveBeenCalledTimes(2));
  });
});

// ── Exports ─────────────────────────────────────────────────────────────────

describe("ListCrates exports", () => {
  const exportButton = () => screen.getByRole("button", { name: /commissioning\.csv_export_crates/ });
  const downloadIn = (picker: HTMLElement) => within(picker).getByRole("button", { name: /common\.download/ });

  it("opens the price export in a dialog of its own", async () => {
    const { user } = await renderLoaded();
    expect(dialog("Crate price export")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /commissioning\.export_prices/ }));

    expect(dialog("Crate price export")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close price export" }));
    expect(dialog("Crate price export")).not.toBeInTheDocument();
  });

  it("exports every crate, inactive ones included, under the list's name", async () => {
    const { user } = await renderLoaded();

    await user.click(exportButton());
    const picker = await screen.findByRole("dialog", { name: "common.export_csv" });
    await user.click(downloadIn(picker));

    await waitFor(() => expect(downloads.files).toHaveLength(1));
    expect(downloads.files[0].filename).toBe(`${TITLE}.csv`);
    const { header, records } = await csvRecords(downloads.files[0].blob);
    expect(header).toEqual(expect.arrayContaining([ACTIVE, NUMBER, NAME, SHORT_NAME, NOTE]));
    expect(records.map((record) => [record[NAME], record[NUMBER], record[SHORT_NAME], record[NOTE]])).toEqual([
      ["Euro crate", "1", "E1", "Stackable 60 x 40 cm"],
      ["Half crate", "2", "E2", ""],
      ["Banana box", "", "BB", "From the wholesaler"],
      ["Wooden crate", "7", "WC", ""],
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("leaves out the columns the office unticks", async () => {
    const { user } = await renderLoaded();

    await user.click(exportButton());
    const picker = await screen.findByRole("dialog", { name: "common.export_csv" });
    await user.click(within(picker).getByRole("checkbox", { name: NOTE }));
    await user.click(within(picker).getByRole("checkbox", { name: NUMBER }));
    await user.click(downloadIn(picker));

    await waitFor(() => expect(downloads.files).toHaveLength(1));
    const { header, records } = await csvRecords(downloads.files[0].blob);
    expect(header).toEqual(expect.arrayContaining([NAME, SHORT_NAME]));
    expect(header).not.toContain(NOTE);
    expect(header).not.toContain(NUMBER);
    expect(records.map((record) => record[NAME])).toEqual(["Euro crate", "Half crate", "Banana box", "Wooden crate"]);
  });

  it("closes the column picker without a download on cancel", async () => {
    const { user } = await renderLoaded();

    await user.click(exportButton());
    const picker = await screen.findByRole("dialog", { name: "common.export_csv" });
    await user.click(within(picker).getByRole("button", { name: "common.cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(downloads.files).toHaveLength(0);
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ListCrates roles", () => {
  it.each(["office", "admin", "staff", "gardener"])("lets the %s add, edit and delete crates", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(addButton()).toBeEnabled();
    expect(rowButton("Half crate", "table.edit")).toBeEnabled();
    expect(deleteButton("Half crate")).toBeEnabled();
    expect(rowButton("Euro crate", "table.edit")).toBeEnabled();
  });

  it("shows the crates read-only to management, who may still look at a crate's prices", async () => {
    auth.roles = ["management"];
    const { user } = await renderLoaded();

    expect(addButton()).not.toBeInTheDocument();
    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

    await user.click(screen.getByText("From the wholesaler"));
    await user.keyboard("+");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();

    await user.click(rowButton("Half crate", PRICES));

    expect(dialog("Prices")).toHaveTextContent("Prices of Half crate (crate-half)");
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("ListCrates on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  function cardOf(text: string): HTMLElement {
    const card = screen.getByText(text).closest<HTMLElement>(".mobile-card-item");
    if (!card) throw new Error(`No card shows ${text}`);
    return card;
  }

  const editDialog = () => screen.getByRole("dialog", { name: "table.edit_record" });

  it("edits a crate from its card in a dialog", async () => {
    const { user } = renderPage();
    await screen.findByText("Half crate");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await user.click(within(cardOf("Half crate")).getByRole("button", { name: "table.edit" }));
    // The dialog puts the cursor into its first field a moment after it
    // opens, so a test waits for it before typing elsewhere.
    await waitFor(() =>
      expect(within(editDialog()).getByRole("checkbox", { name: ACTIVE })).toHaveFocus(),
    );
    expect(within(editDialog()).getByRole("textbox", { name: NAME })).toHaveValue("Half crate");
    await user.type(within(editDialog()).getByRole("textbox", { name: NOTE }), "Holds 12 kg");
    await user.click(within(editDialog()).getByRole("button", { name: "table.save" }));

    await updatedOnce();
    expect(api.updateCrate).toHaveBeenCalledWith(
      "crate-half", expect.objectContaining({ name: "Half crate", short_name: "E2", note: "Holds 12 kg" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(cardOf("Half crate")).toHaveTextContent("Holds 12 kg");
  });

  it("shows management cards with nothing to add or edit", async () => {
    auth.roles = ["management"];
    const { user } = renderPage();
    await user.click(await screen.findByText("Half crate"));

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(within(cardOf("Half crate")).getByRole("button", { name: "table.edit" })).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
