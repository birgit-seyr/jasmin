// The scale VAT codes render through the real CrudListPage and EditableTable;
// only the generated commissioning client is replaced (the list hook by a real
// TanStack query around a spy).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScaleTaxCode } from "@shared/api/generated/models";

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
      useCommissioningScaleTaxCodesList: (params?: unknown) =>
        useQuery({
          queryKey: ["/api/commissioning/scale_tax_codes/", params],
          queryFn: (): Promise<ScaleTaxCode[]> => api.list(params),
        }),
      commissioningScaleTaxCodesCreate: (code: ScaleTaxCode) => api.create(code),
      commissioningScaleTaxCodesPartialUpdate: (id: string, code: ScaleTaxCode) =>
        api.update(id, code),
      commissioningScaleTaxCodesDestroy: (id: string) => api.destroy(id),
    };
  },
);

import ListScaleTaxCodes from "../ListScaleTaxCodes";

// PLUs sell under the reduced rate's code, so it can't go.
const REDUCED: ScaleTaxCode = { id: "tc-7", tax_rate: "7.00", code: 1, can_be_deleted: false };
const STANDARD: ScaleTaxCode = { id: "tc-19", tax_rate: "19.00", code: 2, can_be_deleted: true };

function renderList() {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ListScaleTaxCodes />
    </QueryClientProvider>,
  );
  return { user };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

/** The text inputs of the row being edited inline, in column order. */
function editedInputs(): HTMLElement[] {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return within(row).getAllByRole("textbox");
}

beforeEach(() => {
  auth.roles = ["office"];
  api.list.mockReset().mockResolvedValue([REDUCED, STANDARD]);
  api.create.mockReset().mockImplementation(async (payload: ScaleTaxCode) => ({
    ...payload, id: "tc-new", can_be_deleted: true,
  }));
  api.update.mockReset();
  api.destroy.mockReset();
});

describe("ListScaleTaxCodes", () => {
  it("lists each VAT rate with the scale's code", async () => {
    renderList();

    await screen.findByText("7.00 %");
    expect(within(rowOf("7.00 %")).getByText("1")).toBeInTheDocument();
    expect(within(rowOf("19.00 %")).getByText("2")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_scale_tax_codes")).toBeInTheDocument();
  });

  it("adds the code of another rate", async () => {
    const { user } = renderList();
    await screen.findByText("7.00 %");

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    const [rate, code] = editedInputs();
    await user.type(rate, "0");
    await user.type(code, "3");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const [payload] = api.create.mock.calls[0];
    expect(Number(payload.tax_rate)).toBe(0);
    expect(Number(payload.code)).toBe(3);
  });

  it("offers no delete for a code PLUs still sell under", async () => {
    renderList();
    await screen.findByText("7.00 %");

    expect(
      within(rowOf("7.00 %")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("19.00 %")).getByRole("button", { name: "table.delete" }),
    ).toBeInTheDocument();
  });

  it("shows the codes read-only to staff", async () => {
    auth.roles = ["staff"];
    renderList();
    await screen.findByText("7.00 %");

    expect(
      screen.queryByRole("button", { name: /table\.add_record/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
  });
});
