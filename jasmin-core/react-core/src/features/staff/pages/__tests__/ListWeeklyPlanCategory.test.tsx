// The weekly-plan categories list renders through the real CrudListPage and
// EditableTable; only the generated staff client is replaced (the list hook by
// a real TanStack query around a spy).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  StaffWeeklyPlanCategoriesListParams,
  WeeklyPlanCategory,
} from "@shared/api/generated/models";
import deErrors from "@shared/i18n/locales/de/errors.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The signed-in user's roles; `useRoles` derives the office gate from them.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", roles: auth.roles } }),
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const staffApi = vi.hoisted(() => ({
  listCategories: vi.fn(),
  createCategory: vi.fn(),
  updateCategory: vi.fn(),
  deleteCategory: vi.fn(),
}));

vi.mock("@shared/api/generated/staff/staff", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@shared/api/generated/staff/staff")>();
  const { useQuery } = await import("@tanstack/react-query");
  return {
    ...actual,
    useStaffWeeklyPlanCategoriesList: (
      params?: StaffWeeklyPlanCategoriesListParams,
    ) =>
      useQuery({
        queryKey: actual.getStaffWeeklyPlanCategoriesListQueryKey(params),
        queryFn: (): Promise<WeeklyPlanCategory[]> =>
          staffApi.listCategories(params),
      }),
    staffWeeklyPlanCategoriesCreate: (category: WeeklyPlanCategory) =>
      staffApi.createCategory(category),
    staffWeeklyPlanCategoriesPartialUpdate: (
      id: string,
      category: WeeklyPlanCategory,
    ) => staffApi.updateCategory(id, category),
    staffWeeklyPlanCategoriesDestroy: (id: string) =>
      staffApi.deleteCategory(id),
  };
});

import ListWeeklyPlanCategory from "../ListWeeklyPlanCategory";

// ── Fixtures ────────────────────────────────────────────────────────────────

// The weekly plan has cells in Harvest, so the backend marks it as in use.
const HARVEST: WeeklyPlanCategory = {
  id: "cat-harvest",
  is_active: true,
  sort_order: 1,
  name: "Harvest",
  max_lines: 3,
  can_be_deleted: false,
};
const PACKING: WeeklyPlanCategory = {
  id: "cat-packing",
  is_active: true,
  sort_order: 2,
  name: "Packing",
  max_lines: 2,
  can_be_deleted: true,
};
// No manual order: the plan lists it after the ordered ones.
const CLEANING: WeeklyPlanCategory = {
  id: "cat-cleaning",
  is_active: true,
  sort_order: null,
  name: "Cleaning",
  max_lines: 1,
  can_be_deleted: true,
};
const MARKET: WeeklyPlanCategory = {
  id: "cat-market",
  is_active: false,
  sort_order: 3,
  name: "Market",
  max_lines: 1,
  can_be_deleted: true,
};

// What the server currently holds; the list request answers from it.
let serverCategories: WeeklyPlanCategory[] = [];

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderList() {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ListWeeklyPlanCategory />
    </QueryClientProvider>,
  );
  return { user };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

/** The inputs of the row being edited inline, in column order: sort order,
 *  name, maximum lines. */
function editedInputs() {
  const row = screen
    .getByRole("button", { name: "table.save" })
    .closest("tr");
  if (!row) throw new Error("No row is being edited");
  const [sortOrder, name, maxLines] = within(row).getAllByRole("textbox");
  return { sortOrder, name, maxLines };
}

async function addCategory(
  user: ReturnType<typeof userEvent.setup>,
  {
    sortOrder,
    name,
    maxLines,
  }: { sortOrder?: string; name?: string; maxLines?: string },
) {
  await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
  if (sortOrder) await user.type(editedInputs().sortOrder, sortOrder);
  if (name) await user.type(editedInputs().name, name);
  if (maxLines) await user.type(editedInputs().maxLines, maxLines);
  await user.click(screen.getByRole("button", { name: "table.save" }));
}

beforeEach(() => {
  auth.roles = ["office"];
  serverCategories = [HARVEST, PACKING, CLEANING, MARKET];
  staffApi.listCategories
    .mockReset()
    .mockImplementation(async () => [...serverCategories]);
  staffApi.createCategory
    .mockReset()
    .mockImplementation(async (payload: WeeklyPlanCategory) => ({
      ...payload,
      id: "cat-new",
      can_be_deleted: true,
    }));
  staffApi.updateCategory
    .mockReset()
    .mockImplementation(async (id: string, payload: WeeklyPlanCategory) => ({
      ...payload,
      id,
    }));
  staffApi.deleteCategory.mockReset().mockImplementation(async (id: string) => {
    serverCategories = serverCategories.filter((row) => row.id !== id);
  });
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("ListWeeklyPlanCategory", () => {
  it("loads every category, active or not, with one unfiltered request", async () => {
    renderList();

    await screen.findByText("Harvest");
    expect(staffApi.listCategories).toHaveBeenCalledTimes(1);
    expect(staffApi.listCategories).toHaveBeenCalledWith(undefined);
  });

  it("shows the title, the description and the column headings", async () => {
    renderList();
    await screen.findByText("Harvest");

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "staff.weekly_plan_categories",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 5,
        name: "staff.weekly_plan_categories_description",
      }),
    ).toBeInTheDocument();
    for (const heading of [
      /commissioning\.is_active/,
      "staff.sort_order",
      "staff.name",
      "staff.max_lines",
    ]) {
      expect(
        screen.getByRole("columnheader", { name: heading }),
      ).toBeInTheDocument();
    }
    expect(
      screen.getByText("explainers.list_weekly_plan_categories"),
    ).toBeInTheDocument();
  });

  it("lists each active category with its order and line count, and reveals inactive ones when asked", async () => {
    const { user } = renderList();
    await screen.findByText("Harvest");

    const cellTexts = (name: string) =>
      within(rowOf(name))
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    expect(cellTexts("Harvest")).toEqual(
      expect.arrayContaining(["1", "Harvest", "3"]),
    );
    expect(cellTexts("Cleaning")).toEqual(
      expect.arrayContaining(["", "Cleaning", "1"]),
    );
    expect(screen.queryByText("Market")).not.toBeInTheDocument();

    await user.click(screen.getByText("commissioning.hide_inactive"));

    expect(screen.getByText("Market")).toBeInTheDocument();
  });

  it("creates a category with its order, name and line count, active by default", async () => {
    const { user } = renderList();
    await screen.findByText("Harvest");

    await addCategory(user, { sortOrder: "4", name: "Weeding", maxLines: "2" });

    await waitFor(() => expect(staffApi.createCategory).toHaveBeenCalledTimes(1));
    const [payload] = staffApi.createCategory.mock.calls[0];
    expect(payload).toMatchObject({ is_active: true, name: "Weeding" });
    expect(Number(payload.sort_order)).toBe(4);
    expect(Number(payload.max_lines)).toBe(2);
    expect(await screen.findByText("Weeding")).toBeInTheDocument();
  });

  it("creates a category without an order even though another one has none", async () => {
    const { user } = renderList();
    await screen.findByText("Harvest");

    await addCategory(user, { name: "Weeding", maxLines: "2" });

    await waitFor(() => expect(staffApi.createCategory).toHaveBeenCalledTimes(1));
    const [payload] = staffApi.createCategory.mock.calls[0];
    expect([undefined, null, ""]).toContain(payload.sort_order);
  });

  it("refuses an order another category already has", async () => {
    const { user } = renderList();
    await screen.findByText("Harvest");

    await addCategory(user, { sortOrder: "2", name: "Weeding", maxLines: "2" });

    expect(
      await screen.findByText("staff.sort_order_unique — table.save_failed_hint"),
    ).toBeInTheDocument();
    expect(staffApi.createCategory).not.toHaveBeenCalled();
  });

  it("does not create a category without a name and a line count", async () => {
    // The table logs each refused save; the banner is what the office sees.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { user } = renderList();
    await screen.findByText("Harvest");

    await addCategory(user, { sortOrder: "4" });

    expect(
      await screen.findByText("table.save_failed_generic — table.save_failed_hint"),
    ).toBeInTheDocument();
    expect(editedInputs().name).toHaveAttribute("aria-invalid", "true");
    expect(editedInputs().maxLines).toHaveAttribute("aria-invalid", "true");
    expect(staffApi.createCategory).not.toHaveBeenCalled();
  });

  it("saves a changed line count under the category's id", async () => {
    const { user } = renderList();
    await screen.findByText("Harvest");

    await user.click(
      within(rowOf("Packing")).getByRole("button", { name: "table.edit" }),
    );
    await user.clear(editedInputs().maxLines);
    await user.type(editedInputs().maxLines, "4");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(staffApi.updateCategory).toHaveBeenCalledTimes(1));
    const [id, payload] = staffApi.updateCategory.mock.calls[0];
    expect(id).toBe("cat-packing");
    expect(payload).toMatchObject({ is_active: true, name: "Packing" });
    expect(Number(payload.max_lines)).toBe(4);
    expect(Number(payload.sort_order)).toBe(2);
  });

  it("explains why the backend refuses fewer lines while planned rows would vanish", async () => {
    const message =
      "Weekly-plan entries still sit in rows that a max_lines of 1 would hide. Clear them first.";
    staffApi.updateCategory.mockRejectedValue({
      isAxiosError: true,
      message: "Request failed with status code 409",
      response: {
        status: 409,
        data: {
          code: "staff.weekly_plan_category_shrink_blocked",
          message,
          field: "max_lines",
          details: { max_lines: [message], weeks: [{ year: 2026, week: 42 }] },
        },
      },
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { user } = renderList();
    await screen.findByText("Harvest");

    await user.click(
      within(rowOf("Harvest")).getByRole("button", { name: "table.edit" }),
    );
    await user.clear(editedInputs().maxLines);
    await user.type(editedInputs().maxLines, "1");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    expect(
      await screen.findByText((text) =>
        text.includes(deErrors.staff.weekly_plan_category_shrink_blocked),
      ),
    ).toBeInTheDocument();
    expect(staffApi.updateCategory.mock.calls[0][0]).toBe("cat-harvest");
    // The row stays open so the office can correct the count.
    expect(editedInputs().maxLines).toHaveAttribute("aria-invalid", "true");
  });

  it("deletes an unused category after confirmation and reloads the list", async () => {
    const { user } = renderList();
    await screen.findByText("Harvest");

    await user.click(
      within(rowOf("Packing")).getByRole("button", { name: "table.delete" }),
    );
    await user.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() =>
      expect(staffApi.deleteCategory).toHaveBeenCalledWith("cat-packing"),
    );
    await waitFor(() => expect(staffApi.listCategories).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Packing")).not.toBeInTheDocument();
  });

  it("offers no delete for a category the weekly plan still uses", async () => {
    renderList();
    await screen.findByText("Harvest");

    expect(
      within(rowOf("Harvest")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("Packing")).getByRole("button", { name: "table.delete" }),
    ).toBeInTheDocument();
  });
});

describe("ListWeeklyPlanCategory role gating", () => {
  it.each([{ roles: ["office"] }, { roles: ["admin"] }])(
    "lets $roles add, edit and delete categories",
    async ({ roles }) => {
      auth.roles = roles;
      renderList();
      await screen.findByText("Harvest");

      expect(
        screen.getByRole("button", { name: /table\.add_record/ }),
      ).toBeEnabled();
      expect(
        within(rowOf("Packing")).getByRole("button", { name: "table.edit" }),
      ).toBeEnabled();
      expect(
        within(rowOf("Packing")).getByRole("button", { name: "table.delete" }),
      ).toBeEnabled();
    },
  );

  it.each([
    { roles: ["gardener"] },
    { roles: ["staff"] },
    { roles: ["management"] },
  ])("shows the categories read-only to $roles", async ({ roles }) => {
    auth.roles = roles;
    const { user } = renderList();
    await screen.findByText("Harvest");

    expect(
      screen.queryByRole("button", { name: /table\.add_record/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    for (const editButton of screen.queryAllByRole("button", {
      name: "table.edit",
    })) {
      expect(editButton).toBeDisabled();
    }

    await user.click(screen.getByText("Packing"));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
