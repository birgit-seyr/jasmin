/**
 * ListPlots: the farm's plots — a name and whether the plot is still farmed —
 * edited inline by the office. Rendered through the real CrudListPage,
 * EditableTable and active column hook. The generated commissioning client is
 * the mocking boundary: its list hook is a real TanStack query around a spy
 * that answers from an in-memory farm, whose mutations check a plot the way
 * the backend's serializer does and echo the saved plot.
 *
 * The clock is frozen on Wednesday 7 October 2026.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Plot } from "@shared/api/generated/models";
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
  listPlots: vi.fn(), createPlot: vi.fn(), updatePlot: vi.fn(), destroyPlot: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => ["/api/commissioning/plots/", ...(params ? [params] : [])];
  return {
    useCommissioningPlotsList: function usePlotsList(params?: unknown) {
      return useQuery({ queryKey: queryKey(params), queryFn: async () => api.listPlots(params) });
    },
    getCommissioningPlotsListQueryKey: queryKey,
    commissioningPlotsCreate: (plot: unknown) => api.createPlot(plot),
    commissioningPlotsPartialUpdate: (id: string, plot: unknown) => api.updatePlot(id, plot),
    // The generated destroy takes the id alone, whatever else the caller hands it.
    commissioningPlotsDestroy: (id: string) => api.destroyPlot(id),
  };
});

import ListPlots from "../ListPlots";

// ── Fixtures ────────────────────────────────────────────────────────────────

type Row = Record<string, unknown>;

const NOW = new Date(2026, 9, 7, 12, 0);

/** A plot as the list endpoint carries it. */
const plot = (fields: Partial<Plot> & { id: string; name: string }): Plot => ({
  is_active: true, can_be_deleted: true, ...fields,
});

// Forecasts are planned on it, so the backend protects it.
const NORTH = plot({ id: "plot-north", name: "North field", can_be_deleted: false });
const GREENHOUSE = plot({ id: "plot-greenhouse", name: "Greenhouse 1" });
// No longer farmed.
const ORCHARD = plot({ id: "plot-orchard", name: "Old orchard", is_active: false });

// The fields a client can write; the serializer ignores everything else.
const WRITABLE = ["is_active", "name"];

/** The writable fields a request body carries, as the JSON encoding leaves them. */
const writableFields = (payload: Row): Row =>
  Object.fromEntries(
    Object.entries(payload).filter(([field, value]) => WRITABLE.includes(field) && value !== undefined),
  );

/** What the backend's plot serializer says about ``fields``; empty when it takes them. */
function plotErrors(fields: Row, creating: boolean): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  if (!("name" in fields)) {
    if (creating) errors.name = ["This field is required."];
  } else if (fields.name === null) {
    errors.name = ["This field may not be null."];
  } else if (String(fields.name).trim() === "") {
    errors.name = ["This field may not be blank."];
  } else if (String(fields.name).length > 255) {
    errors.name = ["Ensure this field has no more than 255 characters."];
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
let serverPlots: Plot[] = [];

const stored = (id: string) => serverPlots.find((each) => each.id === id);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  viewport.mobile = false;
  serverPlots = [NORTH, GREENHOUSE, ORCHARD];
  let createdCount = 0;
  api.listPlots.mockReset().mockImplementation(async () => [...serverPlots]);
  api.createPlot.mockReset().mockImplementation(async (payload: Row) => {
    const fields = writableFields(payload);
    refuseIfInvalid(plotErrors(fields, true));
    createdCount += 1;
    const saved = plot({ ...fields, id: `plot-new-${createdCount}` } as Plot & { id: string; name: string });
    serverPlots = [...serverPlots, saved];
    return saved;
  });
  api.updatePlot.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = stored(id);
    if (!current) throw httpError(404, { code: "not_found", message: "Not found." });
    const fields = writableFields(payload);
    refuseIfInvalid(plotErrors(fields, false));
    const saved = { ...current, ...fields, id } as Plot;
    serverPlots = serverPlots.map((each) => (each.id === id ? saved : each));
    return saved;
  });
  api.destroyPlot.mockReset().mockImplementation(async (id: string) => {
    const current = stored(id);
    if (current?.can_be_deleted === false) {
      throw httpError(409, {
        code: "plot.in_use", message: `Plot '${current.name}' is still in use and cannot be deleted.`,
        details: { id },
      });
    }
    serverPlots = serverPlots.filter((each) => each.id !== id);
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
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListPlots />)}</QueryClientProvider>);
  return { user, profiler };
}

/** Renders the page and waits until the plots are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("North field");
  return rendered;
}

const TITLE = "commissioning.list_plots";
const ACTIVE = "commissioning.is_active";
const NAME = "resellers.name";
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

/** The read-only checkbox a row shows for its active flag. */
const activeFlag = (row: HTMLElement) => within(cellOf(row, ACTIVE)).getByRole("checkbox");

const rowButton = (text: string, name: string) => within(rowOf(text)).getByRole("button", { name });
const deleteButton = (text: string) => within(rowOf(text)).queryByRole("button", { name: "table.delete" });
const addButton = () => screen.queryByRole("button", { name: /table\.add_plus_icon/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const heading = () => screen.getByRole("heading", { level: 1, name: TITLE });

type User = ReturnType<typeof userEvent.setup>;

const nameInput = () => within(editingRow()).getByLabelText(NAME);
const activeCheckbox = () => within(editingRow()).getByRole("checkbox", { name: ACTIVE });

// The table puts the cursor into a row a frame after the row opens for
// editing, so a test waits for it before typing, and no keystroke lands in
// another field.
const cursorIn = (field: () => HTMLElement) => waitFor(() => expect(field()).toHaveFocus());

async function startNewRow(user: User) {
  await user.click(addButton()!);
  await cursorIn(nameInput);
}

async function editRow(user: User, name: string) {
  await user.click(rowButton(name, "table.edit"));
  await waitFor(() => expect(editingRow()).toBeInTheDocument());
  await waitFor(() => expect(editingRow().contains(document.activeElement)).toBe(true));
}

const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function deleteRow(user: User, name: string) {
  await user.click(deleteButton(name)!);
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeName(user: User, text: string) {
  await user.clear(nameInput());
  if (text) await user.type(nameInput(), text);
}

const toggleHideInactive = (user: User) => user.click(screen.getByText("commissioning.hide_inactive"));

const createdOnce = () => waitFor(() => expect(api.createPlot).toHaveBeenCalledTimes(1));
const updatedOnce = () => waitFor(() => expect(api.updatePlot).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListPlots loading and layout", () => {
  it("loads every plot, inactive ones included, with one unfiltered request", async () => {
    renderPage();

    expect(await screen.findByText("North field")).toBeInTheDocument();
    expect(api.listPlots).toHaveBeenCalledTimes(1);
    expect(api.listPlots.mock.calls[0][0]).toBeUndefined();
  });

  it("shows a spinner over the table while the plots load", async () => {
    let deliver: (plots: Plot[]) => void = () => {};
    api.listPlots.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([GREENHOUSE]);

    expect(await screen.findByText("Greenhouse 1")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the description, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(heading()).toBeVisible();
    expect(screen.getByRole("heading", { level: 5, name: "commissioning.plots_description" })).toBeVisible();
    expect(columnTitles()).toEqual(["table.actions", ACTIVE, NAME]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_plots")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when there are no plots", async () => {
    serverPlots = [];
    renderPage();

    await waitFor(() => expect(api.listPlots).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the plots fail to load", async () => {
    api.listPlots.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listPlots).toHaveBeenCalled());
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

describe("ListPlots rows", () => {
  it("hides the plots no longer farmed until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(shownNames()).toEqual(["North field", "Greenhouse 1"]);
    expect(activeFlag(rowOf("North field"))).toBeChecked();

    await toggleHideInactive(user);

    expect(shownNames()).toEqual(["North field", "Greenhouse 1", "Old orchard"]);
    expect(activeFlag(rowOf("Old orchard"))).not.toBeChecked();
  });
});

// ── New plot ────────────────────────────────────────────────────────────────

describe("ListPlots new plot", () => {
  it("adds an active plot under its name without reloading the list", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    expect(activeCheckbox()).toBeChecked();
    await typeName(user, "South field");
    await saveRow(user);

    await createdOnce();
    expect(api.createPlot.mock.calls[0][0]).toEqual(expect.objectContaining({ is_active: true, name: "South field" }));
    expect(stored("plot-new-1")).toEqual(plot({ id: "plot-new-1", name: "South field" }));
    await waitFor(() => expect(activeFlag(rowOf("South field"))).toBeChecked());
    expect(api.listPlots).toHaveBeenCalledTimes(1);
  });

  it("adds a plot that is not farmed yet", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeName(user, "Fallow strip");
    await user.click(activeCheckbox());
    await saveRow(user);

    await createdOnce();
    expect(api.createPlot.mock.calls[0][0]).toEqual(expect.objectContaining({ is_active: false, name: "Fallow strip" }));
    expect(stored("plot-new-1")?.is_active).toBe(false);
  });

  it("refuses a new plot without a name and sends nothing", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await startNewRow(user);
    await saveRow(user);

    await flushMicrotasks();
    expect(nameInput()).toBeInvalid();
    expect(api.createPlot).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new plot, and keeps what was typed", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    const tooLong = "P".repeat(256);

    await startNewRow(user);
    await user.click(nameInput());
    await user.paste(tooLong);
    await saveRow(user);

    const message = "Ensure this field has no more than 255 characters.";
    expect(await screen.findByText(`${NAME}: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(nameInput()).toHaveValue(tooLong);
    expect(bodyRows()).toHaveLength(3);
    expect(api.listPlots).toHaveBeenCalledTimes(1);
  });

  it("refuses a name another plot on the list has, inactive ones included, and takes a free one", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeName(user, "Old orchard");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE_NAME)).toBeVisible();
    expect(nameInput()).toBeInvalid();
    expect(api.createPlot).not.toHaveBeenCalled();

    await typeName(user, "New orchard");
    await saveRow(user);

    await createdOnce();
    expect(api.createPlot.mock.calls[0][0]).toEqual(expect.objectContaining({ name: "New orchard" }));
    expect(screen.queryByText(DUPLICATE_NAME)).not.toBeInTheDocument();
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    await cursorIn(nameInput);
    expect(nameInput()).toHaveValue("");
    expect(bodyRows()).toHaveLength(3);
  });
});

// ── Editing and deleting ────────────────────────────────────────────────────

describe("ListPlots editing and deleting", () => {
  it("renames a plot under its id without reloading the list", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Greenhouse 1");
    expect(nameInput()).toHaveValue("Greenhouse 1");
    await typeName(user, "Greenhouse A");
    await saveRow(user);

    await updatedOnce();
    expect(api.updatePlot.mock.calls[0][0]).toBe("plot-greenhouse");
    expect(api.updatePlot.mock.calls[0][1]).toEqual(
      expect.objectContaining({ is_active: true, name: "Greenhouse A" }),
    );
    expect(stored("plot-greenhouse")).toEqual({ ...GREENHOUSE, name: "Greenhouse A" });
    expect(await screen.findByText("Greenhouse A")).toBeInTheDocument();
    expect(api.listPlots).toHaveBeenCalledTimes(1);
  });

  it("keeps a plot's own name when it is saved unchanged", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Greenhouse 1");
    await saveRow(user);

    await updatedOnce();
    expect(api.updatePlot).toHaveBeenCalledWith("plot-greenhouse", expect.objectContaining({ name: "Greenhouse 1" }));
    expect(screen.queryByText(DUPLICATE_NAME)).not.toBeInTheDocument();
  });

  it("retires a plot when the office unticks it as active", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Greenhouse 1");
    await user.click(activeCheckbox());
    await saveRow(user);

    await updatedOnce();
    expect(api.updatePlot).toHaveBeenCalledWith(
      "plot-greenhouse", expect.objectContaining({ name: "Greenhouse 1", is_active: false }),
    );
    expect(stored("plot-greenhouse")?.is_active).toBe(false);
  });

  it("offers no delete for a plot in use, but lets the office edit it", async () => {
    await renderLoaded();

    expect(deleteButton("North field")).not.toBeInTheDocument();
    expect(rowButton("North field", "table.edit")).toBeEnabled();
    expect(deleteButton("Greenhouse 1")).toBeEnabled();
  });

  it("removes a plot after confirmation and reloads the list", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "Greenhouse 1");

    await waitFor(() => expect(api.destroyPlot).toHaveBeenCalledWith("plot-greenhouse"));
    await waitFor(() => expect(api.listPlots).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Greenhouse 1")).not.toBeInTheDocument();
    expect(shownNames()).toEqual(["North field"]);
  });

  it("shows why the server refused to delete a plot and keeps it", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    // A forecast has been planned on the plot since the list was loaded.
    serverPlots = serverPlots.map((each) => (each.id === GREENHOUSE.id ? { ...each, can_be_deleted: false } : each));

    await deleteRow(user, "Greenhouse 1");

    expect(await screen.findByText(germanErrors.plot.in_use)).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(rowOf("Greenhouse 1")).toBeInTheDocument();
    expect(api.listPlots).toHaveBeenCalledTimes(1);
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ListPlots roles", () => {
  it.each(["office", "admin"])("lets the %s add, edit and delete plots", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(addButton()).toBeEnabled();
    expect(rowButton("Greenhouse 1", "table.edit")).toBeEnabled();
    expect(deleteButton("Greenhouse 1")).toBeEnabled();
  });

  it.each(["staff", "gardener", "management"])("shows the plots read-only to %s, as only the office may write them", async (role) => {
    auth.roles = [role];
    const { user } = await renderLoaded();

    expect(addButton()).not.toBeInTheDocument();
    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

    await user.click(screen.getByText("Greenhouse 1"));
    await user.keyboard("+");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(api.createPlot).not.toHaveBeenCalled();
  });
});
