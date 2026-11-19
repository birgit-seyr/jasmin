/**
 * ConfigurationShareTypeVariations: the farm's share types, one section per
 * share option. Rendered through the real EditableTable and column hooks; the
 * generated commissioning client is the mocking boundary, its list hooks real
 * TanStack queries around spies. The sizes modal is a stub.
 *
 * Nothing these tests check depends on today's date, so the clock runs free.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareType } from "@shared/api/generated/models";
import { TenantContext } from "@shared/contexts/TenantContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
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

// What the deployment offers, per test; a capability left unset is offered.
const deployment = { capabilities: {} as Record<string, boolean> };

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: ["office"] } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

vi.mock("@features/commissioning/modals", () => ({
  ShareTypeVariationModal: () => null,
}));

const api = vi.hoisted(() => ({ listShareTypes: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const shareTypesKey = (params?: unknown) => [
    "/api/commissioning/share_types/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningShareTypesListQueryKey: shareTypesKey,
    useCommissioningShareTypesList: (
      params?: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: shareTypesKey(params),
        queryFn: () => api.listShareTypes(params),
        enabled: options?.query?.enabled,
      }),
    useCommissioningShareOptionsActiveRetrieve: () =>
      useQuery({
        queryKey: ["/api/commissioning/share_options/active/"],
        queryFn: async () => ({}),
      }),
    commissioningShareTypesCreate: vi.fn(),
    commissioningShareTypesPartialUpdate: vi.fn(),
    commissioningShareTypesDestroy: vi.fn(),
  };
});

import ConfigurationShareTypeVariations from "../ConfigurationShareTypeVariations";

const VEGETABLES = {
  id: "st-vegetables",
  name: "Vegetables",
  short_name: "Veg",
  share_option: "HARVEST_SHARE",
  delivery_cycle: "WEEKLY",
  valid_from: "2026-01-05",
  valid_until: null,
  can_be_deleted: true,
} as ShareType;

const EGGS = {
  ...VEGETABLES,
  id: "st-eggs",
  name: "Eggs",
  short_name: "Eggs",
  share_option: "CHICKEN_SHARE",
} as ShareType;

const SHARE_OPTIONS = [
  "HARVEST_SHARE",
  "HARVEST_SHARE_FRUIT",
  "CHICKEN_SHARE",
  "HONEY_SHARE",
  "OIL_SHARE",
  "GRAIN_SHARE",
  "BREAD_SHARE",
];

const sectionTitle = (shareOption: string) =>
  `commissioning.share_option.${shareOption}`;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const tenantContext = { tenant: deployment } as unknown as Parameters<
    typeof TenantContext.Provider
  >[0]["value"];
  render(
    <QueryClientProvider client={queryClient}>
      <TenantContext.Provider value={tenantContext}>
        <ConfigurationShareTypeVariations />
      </TenantContext.Provider>
    </QueryClientProvider>,
  );
}

/** Opens the harvest share section and waits for its share type. */
async function openVegetables(): Promise<HTMLElement> {
  await userEvent.click(await screen.findByText(sectionTitle("HARVEST_SHARE")));
  const name = await screen.findByText("Vegetables");
  const row = name.closest("tr");
  if (!row) throw new Error("The vegetables are not listed");
  return row;
}

beforeEach(() => {
  deployment.capabilities = {};
  api.listShareTypes
    .mockReset()
    .mockImplementation(async (params?: { share_option?: string }) =>
      [VEGETABLES, EGGS].filter(
        (shareType) =>
          !params?.share_option || shareType.share_option === params.share_option,
      ),
    );
});

describe("ConfigurationShareTypeVariations where the farm keeps its share types", () => {
  it("lists a section for every share option without loading every share type", async () => {
    renderPage();

    for (const shareOption of SHARE_OPTIONS) {
      expect(await screen.findByText(sectionTitle(shareOption))).toBeInTheDocument();
    }
    expect(api.listShareTypes).not.toHaveBeenCalledWith(undefined);
  });

  it("lets the office add and delete share types", async () => {
    renderPage();
    const row = await openVegetables();

    expect(
      screen.getByRole("button", { name: /table\.add_record/ }),
    ).toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "table.delete" }),
    ).toBeInTheDocument();
  });

  it("lets the office rename a share type", async () => {
    renderPage();
    const row = await openVegetables();

    await userEvent.click(within(row).getByRole("button", { name: "table.edit" }));

    const editing = screen.getByRole("button", { name: "table.save" }).closest("tr");
    if (!editing) throw new Error("No row is being edited");
    expect(within(editing).getByLabelText("commissioning.name")).toHaveValue(
      "Vegetables",
    );
  });
});

describe("ConfigurationShareTypeVariations where a host syncs the share types in", () => {
  beforeEach(() => {
    deployment.capabilities = { share_types: false };
  });

  it("lists only the share options that have share types", async () => {
    renderPage();

    expect(await screen.findByText(sectionTitle("CHICKEN_SHARE"))).toBeInTheDocument();
    expect(screen.getByText(sectionTitle("HARVEST_SHARE"))).toBeInTheDocument();
    for (const shareOption of SHARE_OPTIONS.filter(
      (option) => option !== "HARVEST_SHARE" && option !== "CHICKEN_SHARE",
    )) {
      expect(screen.queryByText(sectionTitle(shareOption))).not.toBeInTheDocument();
    }
  });

  it("lets the office edit share types but add and delete none", async () => {
    renderPage();
    const row = await openVegetables();

    expect(
      screen.queryByRole("button", { name: /table\.add_record/ }),
    ).not.toBeInTheDocument();
    expect(
      within(row).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "table.edit" }),
    ).toBeInTheDocument();
  });

  it("keeps the synced name while the rest is edited", async () => {
    renderPage();
    const row = await openVegetables();

    await userEvent.click(within(row).getByRole("button", { name: "table.edit" }));

    const editing = screen.getByRole("button", { name: "table.save" }).closest("tr");
    if (!editing) throw new Error("No row is being edited");
    expect(within(editing).getByLabelText("commissioning.short_name")).toHaveValue("Veg");
    expect(
      within(editing).queryByLabelText("commissioning.name"),
    ).not.toBeInTheDocument();
    expect(within(editing).getByText("Vegetables")).toBeInTheDocument();
  });
});
