/**
 * Offers page: the weekly offers one offer group gets, their tiered prices,
 * and the bulk actions around them (create for every group, finalize, copy,
 * send by email).
 *
 * The page's own hooks (``useOffersData``, ``useOffersColumns`` and the column
 * hooks under it), the bulk-action row and the send modal are real; the
 * generated API client is the mocking boundary. EditableTable is a stub that
 * records its props and renders each row through the real column renders, and
 * the week / offer-group selectors are stubs with plain buttons.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import dayjs from "dayjs";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EditableColumnConfig,
  EditableTableProps,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    // Interpolation values are appended, so a message's counts can be asserted.
    t: (key: string, values?: unknown) =>
      typeof values === "string" ? values : values ? `${key} ${JSON.stringify(values)}` : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const tenantState = vi.hoisted(() => ({
  values: {} as Record<string, unknown>,
  refreshTenant: vi.fn(),
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.values ? tenantState.values[key] : defaultValue,
    refreshTenant: () => tenantState.refreshTenant(),
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the roles of the logged-in user from here.
const authState = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: authState.roles } }),
}));

const { notifyMock, api } = vi.hoisted(() => ({
  notifyMock: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  api: {
    offersList: vi.fn(),
    sendingStatusList: vi.fn(),
    offerGroupsList: vi.fn(),
    createOffers: vi.fn(),
    offersCreate: vi.fn(),
    offersPartialUpdate: vi.fn(),
    offersDestroy: vi.fn(),
    bulkSend: vi.fn(),
    bulkFinalize: vi.fn(),
    copyToNextWeek: vi.fn(),
    copyToOfferGroup: vi.fn(),
    updateTenantSettings: vi.fn(),
  },
}));

vi.mock("@shared/utils/notify", () => ({ default: notifyMock }));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningOffersList: (params: unknown, options: unknown) =>
    api.offersList(params, options),
  getCommissioningOffersListQueryKey: (params?: unknown) => [
    "/api/commissioning/offers/",
    ...(params ? [params] : []),
  ],
  useCommissioningOfferSendingStatusList: (params: unknown, options: unknown) =>
    api.sendingStatusList(params, options),
  getCommissioningOfferSendingStatusListQueryKey: (params?: unknown) => [
    "/api/commissioning/offer_sending_status/",
    ...(params ? [params] : []),
  ],
  useCommissioningOfferGroupsList: () => api.offerGroupsList(),
  useCommissioningShareArticlesList: () => ({
    data: SHARE_ARTICLES,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCommissioningCratesList: () => ({
    data: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  commissioningCreateOffersCreate: (...args: unknown[]) =>
    api.createOffers(...args),
  commissioningOffersCreate: (...args: unknown[]) => api.offersCreate(...args),
  commissioningOffersPartialUpdate: (...args: unknown[]) =>
    api.offersPartialUpdate(...args),
  commissioningOffersDestroy: (...args: unknown[]) => api.offersDestroy(...args),
  commissioningBulkSendOffersViaEmailCreate: (...args: unknown[]) =>
    api.bulkSend(...args),
  commissioningBulkFinalizeCreate: (...args: unknown[]) =>
    api.bulkFinalize(...args),
  commissioningBulkCopyOffersToNextWeekCreate: (...args: unknown[]) =>
    api.copyToNextWeek(...args),
  commissioningBulkCopyOffersToOfferGroupCreate: (...args: unknown[]) =>
    api.copyToOfferGroup(...args),
}));

vi.mock("@shared/api/generated/tenants/tenants", () => ({
  tenantsSettingsUpdateCurrentSettingsUpdate: (...args: unknown[]) =>
    api.updateTenantSettings(...args),
}));

vi.mock("@shared/selectors", () => ({
  WeekSelector: ({
    selectedYear,
    setSelectedYear,
  }: {
    selectedYear: number;
    setSelectedYear: (year: number) => void;
  }) => (
    <button type="button" onClick={() => setSelectedYear(selectedYear - 1)}>
      previous year
    </button>
  ),
}));

vi.mock("@features/commissioning/selectors/OfferGroupSelector", () => ({
  default: ({
    setSelectedOfferGroup,
  }: {
    setSelectedOfferGroup: (id: string) => void;
  }) => (
    <div>
      <button type="button" onClick={() => setSelectedOfferGroup("og-1")}>
        pick Restaurants
      </button>
    </div>
  ),
}));

vi.mock("@features/commissioning/components/AddShareArticleEntry", () => ({
  default: ({ disabled }: { disabled?: boolean }) => (
    <button type="button" disabled={disabled}>
      add share article
    </button>
  ),
}));

vi.mock("@features/commissioning/components/OfferSendingStatusTable", () => ({
  default: () => <div data-testid="sending-status-table" />,
}));

vi.mock("@shared/ui/JobProgressDrawer", () => ({
  JobProgressDrawer: ({
    jobId,
    onClose,
  }: {
    jobId: string | null;
    onClose: () => void;
  }) =>
    jobId ? (
      <div data-testid="job-drawer">
        {jobId}
        <button type="button" onClick={onClose}>
          close drawer
        </button>
      </div>
    ) : null,
}));

const pdfProps = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }));
vi.mock("@features/commissioning/pdfs/forResellers/OfferPDFGenerator", () => ({
  default: (props: Record<string, unknown>) => {
    pdfProps.last = props;
    return <button type="button">{String(props.buttonText)}</button>;
  },
}));

// The offers grid's props from its latest render.
const table = vi.hoisted(() => ({ props: null as unknown }));

vi.mock("@shared/tables", async () => {
  const { gatedByPermission, READ_ONLY_PERMISSION } = await import(
    "@shared/tables/tablePermissions"
  );
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  const leafColumns = (
    columns: EditableColumnConfig<TableRecord>[],
  ): EditableColumnConfig<TableRecord>[] =>
    columns.flatMap((column) =>
      column.children ? leafColumns(column.children) : [column],
    );
  return {
    gatedByPermission,
    READ_ONLY_PERMISSION,
    wrapApiFunctions,
    EditableTable: (props: EditableTableProps) => {
      table.props = props;
      const columns = leafColumns(props.columns).filter((c) => !c.hidden);
      return (
        <table
          data-testid="offers-grid"
          data-can-add={String(Boolean(props.permissions?.canAdd))}
          data-can-edit={String(Boolean(props.permissions?.canEdit))}
          data-can-delete={String(Boolean(props.permissions?.canDelete))}
        >
          <tbody>
            {(props.initialData ?? []).map((row, index) => {
              const record = { ...row, key: row.id } as TableRecord;
              return (
                <tr key={String(row.id)}>
                  {columns.map((column) => (
                    <td
                      key={column.key ?? column.dataIndex}
                      data-testid={`${String(row.id)}-${column.key ?? column.dataIndex}`}
                    >
                      {column.render
                        ? column.render(record[column.dataIndex], record, index)
                        : String(record[column.dataIndex] ?? "")}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      );
    },
  };
});

import Offers from "../Offers";

// ── Fixtures ────────────────────────────────────────────────────────────────

const YEAR = dayjs().isoWeekYear();
const WEEK = dayjs().isoWeek();

const SHARE_ARTICLES = [
  {
    id: "art-carrot",
    name: "Carrots",
    default_movement_unit: "KG",
    net_price_for_orders_kg_1: 2.4,
    net_price_for_orders_kg_2: 2.2,
    net_price_for_orders_kg_3: 2.0,
  },
];

const OFFER_GROUPS = [
  {
    id: "og-1",
    number: 1,
    name: "Restaurants",
    reseller_names: "Bistro Blau, Cafe Gruen",
    rabatt_price_tier_2: 10,
    rabatt_price_tier_3: 20,
  },
  { id: "og-2", number: 2, name: "Shops", reseller_names: "Corner Shop" },
];

function makeOffer(overrides: Record<string, unknown> = {}) {
  return {
    id: "offer-1",
    year: YEAR,
    delivery_week: WEEK,
    offer_group: "og-1",
    share_article: "art-carrot",
    share_article_name: "Carrots",
    unit: "KG",
    size: "M",
    amount_per_pu: "5.00",
    amount: "20",
    amount_ordered: "0.000",
    price_1: "2.40",
    price_2: "2.20",
    price_3: "2.00",
    is_finalized: true,
    ...overrides,
  };
}

const SENDING_STATUS = [
  {
    id: "res-1",
    name: "Bistro Blau",
    address: "Lindenweg 2",
    zip_code: "10115",
    city: "Berlin",
    uid: "DE111",
    sent: false,
    sent_at: null,
  },
  {
    id: "res-2",
    name: "Cafe Gruen",
    address: "Ufer 9",
    zip_code: "10117",
    city: "Berlin",
    uid: null,
    sent: false,
    sent_at: null,
  },
  {
    id: "res-3",
    name: "Hotel Rot",
    address: "Ring 1",
    zip_code: "10119",
    city: "Berlin",
    uid: null,
    sent: true,
    sent_at: "2026-09-28T09:00:00",
  },
];

const IDLE_QUERY = { data: undefined, isFetching: false };

// Stable result objects per test, like settled TanStack queries.
let offersResult: { data: unknown[]; isFetching: boolean };
let sendingStatusResult: { data: unknown[]; isFetching: boolean };

function setOffers(offers: Record<string, unknown>[]) {
  offersResult = { data: offers, isFetching: false };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderPage() {
  const client = makeQueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Offers />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { invalidateSpy };
}

async function pickOfferGroup() {
  await userEvent.click(screen.getByRole("button", { name: "pick Restaurants" }));
}

function grid(): EditableTableProps {
  if (!table.props) throw new Error("the offers grid never rendered");
  return table.props as EditableTableProps;
}

const offersKey = (year = YEAR, week = WEEK) => [
  "/api/commissioning/offers/",
  { year, delivery_week: week, offer_group: "og-1" },
];

beforeEach(() => {
  tenantState.values = {};
  tenantState.refreshTenant.mockReset().mockResolvedValue(undefined);
  authState.roles = ["office"];
  table.props = null;
  pdfProps.last = null;
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(notifyMock).forEach((fn) => fn.mockReset());
  setOffers([makeOffer(), makeOffer({ id: "offer-2", amount_ordered: "15.000" })]);
  sendingStatusResult = { data: SENDING_STATUS, isFetching: false };
  api.offersList.mockImplementation(
    (_params: unknown, options?: { query?: { enabled?: boolean } }) =>
      options?.query?.enabled === false ? IDLE_QUERY : offersResult,
  );
  api.sendingStatusList.mockImplementation(
    (_params: unknown, options?: { query?: { enabled?: boolean } }) =>
      options?.query?.enabled === false ? IDLE_QUERY : sendingStatusResult,
  );
  api.offerGroupsList.mockReturnValue({
    data: OFFER_GROUPS,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

// ── Mount ───────────────────────────────────────────────────────────────────

describe("Offers mount", () => {
  it("does not re-render in a loop on mount", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>{profiler.wrap(<Offers />, "offers")}</MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByTestId("offers-grid");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });

  it("asks for an offer group first when the tenant has none", () => {
    api.offerGroupsList.mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderPage();

    expect(
      screen.getByText(/commissioning\.no_offer_groups_message/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "commissioning.manage_offer_groups" }),
    ).toHaveAttribute("href", "/commissioning/list-offer-groups");
    expect(screen.queryByTestId("offers-grid")).not.toBeInTheDocument();
  });

  it("loads no offers until an offer group is picked, then the group's offers of the current week", async () => {
    renderPage();

    expect(api.offersList).toHaveBeenLastCalledWith(expect.anything(), {
      query: { enabled: false },
    });
    expect(grid().initialData).toEqual([]);

    await pickOfferGroup();

    expect(api.offersList).toHaveBeenLastCalledWith(
      { year: YEAR, delivery_week: WEEK, offer_group: "og-1" },
      { query: { enabled: true } },
    );
    expect(api.sendingStatusList).toHaveBeenLastCalledWith(
      { year: YEAR, delivery_week: WEEK, offer_group: "og-1" },
      { query: { enabled: true } },
    );
    expect(grid().initialData).toHaveLength(2);
    expect(screen.getByText("Bistro Blau, Cafe Gruen")).toBeInTheDocument();
  });
});

// ── Creating offers ─────────────────────────────────────────────────────────

describe("Offers creation", () => {
  it("creates the offers of the week for every offer group and refreshes the list", async () => {
    api.createOffers.mockResolvedValue({ success: true, created_count: 12 });
    const { invalidateSpy } = renderPage();
    await pickOfferGroup();

    await userEvent.click(
      screen.getByRole("button", { name: /commissioning\.create_offer/ }),
    );

    await waitFor(() =>
      expect(notifyMock.success).toHaveBeenCalledWith('commissioning.offers_created {"created":12}'),
    );
    // No offer group: creation always covers every group.
    expect(api.createOffers).toHaveBeenCalledWith({
      year: YEAR,
      delivery_week: WEEK,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: offersKey() });
  });

  it.each([
    ["No offer groups found", "commissioning.no_offer_groups_found"],
    ["No offers created", "commissioning.no_offers_created"],
    ["Nothing to copy from last week", "Nothing to copy from last week"],
    [undefined, "commissioning.no_offers_created"],
  ])(
    "explains an empty result (%s) as %s",
    async (message, expected) => {
      api.createOffers.mockResolvedValue({ success: false, message });
      renderPage();

      await userEvent.click(
        screen.getByRole("button", { name: /commissioning\.create_offer/ }),
      );

      await waitFor(() => expect(notifyMock.info).toHaveBeenCalledWith(expected));
      expect(notifyMock.success).not.toHaveBeenCalled();
    },
  );

  it("shows the server's message when creating offers fails", async () => {
    api.createOffers.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: { code: "validation_error", message: "Week is locked." },
      },
    });
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /commissioning\.create_offer/ }),
    );

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith("Week is locked."),
    );
  });
});

// ── Editing and permissions ─────────────────────────────────────────────────

describe("Offers editing", () => {
  it("lets the office edit the current week but not delete an offer that was already ordered", async () => {
    renderPage();
    await pickOfferGroup();

    const offersGrid = screen.getByTestId("offers-grid");
    expect(offersGrid).toHaveAttribute("data-can-add", "true");
    expect(offersGrid).toHaveAttribute("data-can-edit", "true");
    expect(offersGrid).toHaveAttribute("data-can-delete", "true");
    const canDeleteRecord = grid().permissions?.canDeleteRecord as (
      record: TableRecord,
    ) => boolean;
    expect(canDeleteRecord({ key: "offer-1", amount_ordered: "0.000" })).toBe(true);
    expect(canDeleteRecord({ key: "offer-2", amount_ordered: "15.000" })).toBe(false);
  });

  it("shows and takes an available amount in PU fractions", async () => {
    setOffers([makeOffer({ amount: "2.500" })]);
    renderPage();
    await pickOfferGroup();
    expect(screen.getByTestId("offer-1-amount")).toHaveTextContent("2,5 commissioning.pu");
    expect(grid().columns.find((c) => c.key === "amount")?.inputType).toBe("positive_decimal3");
  });

  it("keeps the offers read-only for a user without the office role", async () => {
    authState.roles = ["gardener"];
    renderPage();
    await pickOfferGroup();

    const offersGrid = screen.getByTestId("offers-grid");
    expect(offersGrid).toHaveAttribute("data-can-add", "false");
    expect(offersGrid).toHaveAttribute("data-can-edit", "false");
    expect(offersGrid).toHaveAttribute("data-can-delete", "false");
  });

  it("makes a past week read-only and blocks creating and sending offers", async () => {
    renderPage();
    await pickOfferGroup();

    await userEvent.click(screen.getByRole("button", { name: "previous year" }));

    expect(api.offersList).toHaveBeenLastCalledWith(
      { year: YEAR - 1, delivery_week: WEEK, offer_group: "og-1" },
      { query: { enabled: true } },
    );
    expect(screen.getByText("table.past_week_readonly")).toBeInTheDocument();
    expect(screen.getByTestId("offers-grid")).toHaveAttribute(
      "data-can-edit",
      "false",
    );
    expect(
      screen.getByRole("button", { name: /commissioning\.create_offer/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /commissioning\.send_offers_via_email/ }),
    ).toBeDisabled();
    expect(screen.queryByText("commissioning.for_selected")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "add share article" }),
    ).toBeDisabled();
  });

  it("stamps the week and the offer group onto a new offer and creates it through the generated client", async () => {
    api.offersCreate.mockResolvedValue({ id: "offer-9" });
    renderPage();
    await pickOfferGroup();

    const payload = grid().customSave!(
      { share_article: "art-carrot", unit: "KG", amount: 10 },
      { key: -1 },
    );
    await grid().apiFunctions!.create!(payload!);

    expect(api.offersCreate).toHaveBeenCalledWith({
      share_article: "art-carrot",
      unit: "KG",
      amount: 10,
      year: YEAR,
      delivery_week: WEEK,
      offer_group: "og-1",
    });
  });

  it("updates and deletes offers through the generated client", async () => {
    api.offersPartialUpdate.mockResolvedValue({ id: "offer-1" });
    api.offersDestroy.mockResolvedValue(undefined);
    renderPage();
    await pickOfferGroup();

    await grid().apiFunctions!.update!("offer-1", { price_1: "2.60" });
    await grid().apiFunctions!.delete!("offer-1");

    expect(api.offersPartialUpdate).toHaveBeenCalledWith("offer-1", {
      price_1: "2.60",
    });
    expect(api.offersDestroy).toHaveBeenCalledWith("offer-1");
  });

  it("seeds a new offer with size M", () => {
    renderPage();
    const form = { setFieldsValue: vi.fn() } as unknown as FormInstance;

    expect(grid().customEdit!({ key: -1 }, form)).toEqual({ key: -1, size: "M" });
    expect(form.setFieldsValue).toHaveBeenCalledWith({ size: "M" });
  });
});

// ── Prices ──────────────────────────────────────────────────────────────────

describe("Offers prices", () => {
  it("shows one price column per configured tier in the tenant's currency", async () => {
    tenantState.values = { used_tiers_for_offers: [1, 5, 10] };
    renderPage();
    await pickOfferGroup();

    expect(screen.getByTestId("offer-1-price_1")).toHaveTextContent("2,40 €");
    expect(screen.getByTestId("offer-1-price_2")).toHaveTextContent("2,20 €");
    expect(screen.getByTestId("offer-1-price_3")).toHaveTextContent("2,00 €");
  });

  it("shows only the base price column for a single-tier tenant", async () => {
    renderPage();
    await pickOfferGroup();

    expect(screen.getByTestId("offer-1-price_1")).toBeInTheDocument();
    expect(screen.queryByTestId("offer-1-price_2")).not.toBeInTheDocument();
  });

  it("highlights a price that differs from the article's default price", async () => {
    setOffers([makeOffer({ price_1: "2.90" })]);
    renderPage();
    await pickOfferGroup();

    const changed = within(screen.getByTestId("offer-1-price_1")).getByText("2,90 €");
    expect(changed).toHaveStyle({ fontWeight: "bold" });
  });

  it("does not highlight a price that matches the article's default price", async () => {
    renderPage();
    await pickOfferGroup();

    const unchanged = within(screen.getByTestId("offer-1-price_1")).getByText("2,40 €");
    expect(unchanged).toHaveStyle({ fontWeight: "normal" });
  });

  it("locks the prices of a finalized offer", async () => {
    tenantState.values = { used_tiers_for_offers: [1, 5, 10] };
    renderPage();
    await pickOfferGroup();

    const priceColumn = (dataIndex: string) =>
      grid()
        .columns.flatMap((column) => column.children ?? [column])
        .find((column) => column.dataIndex === dataIndex)!;
    const disabled = priceColumn("price_2").disabled as (
      record: TableRecord,
    ) => boolean;
    expect(disabled({ key: "offer-1", is_finalized: true })).toBe(true);
    expect(disabled({ key: "offer-1", is_finalized: false })).toBe(false);
  });

  describe("tier prices derived from the base price", () => {
    // The row's form: what the office typed or the auto-fill wrote.
    const fakeForm = (values: Record<string, unknown>) => ({
      values,
      getFieldValue: (name: string) => values[name],
      setFieldValue: vi.fn((name: string, value: unknown) => {
        values[name] = value;
      }),
    });

    const basePriceColumn = async () => {
      tenantState.values = { used_tiers_for_offers: [1, 5, 10] };
      renderPage();
      await pickOfferGroup();
      const column = grid()
        .columns.flatMap((each) => each.children ?? [each])
        .find((each) => each.dataIndex === "price_1")!;
      return (
        typed: string,
        record: TableRecord,
        form: ReturnType<typeof fakeForm>,
      ) =>
        column.onFieldChange!(
          typed,
          record,
          form as unknown as FormInstance,
          "price_1",
        );
    };

    it("fills an empty lower tier from the group's discount and keeps a filled one", async () => {
      const typeBasePrice = await basePriceColumn();
      const form = fakeForm({ price_2: null, price_3: "1.95" });

      typeBasePrice("3.00", { key: -1 }, form);

      // 10 % off 3.00 for tier 2; tier 3 already has a price and stays.
      expect(form.values.price_2).toBe("2.70");
      expect(form.values.price_3).toBe("1.95");
    });

    it("keeps following the base price while the office types it", async () => {
      const typeBasePrice = await basePriceColumn();
      const form = fakeForm({});

      for (const typed of ["1", "12", "12.", "12.5", "12.50"]) {
        typeBasePrice(typed, { key: -1 }, form);
      }

      expect(form.values.price_2).toBe("11.25");
      expect(form.values.price_3).toBe("10.00");
    });

    it("reads a base price typed with a decimal comma", async () => {
      const typeBasePrice = await basePriceColumn();
      const form = fakeForm({});

      for (const typed of ["2", "2,", "2,9", "2,90"]) {
        typeBasePrice(typed, { key: -1 }, form);
      }

      expect(form.values.price_2).toBe("2.61");
      expect(form.values.price_3).toBe("2.32");
    });

    it("moves a saved tier price that was derived from the saved base price", async () => {
      const typeBasePrice = await basePriceColumn();
      const saved = { key: "offer-9", price_1: "2.00" };
      const form = fakeForm({ price_2: "1.80", price_3: "1.60" });

      typeBasePrice("3", saved, form);

      expect(form.values.price_2).toBe("2.70");
      expect(form.values.price_3).toBe("2.40");
    });

    it("keeps a tier price the office typed", async () => {
      const typeBasePrice = await basePriceColumn();
      const form = fakeForm({});
      typeBasePrice("3", { key: -1 }, form);
      form.values.price_2 = "2.50";

      typeBasePrice("3.5", { key: -1 }, form);

      expect(form.values.price_2).toBe("2.50");
      expect(form.values.price_3).toBe("2.80");
    });
  });

  it("saves the per-PU price switch as a tenant setting", async () => {
    api.updateTenantSettings.mockResolvedValue({});
    renderPage();

    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "settings.reseller.offer_prices_are_per_pu",
      }),
    );

    await waitFor(() =>
      expect(api.updateTenantSettings).toHaveBeenCalledWith({
        settings: { offer_prices_are_per_pu: true },
      }),
    );
    expect(tenantState.refreshTenant).toHaveBeenCalled();
  });
});

// ── Bulk actions ────────────────────────────────────────────────────────────

describe("Offers bulk actions", () => {
  async function selectBothOffers() {
    await pickOfferGroup();
    act(() => grid().onSelectedRowsChange?.(["offer-1", "offer-2"], []));
  }

  it("keeps the bulk actions disabled until offers are selected", async () => {
    renderPage();
    await pickOfferGroup();

    expect(
      screen.getByRole("button", { name: "commissioning.finalize" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "commissioning.copy_selected_to_next_week",
      }),
    ).toBeDisabled();
  });

  it("finalizes the selected offers, refreshes the list and clears the selection", async () => {
    api.bulkFinalize.mockResolvedValue({ results: [] });
    const { invalidateSpy } = renderPage();
    await selectBothOffers();

    await userEvent.click(
      screen.getByRole("button", { name: "commissioning.finalize" }),
    );

    await waitFor(() =>
      expect(api.bulkFinalize).toHaveBeenCalledWith({
        ids: ["offer-1", "offer-2"],
        model: "offer",
        app_label: "commissioning",
      }),
    );
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: offersKey() }),
    );
    expect(grid().selectedRowKeys).toEqual([]);
  });

  it("copies the selected offers to next week after confirmation", async () => {
    api.copyToNextWeek.mockResolvedValue({
      total_requested: 2, total_copied: 2, skipped_count: 0, copied_offers: ["c-1", "c-2"],
    });
    renderPage();
    await selectBothOffers();

    await userEvent.click(
      screen.getByRole("button", { name: "commissioning.copy_selected_to_next_week" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "common.yes" }));

    await waitFor(() =>
      expect(api.copyToNextWeek).toHaveBeenCalledWith({ ids: ["offer-1", "offer-2"] }),
    );
    expect(notifyMock.success).toHaveBeenCalledWith(
      'commissioning.copied_to_next_week {"count":2,"skipped":0}',
    );
  });

  it("copies the selected offers into each other offer group of the week", async () => {
    api.copyToOfferGroup.mockResolvedValue({
      total_requested: 2, total_copied: 1, skipped_count: 1, copied_offers: ["c-1"],
    });
    renderPage();
    await selectBothOffers();

    // Only the other group is offered as a copy target.
    await userEvent.click(
      screen.getByRole("button", { name: /^commissioning\.copy_to_offer_group .*"Shops"/ }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "common.yes" }));

    await waitFor(() =>
      expect(api.copyToOfferGroup).toHaveBeenCalledWith({
        ids: ["offer-1", "offer-2"], year: YEAR, delivery_week: WEEK, offer_group: "og-2",
      }),
    );
    expect(notifyMock.success).toHaveBeenCalledWith(
      'commissioning.copied_to_offer_group_some_skipped {"count":1,"skipped":1,"offerGroup":"Shops"}',
    );
  });
});

// ── Sending ─────────────────────────────────────────────────────────────────

describe("Offers sending", () => {
  it("keeps sending and the PDF unavailable until every offer of the group is finalized", async () => {
    setOffers([makeOffer(), makeOffer({ id: "offer-2", is_finalized: false })]);
    renderPage();
    await pickOfferGroup();

    expect(
      screen.getByRole("button", { name: /commissioning\.send_offers_via_email/ }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "commissioning.download_offers_pdf" }),
    ).not.toBeInTheDocument();
  });

  it("offers the PDF of a fully finalized group with the per-PU setting and one copy per reseller", async () => {
    tenantState.values = { offer_prices_are_per_pu: true };
    renderPage();
    await pickOfferGroup();

    await screen.findByRole("button", {
      name: "commissioning.download_offers_pdf",
    });
    expect(pdfProps.last).toMatchObject({
      year: YEAR,
      delivery_week: WEEK,
      offerGroupId: "og-1",
      pricesPerPU: true,
    });
    expect(pdfProps.last?.resellers).toEqual([
      expect.objectContaining({
        reseller_name: "Bistro Blau",
        reseller_address: "Lindenweg 2",
        reseller_zip: "10115",
        reseller_city: "Berlin",
        reseller_uid: "DE111",
      }),
      expect.objectContaining({ reseller_name: "Cafe Gruen", reseller_uid: undefined }),
      expect.objectContaining({ reseller_name: "Hotel Rot" }),
    ]);
  });

  it("sends the offers to the chosen resellers that have not had them yet and follows the job", async () => {
    api.bulkSend.mockResolvedValue({ job_id: "job-7", kind: "offers", status: "queued" });
    const { invalidateSpy } = renderPage();
    await pickOfferGroup();

    await userEvent.click(
      screen.getByRole("button", { name: /commissioning\.send_offers_via_email/ }),
    );
    const dialog = await screen.findByRole("dialog");
    // The reseller who already has the offers is listed apart, not selectable.
    expect(within(dialog).getByText("Hotel Rot")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Cafe Gruen" }));
    await userEvent.click(
      within(dialog).getByRole("button", { name: /commissioning\.send \(1\)/ }),
    );

    await waitFor(() =>
      expect(api.bulkSend).toHaveBeenCalledWith({
        reseller_ids: ["res-1"],
        year: YEAR,
        delivery_week: WEEK,
        offer_group: "og-1",
      }),
    );
    expect(notifyMock.info).toHaveBeenCalledWith(
      "commissioning.offers_send_queued",
    );
    expect(await screen.findByTestId("job-drawer")).toHaveTextContent("job-7");

    await userEvent.click(screen.getByRole("button", { name: "close drawer" }));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: [
        "/api/commissioning/offer_sending_status/",
        { year: YEAR, delivery_week: WEEK, offer_group: "og-1" },
      ],
    });
    expect(screen.queryByTestId("job-drawer")).not.toBeInTheDocument();
  });

  it("keeps the send dialog open and reports the error when sending fails", async () => {
    api.bulkSend.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: { code: "validation_error", message: "SMTP is not configured." },
      },
    });
    renderPage();
    await pickOfferGroup();

    await userEvent.click(
      screen.getByRole("button", { name: /commissioning\.send_offers_via_email/ }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: /commissioning\.send \(2\)/ }),
    );

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith("SMTP is not configured."),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByTestId("job-drawer")).not.toBeInTheDocument();
  });
});
