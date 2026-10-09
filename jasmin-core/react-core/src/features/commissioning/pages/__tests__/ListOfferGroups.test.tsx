/**
 * ListOfferGroups: the groups the farm sorts its resellers into for offers —
 * number, name and, per price tier beyond the first, the discount the group
 * gets — edited inline. Rendered through the real CrudListPage and
 * EditableTable; the generated commissioning client is the mocking boundary: its list hook is a real TanStack query around a spy that answers
 * from an in-memory farm, whose mutations check a group the way the backend's
 * serializer does and echo the saved group.
 *
 * The clock is frozen on Wednesday 7 October 2026, since a save stamps today.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OfferGroup } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// One ``t`` for every call, as the real hook keeps it stable across renders.
// A tier column's title carries its threshold, so the columns stay apart.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => {
    if (typeof fallback === "string") return fallback;
    if (fallback && typeof fallback === "object" && "tier" in fallback) {
      return `${key} ${(fallback as { tier: unknown }).tier}`;
    }
    return key;
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

const api = vi.hoisted(() => ({
  listGroups: vi.fn(), createGroup: vi.fn(), updateGroup: vi.fn(), destroyGroup: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => ["/api/commissioning/offer_groups/", ...(params ? [params] : [])];
  return {
    useCommissioningOfferGroupsList: function useOfferGroupsList(params?: unknown) {
      return useQuery({ queryKey: queryKey(params), queryFn: async () => api.listGroups(params) });
    },
    getCommissioningOfferGroupsListQueryKey: queryKey,
    commissioningOfferGroupsCreate: (group: unknown) => api.createGroup(group),
    commissioningOfferGroupsPartialUpdate: (id: string, group: unknown) => api.updateGroup(id, group),
    // The generated destroy takes the id alone, whatever else the caller hands it.
    commissioningOfferGroupsDestroy: (id: string) => api.destroyGroup(id),
  };
});

import ListOfferGroups from "../ListOfferGroups";

// ── Fixtures ────────────────────────────────────────────────────────────────

type Row = Record<string, unknown>;

const NOW = new Date(2026, 9, 7, 12, 0);
const TODAY = "2026-10-07";

/** An offer group as the list endpoint carries it. */
const group = (fields: Partial<OfferGroup> & { id: string; number: number }): OfferGroup => ({
  name: null, note: null, rabatt_price_tier_2: null, rabatt_price_tier_3: null,
  is_default: false, can_be_deleted: true, reseller_names: "", ...fields,
});

// The seeded default group; the backend never lets it go.
const STANDARD = group({ id: "og-standard", number: 1, name: "Standard", is_default: true, can_be_deleted: false });
const GASTRO = group({
  id: "og-gastro", number: 2, name: "Gastro", rabatt_price_tier_2: 5, rabatt_price_tier_3: 10,
  reseller_names: "Hofcafé",
});
// Without a name of its own, and a discount on the second tier only.
const UNNAMED = group({ id: "og-unnamed", number: 4, rabatt_price_tier_2: 3 });
// Numbered well apart from the others.
const MARKET = group({ id: "og-market", number: 9, name: "Wochenmarkt 2024" });

// The fields a client can write; the serializer ignores everything else.
const WRITABLE = ["number", "name", "note", "rabatt_price_tier_2", "rabatt_price_tier_3"];

/** The writable fields a request body carries, as the JSON encoding leaves them. */
const writableFields = (payload: Row): Row =>
  Object.fromEntries(
    Object.entries(payload).filter(([field, value]) => WRITABLE.includes(field) && value !== undefined),
  );

const isWholeNumber = (value: unknown) => /^\d+$/.test(String(value));

/** What the backend's offer group serializer says about ``fields``; empty when it takes them. */
function groupErrors(fields: Row, creating: boolean, id?: string): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  if (!("number" in fields)) {
    if (creating) errors.number = ["This field is required."];
  } else if (fields.number === null || fields.number === "") {
    errors.number = ["This field may not be null."];
  } else if (!isWholeNumber(fields.number)) {
    errors.number = ["A valid integer is required."];
  } else if (serverGroups.some((each) => each.id !== id && each.number === Number(fields.number))) {
    errors.number = ["offer group with this number already exists."];
  }
  for (const tier of ["rabatt_price_tier_2", "rabatt_price_tier_3"]) {
    const value = fields[tier];
    if (value === undefined || value === null || value === "") continue;
    if (!isWholeNumber(value)) errors[tier] = ["A valid integer is required."];
    else if (Number(value) > 100) errors[tier] = ["Ensure this value is less than or equal to 100."];
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

/** The fields as the server stores them: numbers are integers, an empty discount none. */
const storedFields = (fields: Row): Row =>
  Object.fromEntries(
    Object.entries(fields).map(([field, value]) =>
      ["number", "rabatt_price_tier_2", "rabatt_price_tier_3"].includes(field)
        ? [field, value === null || value === "" ? null : Number(value)]
        : [field, value],
    ),
  );

// What the server currently holds; the list requests answer from it.
let serverGroups: OfferGroup[] = [];

const stored = (id: string) => serverGroups.find((each) => each.id === id);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  tenantSettings.values = { used_tiers_for_offers: [1, 3, 5] };
  serverGroups = [STANDARD, GASTRO, UNNAMED, MARKET];
  let createdCount = 0;
  api.listGroups.mockReset().mockImplementation(async () => [...serverGroups]);
  api.createGroup.mockReset().mockImplementation(async (payload: Row) => {
    const fields = writableFields(payload);
    refuseIfInvalid(groupErrors(fields, true));
    createdCount += 1;
    const saved = group({ ...storedFields(fields), id: `og-new-${createdCount}` } as OfferGroup & {
      id: string; number: number;
    });
    serverGroups = [...serverGroups, saved];
    return saved;
  });
  api.updateGroup.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = stored(id);
    if (!current) throw httpError(404, { code: "offer_group.not_found", message: "Not found." });
    const fields = writableFields(payload);
    refuseIfInvalid(groupErrors(fields, false, id));
    const saved = { ...current, ...storedFields(fields), id } as OfferGroup;
    serverGroups = serverGroups.map((each) => (each.id === id ? saved : each));
    return saved;
  });
  api.destroyGroup.mockReset().mockImplementation(async (id: string) => {
    const current = stored(id);
    if (current?.is_default) {
      throw httpError(409, {
        code: "offer_group.cannot_delete_default", message: "The default offer group cannot be deleted.",
      });
    }
    if (current?.can_be_deleted === false) {
      throw httpError(409, {
        code: "protected_error", message: "Offer group 'Gastro' still has offers and cannot be deleted.",
      });
    }
    serverGroups = serverGroups.filter((each) => each.id !== id);
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
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListOfferGroups />)}</QueryClientProvider>);
  return { user, profiler };
}

/** Renders the page and waits until the groups are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Gastro");
  return rendered;
}

const TITLE = "commissioning.list_offer_groups";
const NUMBER = "#";
const NAME = "resellers.name";
const TIER_3 = "commissioning.rabatt_price_tier 3";
const TIER_5 = "commissioning.rabatt_price_tier 5";
const DUPLICATE_NUMBER = "validation.unique.number — table.save_failed_hint";

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
/** The row of the group numbered ``number``. */
const rowNumbered = (number: number) => {
  const found = bodyRows().find((row) => cellOf(row, NUMBER).textContent === String(number));
  if (!found) throw new Error(`No row numbered ${number}`);
  return found;
};
/** The row being edited inline — the one offering a save button. */
const editingRow = () => rowAround(screen.getByRole("button", { name: "table.save" }), "is being edited");

function cellOf(row: HTMLElement, columnTitle: string): HTMLElement {
  const index = columnTitles().indexOf(columnTitle);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${columnTitle}`);
  return cell;
}

const cellTexts = (row: HTMLElement, titles: string[]) =>
  Object.fromEntries(titles.map((title) => [title, cellOf(row, title).textContent]));

const shownNumbers = () => bodyRows().map((row) => cellOf(row, NUMBER).textContent);

const rowButton = (row: HTMLElement, name: string) => within(row).queryByRole("button", { name });
const addButton = () => screen.queryByRole("button", { name: /table\.add_plus_icon/ });
const spinner = () => document.querySelector(".ant-spin-spinning");
const heading = () => screen.getByRole("heading", { level: 1, name: TITLE });

type User = ReturnType<typeof userEvent.setup>;

const input = (label: string) => within(editingRow()).getByLabelText(label);

// The table puts the cursor into a row a frame after the row opens for
// editing, so a test waits for it before typing.
const cursorIn = (field: () => HTMLElement) => waitFor(() => expect(field()).toHaveFocus());

async function startNewRow(user: User) {
  await user.click(addButton()!);
  await cursorIn(() => input(NUMBER));
}

async function editRow(user: User, row: HTMLElement) {
  await user.click(rowButton(row, "table.edit")!);
  await cursorIn(() => input(NUMBER));
}

const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function deleteRow(user: User, row: HTMLElement) {
  await user.click(rowButton(row, "table.delete")!);
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  await user.clear(input(label));
  await user.type(input(label), text);
}

const createdOnce = () => waitFor(() => expect(api.createGroup).toHaveBeenCalledTimes(1));
const updatedOnce = () => waitFor(() => expect(api.updateGroup).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListOfferGroups loading and layout", () => {
  it("loads every group with one unfiltered request", async () => {
    renderPage();

    expect(await screen.findByText("Gastro")).toBeInTheDocument();
    expect(api.listGroups).toHaveBeenCalledTimes(1);
    expect(api.listGroups.mock.calls[0][0]).toBeUndefined();
  });

  it("shows a spinner over the table while the groups load", async () => {
    let deliver: (groups: OfferGroup[]) => void = () => {};
    api.listGroups.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([GASTRO]);

    expect(await screen.findByText("Gastro")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, a discount column for the second and third tier, and the explainer", async () => {
    await renderLoaded();

    expect(heading()).toBeVisible();
    expect(columnTitles()).toEqual(["table.actions", NUMBER, NAME, TIER_3, TIER_5]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_offer_groups")).toBeInTheDocument();
  });

  it("shows no discount column when the tenant sells at a single tier", async () => {
    tenantSettings.values = {};
    await renderLoaded();

    expect(columnTitles()).toEqual(["table.actions", NUMBER, NAME]);
  });

  it("caps the discount columns at the third tier, which is as far as a group stores them", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 2, 10, 50] };
    await renderLoaded();

    expect(columnTitles()).toEqual([
      "table.actions", NUMBER, NAME,
      "commissioning.rabatt_price_tier 2", "commissioning.rabatt_price_tier 10",
    ]);
  });

  it("shows a hint instead of rows when there are no groups", async () => {
    serverGroups = [];
    renderPage();

    await waitFor(() => expect(api.listGroups).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the groups fail to load", async () => {
    api.listGroups.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listGroups).toHaveBeenCalled());
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

describe("ListOfferGroups rows", () => {
  it("shows each group's number, name and discounts", async () => {
    await renderLoaded();

    expect(cellTexts(rowOf("Gastro"), [NUMBER, TIER_3, TIER_5])).toEqual({
      [NUMBER]: "2", [TIER_3]: "5 %", [TIER_5]: "10 %",
    });
    expect(cellTexts(rowNumbered(4), [NAME, TIER_3, TIER_5])).toEqual({
      [NAME]: "", [TIER_3]: "3 %", [TIER_5]: "",
    });
  });

  it("marks the default group with a lock and offers no delete for it", async () => {
    await renderLoaded();

    const standard = rowOf("Standard");
    expect(within(cellOf(standard, NAME)).getByRole("img", { name: "lock" })).toBeInTheDocument();
    expect(cellOf(rowOf("Gastro"), NAME).querySelector(".anticon-lock")).toBeNull();
    expect(rowButton(standard, "table.delete")).not.toBeInTheDocument();
    expect(rowButton(standard, "table.edit")).toBeEnabled();
    expect(rowButton(rowOf("Gastro"), "table.delete")).toBeEnabled();
  });

  it("shows every group, with no switch to hide any", async () => {
    await renderLoaded();

    expect(shownNumbers()).toEqual(["1", "2", "4", "9"]);
    expect(screen.queryByText("commissioning.hide_inactive")).not.toBeInTheDocument();
  });
});

// ── New group ───────────────────────────────────────────────────────────────

describe("ListOfferGroups new group", () => {
  it("adds a group with its number, name and discounts, stamped with today", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NUMBER, "3");
    await typeInto(user, NAME, "Kantinen");
    await typeInto(user, TIER_3, "4");
    await typeInto(user, TIER_5, "8");
    await saveRow(user);

    await createdOnce();
    expect(api.createGroup.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        number: "3", name: "Kantinen",
        rabatt_price_tier_2: "4", rabatt_price_tier_3: "8", valid_from: TODAY,
      }),
    );
    expect(api.createGroup.mock.calls[0][0]).not.toHaveProperty("is_active");
    expect(stored("og-new-1")).toEqual(
      group({ id: "og-new-1", number: 3, name: "Kantinen", rabatt_price_tier_2: 4, rabatt_price_tier_3: 8 }),
    );
    const kantinen = await waitFor(() => rowOf("Kantinen"));
    expect(cellTexts(kantinen, [NUMBER, TIER_3, TIER_5])).toEqual({
      [NUMBER]: "3", [TIER_3]: "4 %", [TIER_5]: "8 %",
    });
    expect(api.listGroups).toHaveBeenCalledTimes(1);
  });

  it("adds a group with a number alone", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NUMBER, "5");
    await saveRow(user);

    await createdOnce();
    expect(stored("og-new-1")).toEqual(group({ id: "og-new-1", number: 5 }));
  });

  it("refuses a new group without a number and sends nothing", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NAME, "Kantinen");
    await saveRow(user);

    expect(await screen.findByText(/table\.save_failed_hint/)).toBeVisible();
    expect(input(NAME)).toHaveValue("Kantinen");
    expect(api.createGroup).not.toHaveBeenCalled();
  });

  it("refuses a number another group has and takes a free one", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NUMBER, "9");
    await typeInto(user, NAME, "Kantinen");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE_NUMBER)).toBeVisible();
    expect(input(NUMBER)).toBeInvalid();
    expect(api.createGroup).not.toHaveBeenCalled();

    await typeInto(user, NUMBER, "6");
    await saveRow(user);

    await createdOnce();
    expect(api.createGroup.mock.calls[0][0]).toEqual(expect.objectContaining({ number: "6", name: "Kantinen" }));
    expect(screen.queryByText(DUPLICATE_NUMBER)).not.toBeInTheDocument();
  });

  it("shows the server's reason when it refuses a discount, and keeps what was typed", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NUMBER, "3");
    await typeInto(user, TIER_3, "150");
    await saveRow(user);

    expect(
      await screen.findByText(`${TIER_3}: Ensure this value is less than or equal to 100. — table.save_failed_hint`),
    ).toBeVisible();
    expect(input(NUMBER)).toHaveValue("3");
    expect(serverGroups).toHaveLength(4);
  });
});

// ── Editing and deleting ────────────────────────────────────────────────────

describe("ListOfferGroups editing and deleting", () => {
  it("saves a changed discount under the group's id without reloading the list", async () => {
    const { user } = await renderLoaded();

    await editRow(user, rowOf("Gastro"));
    expect(input(TIER_3)).toHaveValue("5");
    await typeInto(user, TIER_3, "7");
    await saveRow(user);

    await updatedOnce();
    expect(api.updateGroup.mock.calls[0][0]).toBe("og-gastro");
    expect(api.updateGroup.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        number: "2", name: "Gastro",
        rabatt_price_tier_2: "7", rabatt_price_tier_3: "10", valid_from: TODAY,
      }),
    );
    expect(api.updateGroup.mock.calls[0][1]).not.toHaveProperty("is_active");
    expect(stored("og-gastro")).toEqual({ ...GASTRO, rabatt_price_tier_2: 7 });
    await waitFor(() => expect(cellOf(rowOf("Gastro"), TIER_3)).toHaveTextContent("7 %"));
    expect(api.listGroups).toHaveBeenCalledTimes(1);
  });

  it("lets the office rename and renumber the default group", async () => {
    const { user } = await renderLoaded();

    await editRow(user, rowOf("Standard"));
    await typeInto(user, NUMBER, "10");
    await typeInto(user, NAME, "Alle");
    await saveRow(user);

    await updatedOnce();
    expect(stored("og-standard")).toEqual({ ...STANDARD, number: 10, name: "Alle" });
    expect(within(cellOf(await waitFor(() => rowOf("Alle")), NAME)).getByRole("img", { name: "lock" }))
      .toBeInTheDocument();
  });

  it("refuses renumbering a group to another group's number", async () => {
    const { user } = await renderLoaded();

    await editRow(user, rowOf("Gastro"));
    await typeInto(user, NUMBER, "4");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE_NUMBER)).toBeVisible();
    expect(api.updateGroup).not.toHaveBeenCalled();
  });

  it("removes a group after confirmation and reloads the list", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, rowNumbered(4));

    await waitFor(() => expect(api.destroyGroup).toHaveBeenCalledWith("og-unnamed"));
    await waitFor(() => expect(api.listGroups).toHaveBeenCalledTimes(2));
    expect(shownNumbers()).toEqual(["1", "2", "9"]);
  });

  it("shows why the server refused to delete a group and keeps it", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();
    // Offers have been made for the group since the list was loaded.
    serverGroups = serverGroups.map((each) => (each.id === GASTRO.id ? { ...each, can_be_deleted: false } : each));

    await deleteRow(user, rowOf("Gastro"));

    expect(await screen.findByText("Offer group 'Gastro' still has offers and cannot be deleted.")).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(rowOf("Gastro")).toBeInTheDocument();
    expect(api.listGroups).toHaveBeenCalledTimes(1);
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ListOfferGroups roles", () => {
  it.each(["office", "admin"])("lets the %s add, edit and delete groups", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(addButton()).toBeEnabled();
    expect(rowButton(rowOf("Gastro"), "table.edit")).toBeEnabled();
    expect(rowButton(rowOf("Gastro"), "table.delete")).toBeEnabled();
  });

  it.each(["staff", "gardener", "management"])("shows the groups read-only to %s", async (role) => {
    auth.roles = [role];
    const { user } = await renderLoaded();

    expect(addButton()).not.toBeInTheDocument();
    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

    await user.click(screen.getByText("Gastro"));
    await user.keyboard("+");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });
});
