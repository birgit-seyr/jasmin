/**
 * StationBulkPercentagesModal: the surcharge each active delivery station adds
 * on its loose packing list. Rendered through the real EditableTable; the
 * generated client is the mocking boundary, its list hook a real TanStack
 * query around a spy.
 *
 * Nothing these tests check depends on today's date, so the clock runs free.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DeliveryStation } from "@shared/api/generated/models";

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

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const api = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const listKey = (params?: unknown) => [
    "/api/commissioning/delivery_stations/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningDeliveryStationsListQueryKey: listKey,
    getCommissioningDeliveryStationsListQueryOptions: (params: unknown) => ({
      queryKey: listKey(params),
      queryFn: () => api.list(params),
    }),
    useCommissioningDeliveryStationsList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: listKey(params),
        queryFn: () => api.list(params),
        enabled: options?.query?.enabled,
      }),
    commissioningDeliveryStationsPartialUpdate: (id: string, station: unknown) =>
      api.update(id, station),
  };
});

import StationBulkPercentagesModal from "../StationBulkPercentagesModal";

const FIELD = "percentage_added_to_bulk_packing_list";
const SURCHARGE = "settings.commissioning.station_bulk_percentages.column";

const MARKET_HALL = {
  id: "st-hall",
  short_name: "Market hall",
  is_active: true,
  picture: "/media/hall.jpg",
  [FIELD]: 10,
} as DeliveryStation;

const VILLAGE_SHOP = {
  id: "st-shop",
  short_name: null,
  company_name: "Village shop",
  is_active: true,
  [FIELD]: null,
} as DeliveryStation;

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <StationBulkPercentagesModal open onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

function rowOf(name: string): HTMLElement {
  const row = screen.getByText(name).closest("tr");
  if (!row) throw new Error(`${name} is not listed`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

async function setSurcharge(name: string, value: string) {
  await userEvent.click(within(rowOf(name)).getByRole("button", { name: "table.edit" }));
  const input = within(editingRow()).getByLabelText(SURCHARGE);
  await userEvent.clear(input);
  if (value) await userEvent.type(input, value);
  await userEvent.click(screen.getByRole("button", { name: "table.save" }));
}

beforeEach(() => {
  auth.roles = ["office"];
  api.list.mockReset().mockResolvedValue([MARKET_HALL, VILLAGE_SHOP]);
  api.update
    .mockReset()
    .mockImplementation(async (id: string, station: Partial<DeliveryStation>) => ({
      ...[MARKET_HALL, VILLAGE_SHOP].find((row) => row.id === id),
      ...station,
    }));
});

describe("StationBulkPercentagesModal", () => {
  it("lists the active stations by name with their surcharge", async () => {
    renderModal();

    expect(await screen.findByText("Market hall")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith({ is_active: true });
    expect(within(rowOf("Market hall")).getByText("10 %")).toBeInTheDocument();
    expect(within(rowOf("Village shop")).queryByText(/%/)).not.toBeInTheDocument();
  });

  it("sends only the surcharge, not the rest of the station", async () => {
    renderModal();
    await screen.findByText("Market hall");

    await setSurcharge("Market hall", "12");

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    const [id, payload] = api.update.mock.calls[0];
    expect(id).toBe("st-hall");
    expect(Object.keys(payload)).toEqual([FIELD]);
    expect(Number(payload[FIELD])).toBe(12);
  });

  it("clears a surcharge emptied in its cell", async () => {
    renderModal();
    await screen.findByText("Market hall");

    await setSurcharge("Market hall", "");

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith("st-hall", { [FIELD]: null }),
    );
  });

  it("adds and deletes no station", async () => {
    renderModal();
    await screen.findByText("Market hall");

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
  });

  it("shows the surcharges read-only to staff without the office role", async () => {
    auth.roles = ["staff"];
    renderModal();
    await screen.findByText("Market hall");

    expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();
  });
});
