/**
 * ConfigurationDeliveryDays: the weekdays shares and orders are delivered on.
 * Rendered through the real EditableTable and time-bound column hooks; the
 * generated commissioning client is the mocking boundary, its list hooks real
 * TanStack queries around spies.
 *
 * Only whether a delivery day has ended depends on today's date, and the one
 * that has ended did so in January 2026, so the clock runs free.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SharesDeliveryDay } from "@shared/api/generated/models";
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

// Per-test tenant settings over the mock's own.
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const base = makeUseTenantMock();
  const tenant = {
    ...base,
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values
        ? tenantSettings.values[key]
        : base.getSetting(key, defaultValue),
  };
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

const api = vi.hoisted(() => ({
  listShareDays: vi.fn(),
  listOrderDays: vi.fn(),
  createShareDay: vi.fn(),
  updateShareDay: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const shareDaysKey = (params?: unknown) => [
    "/api/commissioning/shares_delivery_days/",
    ...(params ? [params] : []),
  ];
  const orderDaysKey = () => ["/api/commissioning/orders_delivery_days/"];
  return {
    getCommissioningSharesDeliveryDaysListQueryKey: shareDaysKey,
    getCommissioningOrdersDeliveryDaysListQueryKey: orderDaysKey,
    useCommissioningSharesDeliveryDaysList: (params?: unknown) =>
      useQuery({ queryKey: shareDaysKey(params), queryFn: () => api.listShareDays(params) }),
    useCommissioningOrdersDeliveryDaysList: (options?: { query?: { enabled?: boolean } }) =>
      useQuery({
        queryKey: orderDaysKey(),
        queryFn: () => api.listOrderDays(),
        enabled: options?.query?.enabled,
      }),
    commissioningSharesDeliveryDaysCreate: (day: unknown) => api.createShareDay(day),
    commissioningSharesDeliveryDaysPartialUpdate: (id: string, day: unknown) =>
      api.updateShareDay(id, day),
    commissioningSharesDeliveryDaysDestroy: vi.fn(),
    commissioningOrdersDeliveryDaysCreate: vi.fn(),
    commissioningOrdersDeliveryDaysPartialUpdate: vi.fn(),
    commissioningOrdersDeliveryDaysDestroy: vi.fn(),
  };
});

import ConfigurationDeliveryDays from "../ConfigurationDeliveryDays";

const WEDNESDAY: SharesDeliveryDay = {
  id: "day-wednesday",
  day_number: 2,
  valid_from: "2026-01-05",
  valid_until: null,
  default_harvesting_day: 1,
  default_packing_day: 2,
  default_washing_day: 1,
  default_cleaning_day: 1,
  default_get_current_stock_day: 1,
  number_of_tours: 2,
  can_be_deleted: false,
} as SharesDeliveryDay;

// Not in use yet, so the office could delete it.
const FRIDAY: SharesDeliveryDay = {
  ...WEDNESDAY,
  id: "day-friday",
  day_number: 4,
  can_be_deleted: true,
} as SharesDeliveryDay;

const TOURS = "configuration.number_of_tours";

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
        <ConfigurationDeliveryDays />
      </TenantContext.Provider>
    </QueryClientProvider>,
  );
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

/** The cell of ``row`` under the share days' column whose title starts so. */
function cellOf(row: HTMLElement, columnTitle: string): HTMLElement {
  const table = row.closest("table");
  const titles = Array.from(table?.querySelectorAll("thead th") ?? []).map(
    (th) => th.textContent ?? "",
  );
  const index = titles.findIndex((title) => title.startsWith(columnTitle));
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${columnTitle}`);
  return cell;
}

/** The titles of every column on the page. */
const columnTitles = () =>
  screen.getAllByRole("columnheader").map((header) => header.textContent ?? "");

async function startNewShareDay() {
  await screen.findAllByText("configuration.acronym_wednesday");
  const [shareDaysAdd] = screen.getAllByRole("button", { name: /table\.add_record/ });
  await userEvent.click(shareDaysAdd);
}

/** The rows of the share delivery days, the page's first table. */
const shareDayRows = () =>
  Array.from(
    document.querySelectorAll<HTMLElement>(".ant-table-tbody")[0]?.querySelectorAll<HTMLElement>(
      ":scope > tr.ant-table-row",
    ) ?? [],
  );

beforeEach(() => {
  deployment.capabilities = {};
  tenantSettings.values = {};
  api.listShareDays.mockReset().mockResolvedValue([WEDNESDAY, FRIDAY]);
  api.listOrderDays.mockReset().mockResolvedValue([]);
  api.createShareDay.mockReset().mockImplementation(async (day: SharesDeliveryDay) => ({
    ...day,
    id: "day-new",
  }));
  api.updateShareDay
    .mockReset()
    .mockImplementation(async (id: string, day: SharesDeliveryDay) => ({ ...WEDNESDAY, ...day, id }));
});

describe("ConfigurationDeliveryDays new delivery day", () => {
  it("starts a new delivery day with one tour", async () => {
    renderPage();
    await startNewShareDay();

    expect(columnTitles()).toContain(TOURS);
    expect(within(editingRow()).getByLabelText(TOURS)).toHaveValue("1");
  });

  it("refuses to save a new delivery day without a number of tours", async () => {
    renderPage();
    await startNewShareDay();

    await userEvent.clear(within(editingRow()).getByLabelText(TOURS));
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    expect(await within(cellOf(editingRow(), TOURS)).findByText("table.required")).toBeInTheDocument();
    expect(api.createShareDay).not.toHaveBeenCalled();
  });
});

describe("ConfigurationDeliveryDays where the host brings the delivery days", () => {
  beforeEach(() => {
    deployment.capabilities = { delivery_stations: false };
  });

  it("adds and deletes no share delivery day", async () => {
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    // The one add button left belongs to the order days.
    expect(screen.getAllByRole("button", { name: /table\.add_record/ })).toHaveLength(1);
    for (const row of shareDayRows()) {
      expect(within(row).queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    }
  });

  it("keeps a share delivery day's weekday and validity, and lets the office set its work days", async () => {
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    await userEvent.click(within(shareDayRows()[1]).getByRole("button", { name: "table.edit" }));

    const row = editingRow();
    expect(within(row).queryByLabelText("configuration.valid_from")).not.toBeInTheDocument();
    expect(within(row).queryByLabelText("configuration.valid_until")).not.toBeInTheDocument();
    expect(within(row).queryByLabelText("configuration.delivery_day")).not.toBeInTheDocument();
    expect(
      within(row).getByRole("combobox", { name: "configuration.default_harvesting_day" }),
    ).toBeEnabled();
  });

  it("leaves the tours to the host", async () => {
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    expect(columnTitles()).not.toContain(TOURS);
    expect(columnTitles()).toContain("configuration.default_harvesting_day");
  });
});

describe("ConfigurationDeliveryDays work days of a day in use", () => {
  const HARVESTING = "configuration.default_harvesting_day";
  const PACKING = "configuration.default_packing_day";

  async function editWednesday(): Promise<HTMLElement> {
    await screen.findAllByText("configuration.acronym_wednesday");
    const row = document.querySelector<HTMLElement>('tr[data-row-key="day-wednesday"]');
    if (!row) throw new Error("Wednesday is not listed");
    await userEvent.click(within(row).getByRole("button", { name: "table.edit" }));
    return editingRow();
  }

  beforeEach(() => {
    // A host's sync brings the days, and they are in use at once.
    deployment.capabilities = { delivery_stations: false };
  });

  it("keeps them once the day has them all", async () => {
    renderPage();
    const row = await editWednesday();

    expect(within(row).queryByRole("combobox", { name: HARVESTING })).not.toBeInTheDocument();
    expect(within(row).queryByRole("combobox", { name: PACKING })).not.toBeInTheDocument();
  });

  it("opens them while the day lacks one, as the banner over the commissioning pages asks", async () => {
    api.listShareDays.mockResolvedValue([
      { ...WEDNESDAY, default_harvesting_day: null },
      FRIDAY,
    ]);
    renderPage();
    const row = await editWednesday();

    expect(within(row).getByRole("combobox", { name: HARVESTING })).toBeEnabled();
    expect(within(row).getByRole("combobox", { name: PACKING })).toBeEnabled();
  });

  it("saves the work day picked for a day that lacked it", async () => {
    api.listShareDays.mockResolvedValue([
      { ...WEDNESDAY, default_harvesting_day: null },
      FRIDAY,
    ]);
    renderPage();
    const row = await editWednesday();

    await userEvent.click(within(row).getByRole("combobox", { name: HARVESTING }));
    const monday = await waitFor(() => {
      const option = document.querySelector<HTMLElement>(
        '.ant-select-dropdown:not(.ant-select-dropdown-hidden) [title="configuration.acronym_monday"]',
      );
      if (!option) throw new Error("Monday is not offered");
      return option;
    });
    await userEvent.click(monday);
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(api.updateShareDay).toHaveBeenCalledWith(
        "day-wednesday",
        expect.objectContaining({ default_harvesting_day: 0, default_packing_day: 2 }),
      ),
    );

    // With every work day saved, the day in use keeps them again.
    const again = await editWednesday();
    expect(within(again).queryByRole("combobox", { name: HARVESTING })).not.toBeInTheDocument();
  });

  it("keeps them on a farm that hides washing and cleaning once the day has the rest", async () => {
    tenantSettings.values = { show_washing: false, show_cleaning: false };
    api.listShareDays.mockResolvedValue([
      { ...WEDNESDAY, default_washing_day: null, default_cleaning_day: null },
      FRIDAY,
    ]);
    renderPage();
    const row = await editWednesday();

    expect(within(row).queryByRole("combobox", { name: HARVESTING })).not.toBeInTheDocument();
    expect(within(row).queryByRole("combobox", { name: PACKING })).not.toBeInTheDocument();
  });

  it("keeps them on a day that has ended, which the banner no longer names", async () => {
    api.listShareDays.mockResolvedValue([
      { ...WEDNESDAY, valid_until: "2026-01-11", default_harvesting_day: null },
      FRIDAY,
    ]);
    renderPage();
    const row = await editWednesday();

    expect(within(row).queryByRole("combobox", { name: HARVESTING })).not.toBeInTheDocument();
  });
});

describe("ConfigurationDeliveryDays stock-count day", () => {
  it("is shown on neither table, as nothing reads it", async () => {
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    expect(columnTitles()).not.toContain("configuration.default_get_current_stock_day");
  });
});

describe("ConfigurationDeliveryDays order days", () => {
  const ORDER_DAYS = "configuration.time_manamagent_for_orders";

  it("lists the order days where the farm sells to resellers", async () => {
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    expect(screen.getByText(ORDER_DAYS)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /table\.add_record/ })).toHaveLength(2);
    expect(api.listOrderDays).toHaveBeenCalled();
  });

  it("leaves them out, unloaded, where the farm sells to no reseller", async () => {
    tenantSettings.values = { sells_to_resellers: false };
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    expect(screen.queryByText(ORDER_DAYS)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /table\.add_record/ })).toHaveLength(1);
    expect(api.listOrderDays).not.toHaveBeenCalled();
  });
});

describe("ConfigurationDeliveryDays on a farm that hides washing and cleaning", () => {
  it("shows the washing and cleaning days on both tables by default", async () => {
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    expect(screen.getAllByText("configuration.default_washing_day").length).toBeGreaterThan(0);
    expect(screen.getAllByText("configuration.default_cleaning_day").length).toBeGreaterThan(0);
  });

  it("leaves them out of both tables", async () => {
    tenantSettings.values = { show_washing: false, show_cleaning: false };
    renderPage();
    await screen.findAllByText("configuration.acronym_wednesday");

    expect(screen.queryByText("configuration.default_washing_day")).not.toBeInTheDocument();
    expect(screen.queryByText("configuration.default_cleaning_day")).not.toBeInTheDocument();
    expect(screen.getAllByText("configuration.default_harvesting_day").length).toBeGreaterThan(0);
  });
});
