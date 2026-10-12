/**
 * ListStorages: the farm's storages, which the office may rename but neither
 * add nor delete here, with the two flags that mark the short- and long-term
 * harvest storage shown read-only. Rendered through the real CrudListPage and
 * EditableTable. The generated commissioning client is the mocking boundary:
 * its list hook is a real TanStack query around a spy that answers from an
 * in-memory farm, whose update checks a storage the way the backend's
 * serializer does and echoes the saved storage.
 *
 * The clock is frozen on Wednesday 7 October 2026.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Storage } from "@shared/api/generated/models";
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

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
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
  listStorages: vi.fn(), createStorage: vi.fn(), updateStorage: vi.fn(), destroyStorage: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => ["/api/commissioning/storages/", ...(params ? [params] : [])];
  return {
    useCommissioningStoragesList: function useStoragesList(params?: unknown) {
      return useQuery({ queryKey: queryKey(params), queryFn: async () => api.listStorages(params) });
    },
    getCommissioningStoragesListQueryKey: queryKey,
    commissioningStoragesCreate: (storage: unknown) => api.createStorage(storage),
    commissioningStoragesPartialUpdate: (id: string, storage: unknown) => api.updateStorage(id, storage),
    commissioningStoragesDestroy: (id: string) => api.destroyStorage(id),
  };
});

import ListStorages from "../ListStorages";

// ── Fixtures ────────────────────────────────────────────────────────────────

type Row = Record<string, unknown>;

const NOW = new Date(2026, 9, 7, 12, 0);

/** A storage as the list endpoint carries it. */
const storage = (fields: Partial<Storage> & { id: string; name: string }): Storage => ({
  is_active: true, description: null, is_short_term_harvest_storage: false,
  is_long_term_harvest_storage: false, can_be_deleted: true, ...fields,
});

const COLD_ROOM = storage({ id: "storage-cold", name: "Cold room", is_short_term_harvest_storage: true, can_be_deleted: false });
const CELLAR = storage({ id: "storage-cellar", name: "Root cellar", is_long_term_harvest_storage: true });
const BARN = storage({ id: "storage-barn", name: "Barn", description: "Dry goods" });
// No longer used; the page has no switch to hide it.
const SHED = storage({ id: "storage-shed", name: "Old shed", is_active: false });

// The fields a client can write; the serializer ignores everything else.
const WRITABLE = ["is_active", "name", "description", "is_long_term_harvest_storage", "is_short_term_harvest_storage"];

/** The writable fields a request body carries, as the JSON encoding leaves them. */
const writableFields = (payload: Row): Row =>
  Object.fromEntries(
    Object.entries(payload).filter(([field, value]) => WRITABLE.includes(field) && value !== undefined),
  );

/** What the backend's storage serializer says about ``fields``; empty when it takes them. */
function storageErrors(fields: Row): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  if ("name" in fields) {
    if (fields.name === null) errors.name = ["This field may not be null."];
    else if (String(fields.name).trim() === "") errors.name = ["This field may not be blank."];
    else if (String(fields.name).length > 100) errors.name = ["Ensure this field has no more than 100 characters."];
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

// What the server currently holds; the list requests answer from it.
let serverStorages: Storage[] = [];

const stored = (id: string) => serverStorages.find((each) => each.id === id);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  viewport.mobile = false;
  serverStorages = [COLD_ROOM, CELLAR, BARN, SHED];
  api.listStorages.mockReset().mockImplementation(async () => [...serverStorages]);
  api.createStorage.mockReset();
  api.destroyStorage.mockReset();
  api.updateStorage.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = stored(id);
    if (!current) throw httpError(404, { code: "storage.not_found", message: "Storage not found." });
    const fields = writableFields(payload);
    refuseIfInvalid(storageErrors(fields));
    const saved = { ...current, ...fields, id } as Storage;
    serverStorages = serverStorages.map((each) => (each.id === id ? saved : each));
    return saved;
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
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListStorages />)}</QueryClientProvider>);
  return { user, profiler };
}

/** Renders the page and waits until the storages are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Cold room");
  return rendered;
}

const TITLE = "commissioning.list_storages";
const NAME = "commissioning.name";
const SHORT_TERM = "commissioning.is_short_term_harvest_storage";
const LONG_TERM = "commissioning.is_long_term_storage";
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

const shownNames = () => bodyRows().map((row) => cellOf(row, NAME).textContent);
const flag = (row: HTMLElement, column: string) => within(cellOf(row, column)).getByRole("checkbox");

const rowButton = (text: string, name: string) => within(rowOf(text)).getByRole("button", { name });
const addButton = () => screen.queryByRole("button", { name: /table\.add_record/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const heading = () => screen.getByRole("heading", { level: 1, name: TITLE });

type User = ReturnType<typeof userEvent.setup>;

const nameInput = () => within(editingRow()).getByLabelText(NAME);

async function editRow(user: User, name: string) {
  await user.click(rowButton(name, "table.edit"));
  await waitFor(() => expect(nameInput()).toHaveFocus());
}

const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function typeName(user: User, text: string) {
  await user.clear(nameInput());
  if (text) await user.type(nameInput(), text);
}

const updatedOnce = () => waitFor(() => expect(api.updateStorage).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListStorages loading and layout", () => {
  it("loads every storage with one unfiltered request", async () => {
    renderPage();

    expect(await screen.findByText("Cold room")).toBeInTheDocument();
    expect(api.listStorages).toHaveBeenCalledTimes(1);
    expect(api.listStorages.mock.calls[0][0]).toBeUndefined();
  });

  it("shows a spinner over the table while the storages load", async () => {
    let deliver: (storages: Storage[]) => void = () => {};
    api.listStorages.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([BARN]);

    expect(await screen.findByText("Barn")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer, with no switch for inactive storages", async () => {
    await renderLoaded();

    expect(heading()).toBeVisible();
    expect(columnTitles()).toEqual(["table.actions", NAME, SHORT_TERM, LONG_TERM]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_storages")).toBeInTheDocument();
    expect(screen.queryByText("commissioning.hide_inactive")).not.toBeInTheDocument();
  });

  it("shows a hint instead of rows when there are no storages", async () => {
    serverStorages = [];
    renderPage();

    await waitFor(() => expect(api.listStorages).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
  });

  it("keeps the page usable when the storages fail to load", async () => {
    api.listStorages.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listStorages).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(heading()).toBeVisible();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Rows ────────────────────────────────────────────────────────────────────

describe("ListStorages rows", () => {
  it("lists inactive storages too, and marks the short- and long-term harvest storage", async () => {
    await renderLoaded();

    expect(shownNames()).toEqual(["Cold room", "Root cellar", "Barn", "Old shed"]);
    expect(flag(rowOf("Cold room"), SHORT_TERM)).toBeChecked();
    expect(flag(rowOf("Cold room"), LONG_TERM)).not.toBeChecked();
    expect(flag(rowOf("Root cellar"), SHORT_TERM)).not.toBeChecked();
    expect(flag(rowOf("Root cellar"), LONG_TERM)).toBeChecked();
    expect(flag(rowOf("Barn"), SHORT_TERM)).not.toBeChecked();
    expect(flag(rowOf("Barn"), LONG_TERM)).not.toBeChecked();
  });

  it("offers the office no way to add or delete a storage", async () => {
    const { user } = await renderLoaded();

    expect(addButton()).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    expect(rowButton("Barn", "table.edit")).toBeEnabled();

    await user.keyboard("+");

    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);
    expect(api.createStorage).not.toHaveBeenCalled();
  });
});

// ── Editing ─────────────────────────────────────────────────────────────────

describe("ListStorages editing", () => {
  it("renames a storage under its id, keeping its flags, without reloading the list", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Root cellar");
    expect(nameInput()).toHaveValue("Root cellar");
    await typeName(user, "Potato cellar");
    await saveRow(user);

    await updatedOnce();
    expect(api.updateStorage.mock.calls[0][0]).toBe("storage-cellar");
    expect(api.updateStorage.mock.calls[0][1]).toEqual(expect.objectContaining({ name: "Potato cellar" }));
    expect(stored("storage-cellar")).toEqual({ ...CELLAR, name: "Potato cellar" });
    const cellar = await waitFor(() => rowOf("Potato cellar"));
    expect(flag(cellar, LONG_TERM)).toBeChecked();
    expect(api.listStorages).toHaveBeenCalledTimes(1);
  });

  it("keeps the harvest-storage flags out of the office's reach while a row is edited", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Cold room");

    const row = editingRow();
    for (const checkbox of within(row).getAllByRole("checkbox")) {
      expect(checkbox).toBeDisabled();
    }
    await saveRow(user);

    await updatedOnce();
    expect(api.updateStorage.mock.calls[0][1]).toEqual(
      expect.objectContaining({ name: "Cold room", is_short_term_harvest_storage: true }),
    );
    expect(stored("storage-cold")).toEqual(COLD_ROOM);
  });

  it("refuses an empty name and sends nothing", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await editRow(user, "Barn");
    await typeName(user, "");
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(api.updateStorage).not.toHaveBeenCalled();
    expect(stored("storage-barn")).toEqual(BARN);
  });

  it("refuses a name another storage has, inactive ones included, and takes a free one", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Barn");
    await typeName(user, "Old shed");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE_NAME)).toBeVisible();
    expect(nameInput()).toBeInvalid();
    expect(api.updateStorage).not.toHaveBeenCalled();

    await typeName(user, "Hay barn");
    await saveRow(user);

    await updatedOnce();
    expect(api.updateStorage).toHaveBeenCalledWith("storage-barn", expect.objectContaining({ name: "Hay barn" }));
    expect(screen.queryByText(DUPLICATE_NAME)).not.toBeInTheDocument();
  });

  it("saves a storage under its own unchanged name", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Barn");
    await saveRow(user);

    await updatedOnce();
    expect(api.updateStorage).toHaveBeenCalledWith("storage-barn", expect.objectContaining({ name: "Barn" }));
  });

  it("shows the server's reason when it refuses a name, and keeps what was typed", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    const tooLong = "S".repeat(101);

    await editRow(user, "Barn");
    await user.clear(nameInput());
    await user.paste(tooLong);
    await saveRow(user);

    const message = "Ensure this field has no more than 100 characters.";
    expect(await screen.findByText(`${NAME}: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(nameInput()).toHaveValue(tooLong);
    expect(stored("storage-barn")).toEqual(BARN);
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ListStorages roles", () => {
  it.each(["office", "admin"])("lets the %s rename storages", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(rowButton("Barn", "table.edit")).toBeEnabled();
    expect(addButton()).not.toBeInTheDocument();
  });

  it.each(["staff", "gardener", "management"])("shows the storages read-only to %s", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();
    expect(shownNames()).toEqual(["Cold room", "Root cellar", "Barn", "Old shed"]);
  });
});
