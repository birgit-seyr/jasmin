// The market product groups list renders through the real CrudListPage and
// EditableTable; only the generated commissioning client is replaced (the list
// hook by a real TanStack query around a spy).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketProductGroup } from "@shared/api/generated/models";

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

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock(
  "@shared/api/generated/commissioning/commissioning",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@shared/api/generated/commissioning/commissioning")
      >();
    const { useQuery } = await import("@tanstack/react-query");
    return {
      ...actual,
      useCommissioningMarketProductGroupsList: (params?: unknown) =>
        useQuery({
          queryKey: ["/api/commissioning/market_product_groups/", params],
          queryFn: (): Promise<MarketProductGroup[]> => api.list(params),
        }),
      commissioningMarketProductGroupsCreate: (group: MarketProductGroup) => api.create(group),
      commissioningMarketProductGroupsPartialUpdate: (id: string, group: MarketProductGroup) =>
        api.update(id, group),
      commissioningMarketProductGroupsDestroy: (id: string) => api.destroy(id),
    };
  },
);

import ListMarketProductGroups from "../ListMarketProductGroups";

// Apples still group PLUs, so they can't go.
const APPLES: MarketProductGroup = {
  id: "pg-apples", is_active: true, number: 1, name: "Apples", can_be_deleted: false,
};
const BREAD: MarketProductGroup = {
  id: "pg-bread", is_active: true, number: 16, name: "Bread", can_be_deleted: true,
};

function renderList() {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ListMarketProductGroups />
    </QueryClientProvider>,
  );
  return { user };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

/** The inputs of the row being edited inline, in column order: number, name. */
function editedInputs() {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  const [number, name] = within(row).getAllByRole("textbox");
  return { number, name };
}

beforeEach(() => {
  auth.roles = ["office"];
  api.list.mockReset().mockResolvedValue([APPLES, BREAD]);
  api.create.mockReset().mockImplementation(async (payload: MarketProductGroup) => ({
    ...payload, id: "pg-new", number: Number(payload.number), can_be_deleted: true,
  }));
  api.update.mockReset();
  api.destroy.mockReset();
});

describe("ListMarketProductGroups", () => {
  it("lists the groups by number under the page's title and explainer", async () => {
    renderList();

    await screen.findByText("Apples");
    expect(within(rowOf("Apples")).getByText("1")).toBeInTheDocument();
    expect(within(rowOf("Bread")).getByText("16")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "commissioning.list_market_product_groups" }),
    ).toBeInTheDocument();
    expect(screen.getByText("explainers.list_market_product_groups")).toBeInTheDocument();
  });

  it("adds a group", async () => {
    const { user } = renderList();
    await screen.findByText("Apples");

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    await user.type(editedInputs().number, "5");
    await user.type(editedInputs().name, "Root vegetables");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const [payload] = api.create.mock.calls[0];
    expect(payload).toMatchObject({ is_active: true, name: "Root vegetables" });
    expect(Number(payload.number)).toBe(5);
  });

  it("refuses a number another group has", async () => {
    const { user } = renderList();
    await screen.findByText("Apples");

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    await user.type(editedInputs().number, "16");
    await user.type(editedInputs().name, "Pastries");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    expect(
      await screen.findByText("validation.unique.number — table.save_failed_hint"),
    ).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("offers no delete for a group PLUs still belong to", async () => {
    renderList();
    await screen.findByText("Apples");

    expect(
      within(rowOf("Apples")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("Bread")).getByRole("button", { name: "table.delete" }),
    ).toBeInTheDocument();
  });

  it("shows the groups read-only to staff", async () => {
    auth.roles = ["staff"];
    renderList();
    await screen.findByText("Apples");

    expect(
      screen.queryByRole("button", { name: /table\.add_record/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
  });
});
