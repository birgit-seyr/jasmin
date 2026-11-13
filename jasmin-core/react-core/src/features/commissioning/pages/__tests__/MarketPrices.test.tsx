/**
 * MarketPrices: one week's PLU prices, the copy into the next week, the scale
 * export, the price and order list PDFs and the member list. The generated
 * client is the boundary; the grid is a stub that renders each row through the
 * page's columns and keeps the props it got, and the PDF buttons keep the
 * groups they would print.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import dayjs from "dayjs";
import isoWeek from "dayjs/plugin/isoWeek";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EditableColumnConfig,
  EditableTableProps,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

dayjs.extend(isoWeek);

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

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({});
  return { useTenant: () => tenant };
});

vi.mock("@hooks/configuration/useCurrency", () => ({
  useCurrency: () => ({
    currencyCode: "EUR",
    currencySymbol: "€",
    formatCurrency: (amount: number) => `${amount.toFixed(2)} €`,
  }),
}));

// ``useRoles`` is real; it reads the roles of the logged-in user from here.
const authState = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: authState.roles } }),
}));

const { notifyMock, downloadBlobMock, api } = vi.hoisted(() => ({
  notifyMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  downloadBlobMock: vi.fn(),
  api: {
    pricesList: vi.fn(),
    copyToNextWeek: vi.fn(),
    setActive: vi.fn(),
    scaleExport: vi.fn(),
  },
}));
vi.mock("@shared/utils/notify", () => ({ default: notifyMock }));
vi.mock("@shared/utils/downloadBlob", () => ({ downloadBlob: downloadBlobMock }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => [
    "/api/commissioning/market_prices/",
    ...(params ? [params] : []),
  ];
  return {
    useCommissioningMarketPricesList: (params: unknown) =>
      useQuery({ queryKey: queryKey(params), queryFn: async () => api.pricesList(params) }),
    getCommissioningMarketPricesListQueryKey: queryKey,
    useCommissioningMarketArticlesList: () => ({
      data: [
        { id: "plu-110", plu_number: 110, name: "Boskoop apple", unit: "KG", product_group: "group-4" },
        { id: "plu-101", plu_number: 101, name: "Elstar apple", unit: "KG", product_group: "group-4" },
        { id: "plu-102", plu_number: 102, name: "Topaz apple", unit: "KG", product_group: "group-4" },
        { id: "plu-300", plu_number: 300, name: "Rye bread", unit: "PCS", product_group: null },
        { id: "plu-205", plu_number: 205, name: "Leek", unit: "KG", product_group: "group-5" },
        { id: "plu-701", plu_number: 701, name: "Forest honey", unit: "PCS", product_group: "group-7" },
      ],
      isLoading: false,
    }),
    useCommissioningMarketProductGroupsList: (params?: { is_active?: boolean }) => {
      const groups = [
        { id: "group-5", number: 5, name: "Roots", is_active: true },
        { id: "group-4", number: 4, name: "Apples", is_active: true },
        { id: "group-7", number: 7, name: "Honey", is_active: false },
      ];
      return {
        data: params?.is_active ? groups.filter((group) => group.is_active) : groups,
        isLoading: false,
      };
    },
    getCommissioningMembersListQueryOptions: (params: unknown) => ({
      queryKey: ["/api/commissioning/members/", params],
      queryFn: async () => [],
    }),
    commissioningMarketPricesCreate: vi.fn(),
    commissioningMarketPricesPartialUpdate: vi.fn(),
    commissioningMarketPricesDestroy: vi.fn(),
    commissioningMarketPricesBulkCopyToNextWeekCreate: (...args: unknown[]) =>
      api.copyToNextWeek(...args),
    commissioningMarketPricesBulkSetActiveCreate: (...args: unknown[]) =>
      api.setActive(...args),
    commissioningMarketPricesScaleExportRetrieve: (...args: unknown[]) =>
      api.scaleExport(...args),
  };
});

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

const { pdfProps, orderPdfProps } = vi.hoisted(() => ({
  pdfProps: { last: null as Record<string, unknown> | null },
  orderPdfProps: { last: null as Record<string, unknown> | null },
}));
vi.mock("@features/commissioning/pdfs", () => ({
  MarketPriceListPDFGenerator: (props: Record<string, unknown>) => {
    pdfProps.last = props;
    return <button type="button">{String(props.buttonText)}</button>;
  },
  MarketOrderListPDFGenerator: (props: Record<string, unknown>) => {
    orderPdfProps.last = props;
    return <button type="button">{String(props.buttonText)}</button>;
  },
  MarketMemberListPDFGenerator: (props: Record<string, unknown>) => (
    <button type="button">{String(props.buttonText)}</button>
  ),
}));

// The grid's props from its latest render.
const table = vi.hoisted(() => ({ props: null as unknown }));
vi.mock("@shared/tables", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/tables")>();
  return {
    ...actual,
    EditableTable: (props: EditableTableProps) => {
      table.props = props;
      const columns = (props.columns as EditableColumnConfig<TableRecord>[]).filter(
        (column) => !column.hidden,
      );
      return (
        <table
          data-testid="prices-grid"
          data-can-edit={String(Boolean(props.permissions?.canEdit))}
        >
          <tbody>
            {(props.initialData ?? []).map((row, index) => {
              const record = { ...row, key: row.id } as TableRecord;
              return (
                <tr key={String(row.id)} data-testid={`row-${String(row.id)}`}>
                  {columns.map((column) => (
                    <td key={column.key ?? column.dataIndex}>
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

import MarketPrices from "../MarketPrices";

// ── Fixtures ────────────────────────────────────────────────────────────────

const YEAR = dayjs().isoWeekYear();
const WEEK = dayjs().isoWeek();

function makePrice(overrides: Record<string, unknown> = {}) {
  return {
    id: "price-1",
    year: YEAR,
    delivery_week: WEEK,
    market_article: "plu-101",
    plu_number: 101,
    name: "Elstar apple",
    unit: "KG",
    size: "M",
    sort: "Elstar",
    product_group_number: 4,
    product_group_name: "Apples",
    gross_price: "3.49",
    previous_gross_price: "3.29",
    origin: "DE",
    previous_origin: "DE",
    is_changed: true,
    is_active: true,
    ...overrides,
  };
}

const UNCHANGED = makePrice({
  id: "price-2",
  market_article: "plu-102",
  plu_number: 102,
  name: "Topaz apple",
  gross_price: "2.99",
  previous_gross_price: "2.99",
  origin: null,
  is_changed: false,
});
const WITHOUT_GROUP = makePrice({
  id: "price-3",
  market_article: "plu-300",
  plu_number: 300,
  name: "Rye bread",
  unit: "PCS",
  product_group_number: null,
  product_group_name: null,
  origin: null,
});
const INACTIVE = makePrice({
  id: "price-4",
  market_article: "plu-205",
  plu_number: 205,
  is_active: false,
});

function grid() {
  return table.props as EditableTableProps;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MarketPrices />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  authState.roles = ["office"];
  table.props = null;
  pdfProps.last = null;
  orderPdfProps.last = null;
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(notifyMock).forEach((fn) => fn.mockReset());
  downloadBlobMock.mockReset();
  api.pricesList.mockResolvedValue([makePrice(), UNCHANGED, WITHOUT_GROUP, INACTIVE]);
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("MarketPrices", () => {
  it("does not re-render in a loop on mount", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={new QueryClient()}>
        {profiler.wrap(<MarketPrices />, "market-prices")}
      </QueryClientProvider>,
    );
    await screen.findByTestId("row-price-1");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });

  it("lists the week's prices, a changed one in bold beside last week's", async () => {
    renderPage();
    const changed = await screen.findByTestId("row-price-1");

    expect(api.pricesList).toHaveBeenCalledWith({ year: YEAR, delivery_week: WEEK });
    expect(within(changed).getByText("3.49 €").tagName).toBe("STRONG");
    expect(within(changed).getByText("3.29 €")).toBeInTheDocument();
    // The same price as last week, in plain type both times.
    const unchanged = screen.getByTestId("row-price-2");
    const prices = within(unchanged).getAllByText("2.99 €");
    expect(prices).toHaveLength(2);
    expect(prices.map((price) => price.tagName)).toEqual(["TD", "TD"]);
  });

  it("stamps a new price with the chosen week", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    const newRow = { key: -1 } as TableRecord;
    expect(
      grid().customSave?.({ market_article: "plu-101", gross_price: "1.00" }, newRow),
    ).toEqual({
      market_article: "plu-101",
      gross_price: "1.00",
      year: YEAR,
      delivery_week: WEEK,
    });
  });

  it("copies the selected prices to next week after confirmation", async () => {
    api.copyToNextWeek.mockResolvedValue({ total_requested: 2, total_copied: 1, skipped_count: 1 });
    renderPage();
    await screen.findByTestId("row-price-1");
    act(() => grid().onSelectedRowsChange?.(["price-1", "price-2"], []));

    await userEvent.click(
      screen.getByRole("button", { name: "commissioning.copy_selected_to_next_week" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "common.yes" }));

    await waitFor(() =>
      expect(api.copyToNextWeek).toHaveBeenCalledWith({ ids: ["price-1", "price-2"] }),
    );
    expect(notifyMock.success).toHaveBeenCalledWith(
      'commissioning.market_prices_copied_some_skipped {"count":1,"skipped":1}',
    );
  });

  it("takes the selected prices off sale and reloads the week", async () => {
    api.setActive.mockResolvedValue(undefined);
    renderPage();
    await screen.findByTestId("row-price-1");
    act(() => grid().onSelectedRowsChange?.(["price-1", "price-2"], []));

    await userEvent.click(
      screen.getByRole("button", { name: "commissioning.market_prices_deactivate" }),
    );

    await waitFor(() =>
      expect(api.setActive).toHaveBeenCalledWith({
        is_active: false,
        ids: ["price-1", "price-2"],
      }),
    );
    expect(notifyMock.success).toHaveBeenCalledWith(
      'commissioning.market_prices_deactivated {"count":2}',
    );
    await waitFor(() => expect(api.pricesList).toHaveBeenCalledTimes(2));
  });

  it("counts the active prices of each product group", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    expect(await screen.findByText("4 Apples: 2")).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.market_price_list_without_group: 1"),
    ).toBeInTheDocument();
  });

  it("prints only the changed prices when asked, and says so", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    await userEvent.click(
      screen.getByRole("checkbox", { name: "commissioning.market_price_list_changed_only" }),
    );

    await waitFor(() =>
      expect(pdfProps.last?.subtitle).toBe("commissioning.market_price_list_changed_only"),
    );
    const groups = pdfProps.last?.groups as { label: string; rows: { id: string }[] }[];
    expect(groups.map((group) => [group.label, group.rows.map((row) => row.id)])).toEqual([
      ["4 Apples", ["price-1"]],
      ["commissioning.market_price_list_without_group", ["price-3"]],
    ]);
  });

  it("prints only the picked product groups, a fruit list say", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    await userEvent.click(
      screen.getByRole("combobox", { name: "commissioning.market_price_list_groups" }),
    );
    await userEvent.click(await screen.findByText("4 Apples (2)"));

    await waitFor(() => expect(pdfProps.last?.subtitle).toBe("4 Apples"));
    const groups = pdfProps.last?.groups as { label: string }[];
    expect(groups.map((group) => group.label)).toEqual(["4 Apples"]);
    // The order list follows the same choice.
    expect(orderPdfProps.last?.subtitle).toBe("4 Apples");
    const orderGroups = orderPdfProps.last?.groups as { label: string }[];
    expect(orderGroups.map((group) => group.label)).toEqual(["4 Apples"]);
  });

  it("offers every group of either list, counted by its active prices", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    await userEvent.click(
      screen.getByRole("combobox", { name: "commissioning.market_price_list_groups" }),
    );

    expect(await screen.findByText("4 Apples (2)")).toBeInTheDocument();
    expect(screen.getByText("5 Roots (0)")).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.market_price_list_without_group (1)"),
    ).toBeInTheDocument();
  });

  it("puts every active PLU on the order list, with the week's price where it has one", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    await waitFor(() => expect(orderPdfProps.last?.groups).toBeTruthy());
    const kg = "commissioning.units.kg";
    expect(orderPdfProps.last?.groups).toEqual([
      {
        label: "4 Apples",
        rows: [
          { id: "plu-101", plu_number: 101, name: "Elstar apple DE", unit_label: kg, price_text: "3.49 €" },
          { id: "plu-102", plu_number: 102, name: "Topaz apple", unit_label: kg, price_text: "2.99 €" },
          { id: "plu-110", plu_number: 110, name: "Boskoop apple", unit_label: kg, price_text: "" },
        ],
      },
      {
        label: "5 Roots",
        // Off sale this week, but still to count and order.
        rows: [
          { id: "plu-205", plu_number: 205, name: "Leek DE", unit_label: kg, price_text: "3.49 €" },
        ],
      },
      {
        // A group switched off still names the PLUs filed under it.
        label: "7 Honey",
        rows: [
          {
            id: "plu-701",
            plu_number: 701,
            name: "Forest honey",
            unit_label: "commissioning.units.pcs",
            price_text: "",
          },
        ],
      },
      {
        label: "commissioning.market_price_list_without_group",
        rows: [
          {
            id: "plu-300",
            plu_number: 300,
            name: "Rye bread",
            unit_label: "commissioning.units.pcs",
            price_text: "3.49 €",
          },
        ],
      },
    ]);
  });

  it("offers the office the member list in a row of its own", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    const memberList = screen.getByRole("button", {
      name: "commissioning.market_member_list_pdf",
    });
    const priceList = screen.getByRole("button", {
      name: "commissioning.market_price_list_pdf",
    });
    expect(memberList.parentElement).not.toBe(priceList.parentElement);
    expect(
      screen.getByRole("button", { name: "commissioning.market_order_list_pdf" })
        .parentElement,
    ).toBe(priceList.parentElement);
  });

  it("downloads the week's scale file", async () => {
    const file = new Blob(["xlsx"]);
    api.scaleExport.mockResolvedValue(file);
    renderPage();
    await screen.findByTestId("row-price-1");

    await userEvent.click(screen.getByRole("button", { name: "commissioning.scale_export" }));

    await waitFor(() => expect(downloadBlobMock).toHaveBeenCalledTimes(1));
    expect(api.scaleExport).toHaveBeenCalledWith({ year: YEAR, delivery_week: WEEK });
    const [blob, filename] = downloadBlobMock.mock.calls[0];
    expect(blob).toBe(file);
    expect(filename).toMatch(new RegExp(`^commissioning\\.scale_export_${YEAR}_.*\\.xlsx$`));
  });

  it("shows the server's reason when the scale file is refused", async () => {
    api.scaleExport.mockRejectedValue(
      Object.assign(new Error("Request failed with status code 409"), {
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            code: "scale_unit.unsupported",
            message: "The scale can't sell PLU 7 in its unit.",
            details: { plu_numbers: "7" },
          },
        },
      }),
    );
    renderPage();
    await screen.findByTestId("row-price-1");

    await userEvent.click(screen.getByRole("button", { name: "commissioning.scale_export" }));

    await waitFor(() =>
      // Translated by its code, with the PLUs the server named.
      expect(notifyMock.error).toHaveBeenCalledWith(expect.stringContaining("PLU 7 ")),
    );
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });

  it("prints the active prices by product group, those without a group last", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    await waitFor(() => expect(pdfProps.last?.groups).toBeTruthy());
    expect(pdfProps.last?.groups).toEqual([
      {
        label: "4 Apples",
        rows: [
          {
            id: "price-1",
            plu_number: 101,
            name: "Elstar apple DE",
            price_text: "3.49 €/commissioning.units.kg",
            is_changed: true,
          },
          {
            id: "price-2",
            plu_number: 102,
            name: "Topaz apple",
            price_text: "2.99 €/commissioning.units.kg",
            is_changed: false,
          },
        ],
      },
      {
        label: "commissioning.market_price_list_without_group",
        rows: [
          {
            id: "price-3",
            plu_number: 300,
            name: "Rye bread",
            price_text: "3.49 €/commissioning.units.pcs",
            is_changed: true,
          },
        ],
      },
    ]);
  });

  it("keeps a past week read-only", async () => {
    renderPage();
    await screen.findByTestId("row-price-1");

    await userEvent.click(screen.getByRole("button", { name: "previous year" }));

    await waitFor(() =>
      expect(screen.getByTestId("prices-grid")).toHaveAttribute("data-can-edit", "false"),
    );
    expect(
      screen.queryByRole("button", { name: "commissioning.copy_selected_to_next_week" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("table.past_week_readonly")).toBeInTheDocument();
  });

  it("lets staff read the prices and print the lists, but not change or export them", async () => {
    authState.roles = ["staff"];
    renderPage();
    await screen.findByTestId("row-price-1");

    expect(screen.getByTestId("prices-grid")).toHaveAttribute("data-can-edit", "false");
    expect(screen.getByRole("button", { name: "commissioning.market_price_list_pdf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "commissioning.market_order_list_pdf" })).toBeInTheDocument();
    // The member list is the office's: staff can't read the members.
    expect(
      screen.queryByRole("button", { name: "commissioning.market_member_list_pdf" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "commissioning.scale_export" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "commissioning.copy_selected_to_next_week" }),
    ).not.toBeInTheDocument();
  });
});
