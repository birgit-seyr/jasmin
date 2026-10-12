// The absence-categories list renders through the real CrudListPage and
// EditableTable; only the generated staff client is replaced (the list hook by
// a real TanStack query around a spy).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AbsenceCategory,
  StaffAbsenceCategoriesListParams,
} from "@shared/api/generated/models";

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
  listAbsenceCategories: vi.fn(),
  createAbsenceCategory: vi.fn(),
  updateAbsenceCategory: vi.fn(),
  deleteAbsenceCategory: vi.fn(),
}));

vi.mock("@shared/api/generated/staff/staff", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@shared/api/generated/staff/staff")>();
  const { useQuery } = await import("@tanstack/react-query");
  return {
    ...actual,
    useStaffAbsenceCategoriesList: (
      params?: StaffAbsenceCategoriesListParams,
    ) =>
      useQuery({
        queryKey: actual.getStaffAbsenceCategoriesListQueryKey(params),
        queryFn: (): Promise<AbsenceCategory[]> =>
          staffApi.listAbsenceCategories(params),
      }),
    staffAbsenceCategoriesCreate: (category: AbsenceCategory) =>
      staffApi.createAbsenceCategory(category),
    staffAbsenceCategoriesPartialUpdate: (
      id: string,
      category: AbsenceCategory,
    ) => staffApi.updateAbsenceCategory(id, category),
    staffAbsenceCategoriesDestroy: (id: string) =>
      staffApi.deleteAbsenceCategory(id),
  };
});

import ListAbsenceCategory from "../ListAbsenceCategory";

// ── Fixtures ────────────────────────────────────────────────────────────────

// Absences still point at the 2026 vacation category, so it is in use.
const VACATION_2026: AbsenceCategory = {
  id: "abs-vacation-2026",
  is_active: true,
  year: 2026,
  name: "Vacation",
  can_be_deleted: false,
};
const SICK_LEAVE_2026: AbsenceCategory = {
  id: "abs-sick-2026",
  is_active: true,
  year: 2026,
  name: "Sick leave",
  can_be_deleted: true,
};
const TRAINING_2025: AbsenceCategory = {
  id: "abs-training-2025",
  is_active: false,
  year: 2025,
  name: "Training",
  can_be_deleted: true,
};

// What the server currently holds; the list request answers from it.
let serverCategories: AbsenceCategory[] = [];

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
      <ListAbsenceCategory />
    </QueryClientProvider>,
  );
  return { user };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

/** The inputs of the row being edited inline, in column order: year, name. */
function editedInputs() {
  const row = screen
    .getByRole("button", { name: "table.save" })
    .closest("tr");
  if (!row) throw new Error("No row is being edited");
  const [year, name] = within(row).getAllByRole("textbox");
  return { year, name };
}

beforeEach(() => {
  auth.roles = ["office"];
  serverCategories = [VACATION_2026, SICK_LEAVE_2026, TRAINING_2025];
  staffApi.listAbsenceCategories
    .mockReset()
    .mockImplementation(async () => [...serverCategories]);
  staffApi.createAbsenceCategory
    .mockReset()
    .mockImplementation(async (payload: AbsenceCategory) => ({
      ...payload,
      id: "abs-new",
      year: Number(payload.year),
      can_be_deleted: true,
    }));
  staffApi.updateAbsenceCategory
    .mockReset()
    .mockImplementation(async (id: string, payload: AbsenceCategory) => ({
      ...payload,
      id,
      year: Number(payload.year),
    }));
  staffApi.deleteAbsenceCategory
    .mockReset()
    .mockImplementation(async (id: string) => {
      serverCategories = serverCategories.filter((row) => row.id !== id);
    });
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("ListAbsenceCategory", () => {
  it("loads every category, active or not, with one unfiltered request", async () => {
    renderList();

    await screen.findByText("Vacation");
    expect(staffApi.listAbsenceCategories).toHaveBeenCalledTimes(1);
    expect(staffApi.listAbsenceCategories).toHaveBeenCalledWith(undefined);
  });

  it("shows the title, the description and the column headings", async () => {
    renderList();
    await screen.findByText("Vacation");

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "staff.absence_categories",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 5,
        name: "staff.absence_categories_description",
      }),
    ).toBeInTheDocument();
    for (const heading of [/commissioning\.is_active/, "common.year", "staff.name"]) {
      expect(
        screen.getByRole("columnheader", { name: heading }),
      ).toBeInTheDocument();
    }
    expect(
      screen.getByText("explainers.list_absence_categories"),
    ).toBeInTheDocument();
  });

  it("lists each active category with its year and reveals inactive ones when asked", async () => {
    const { user } = renderList();
    await screen.findByText("Vacation");

    expect(within(rowOf("Vacation")).getByText("2026")).toBeInTheDocument();
    expect(within(rowOf("Sick leave")).getByText("2026")).toBeInTheDocument();
    expect(screen.queryByText("Training")).not.toBeInTheDocument();

    await user.click(screen.getByText("commissioning.hide_inactive"));

    expect(within(rowOf("Training")).getByText("2025")).toBeInTheDocument();
  });

  it("creates a category for another year under a name an earlier year already has", async () => {
    const { user } = renderList();
    await screen.findByText("Vacation");

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    await user.type(editedInputs().year, "2027");
    await user.type(editedInputs().name, "Vacation");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(staffApi.createAbsenceCategory).toHaveBeenCalledTimes(1),
    );
    const [payload] = staffApi.createAbsenceCategory.mock.calls[0];
    expect(payload).toMatchObject({ is_active: true, name: "Vacation" });
    expect(Number(payload.year)).toBe(2027);
    expect(await screen.findByText("2027")).toBeInTheDocument();
  });

  it("refuses a second category with the same name in the same year", async () => {
    const { user } = renderList();
    await screen.findByText("Vacation");

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    await user.type(editedInputs().year, "2026");
    await user.type(editedInputs().name, "Vacation");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    expect(
      await screen.findByText(
        "staff.absence_category_year_name_unique — table.save_failed_hint",
      ),
    ).toBeInTheDocument();
    expect(staffApi.createAbsenceCategory).not.toHaveBeenCalled();
  });

  it("saves a renamed category under its id", async () => {
    const { user } = renderList();
    await screen.findByText("Vacation");

    await user.click(
      within(rowOf("Sick leave")).getByRole("button", { name: "table.edit" }),
    );
    await user.clear(editedInputs().name);
    await user.type(editedInputs().name, "Illness");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(staffApi.updateAbsenceCategory).toHaveBeenCalledTimes(1),
    );
    const [id, payload] = staffApi.updateAbsenceCategory.mock.calls[0];
    expect(id).toBe("abs-sick-2026");
    expect(payload).toMatchObject({ is_active: true, name: "Illness" });
    expect(Number(payload.year)).toBe(2026);
    expect(await screen.findByText("Illness")).toBeInTheDocument();
  });

  it("deletes an unused category after confirmation and reloads the list", async () => {
    const { user } = renderList();
    await screen.findByText("Vacation");

    await user.click(
      within(rowOf("Sick leave")).getByRole("button", {
        name: "table.delete",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() =>
      expect(staffApi.deleteAbsenceCategory).toHaveBeenCalledWith(
        "abs-sick-2026",
      ),
    );
    await waitFor(() =>
      expect(staffApi.listAbsenceCategories).toHaveBeenCalledTimes(2),
    );
    expect(screen.queryByText("Sick leave")).not.toBeInTheDocument();
  });

  it("offers no delete for a category that absences still use", async () => {
    renderList();
    await screen.findByText("Vacation");

    expect(
      within(rowOf("Vacation")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("Sick leave")).getByRole("button", {
        name: "table.delete",
      }),
    ).toBeInTheDocument();
  });
});

describe("ListAbsenceCategory role gating", () => {
  it.each([{ roles: ["office"] }, { roles: ["admin"] }])(
    "lets $roles add, edit and delete categories",
    async ({ roles }) => {
      auth.roles = roles;
      renderList();
      await screen.findByText("Vacation");

      expect(
        screen.getByRole("button", { name: /table\.add_record/ }),
      ).toBeEnabled();
      expect(
        within(rowOf("Sick leave")).getByRole("button", { name: "table.edit" }),
      ).toBeEnabled();
      expect(
        within(rowOf("Sick leave")).getByRole("button", {
          name: "table.delete",
        }),
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
    await screen.findByText("Vacation");

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

    await user.click(screen.getByText("Sick leave"));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
