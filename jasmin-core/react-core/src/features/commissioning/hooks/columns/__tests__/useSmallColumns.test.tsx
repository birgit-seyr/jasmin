/**
 * The small shared column hooks: the active flag, the seller select, the
 * tenant-gated organic status and the share-article prices button. Each is
 * read as EditableTable reads it — its config, and the cells its render draws
 * for realistic rows with and without the optional fields.
 */
import { render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Reseller } from "@shared/api/generated/models";
import type { EditableColumnConfig, SelectOption, TableRecord } from "@shared/tables/BasicEditableTable/types";

// One `t` for every render, as react-i18next keeps it.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const tenantState = vi.hoisted(() => ({ organicControlNumber: null as string | null }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const certified = makeUseTenantMock({ tenant: { organic_control_number: "DE-ÖKO-006" } });
  const uncertified = makeUseTenantMock({ tenant: { organic_control_number: null } });
  const blank = makeUseTenantMock({ tenant: { organic_control_number: "   " } });
  return {
    useTenant: () => {
      if (tenantState.organicControlNumber === null) return uncertified;
      return tenantState.organicControlNumber.trim() ? certified : blank;
    },
  };
});

// The resellers the generated client answers with; one array, as TanStack
// keeps the same data between renders.
const resellersApi = vi.hoisted(() => ({
  data: [] as Reseller[],
  params: [] as unknown[],
}));
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningResellersList: (params: unknown) => {
    resellersApi.params.push(params);
    return { data: resellersApi.data, isLoading: false, error: null, refetch: () => {} };
  },
}));

import { useIsActiveColumn } from "../useIsActiveColumn";
import { useOrganicStatusColumn } from "../useOrganicStatusColumn";
import { useSellerColumn } from "../useSellerColumn";
import { useShareArticlePriceColumn } from "../useShareArticlePriceColumn";

const row = (fields: Record<string, unknown> = {}): TableRecord => ({ key: "r1", id: "r1", ...fields });

const renderCell = (column: EditableColumnConfig<TableRecord>, value: unknown, record: TableRecord) =>
  render(<>{column.render?.(value, record, 0) as ReactNode}</>);

beforeEach(() => {
  tenantState.organicControlNumber = null;
  resellersApi.params = [];
  resellersApi.data = [
    { id: "rs-hof", company_name: "Hof Sonnenschein", name_for_member_pages: "Sonnenschein" } as Reseller,
    { id: "rs-anna", company_name: null, name_for_member_pages: null, first_name: "Anna", last_name: "Berger" } as Reseller,
    { id: "rs-markt", company_name: "", name_for_member_pages: "Markthalle" } as Reseller,
  ];
});

// ── useIsActiveColumn ───────────────────────────────────────────────────────

describe("useIsActiveColumn", () => {
  it("is an optional, sortable checkbox on is_active with an explained title", async () => {
    const { result } = renderHook(() => useIsActiveColumn());

    expect(result.current).toMatchObject({
      dataIndex: "is_active",
      key: "is_active",
      inputType: "checkbox",
      required: false,
      sortable: true,
    });
    render(<>{result.current.title}</>);
    expect(screen.getByText("commissioning.is_active")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "tooltip.is_active_description" })).toBeInTheDocument();
  });

  it("lets the caller's options win", () => {
    const options = { disabled: true, width: "6em", sortable: false };
    const { result } = renderHook(() => useIsActiveColumn(options));

    expect(result.current).toMatchObject({ dataIndex: "is_active", disabled: true, width: "6em", sortable: false });
  });

  it("hands back the same column on every render without options", () => {
    const { result, rerender } = renderHook(() => useIsActiveColumn());
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });
});

// ── useSellerColumn ─────────────────────────────────────────────────────────

describe("useSellerColumn", () => {
  it("asks for the active sellers only", () => {
    renderHook(() => useSellerColumn());

    expect(resellersApi.params[0]).toEqual({ is_active_seller: true, is_seller: true });
  });

  it("is an optional select writing the seller id and showing its name", () => {
    const { result } = renderHook(() => useSellerColumn());

    expect(result.current).toMatchObject({
      dataIndex: "seller_name",
      key: "seller_name",
      inputType: "select",
      required: false,
      width: "16em",
      foreignKey: { valueField: "seller", displayField: "seller_name" },
    });
    render(<>{result.current.title}</>);
    expect(screen.getByText("commissioning.seller")).toBeInTheDocument();
  });

  it("offers each seller by company name, else member-page name, else contact name", () => {
    const { result } = renderHook(() => useSellerColumn());

    expect((result.current.options as SelectOption[]).map((o) => [o.value, o.label])).toEqual([
      ["rs-hof", "Hof Sonnenschein"],
      ["rs-anna", "Anna Berger"],
      ["rs-markt", "Markthalle"],
    ]);
  });

  it("offers nothing while the sellers are loading", () => {
    resellersApi.data = undefined as unknown as Reseller[];
    const { result } = renderHook(() => useSellerColumn());

    expect(result.current.options).toEqual([]);
  });

  it("takes another title and lets overrides win", () => {
    const { result } = renderHook(() =>
      useSellerColumn({ titleKey: "commissioning.supplier", overrides: { width: "10em", sortable: true } }),
    );

    expect(result.current).toMatchObject({ width: "10em", sortable: true, dataIndex: "seller_name" });
    render(<>{result.current.title}</>);
    expect(screen.getByText("commissioning.supplier")).toBeInTheDocument();
  });

  it("hands back the same column on every render while the sellers stay the same", () => {
    const { result, rerender } = renderHook(() => useSellerColumn());
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });
});

// ── useOrganicStatusColumn ──────────────────────────────────────────────────

describe("useOrganicStatusColumn", () => {
  it.each([
    ["without a control number", null],
    ["with a blank control number", "   "],
  ])("has no column for a tenant %s", (_case, controlNumber) => {
    tenantState.organicControlNumber = controlNumber;

    const { result } = renderHook(() => useOrganicStatusColumn());

    expect(result.current).toEqual([]);
  });

  it("is an optional select of the three statuses for a certified tenant", () => {
    tenantState.organicControlNumber = "DE-ÖKO-006";

    const { result } = renderHook(() => useOrganicStatusColumn());

    expect(result.current).toHaveLength(1);
    const [column] = result.current;
    expect(column).toMatchObject({
      dataIndex: "organic_status",
      key: "organic_status",
      inputType: "select",
      required: false,
      sortable: true,
    });
    expect(column.options).toEqual([
      { value: "conventional", label: "commissioning.organic.conventional" },
      { value: "in_conversion", label: "commissioning.organic.in_conversion" },
      { value: "organic", label: "commissioning.organic.organic" },
    ]);
  });

  it.each([
    ["organic", "commissioning.organic.organic"],
    ["in_conversion", "commissioning.organic.in_conversion"],
    ["conventional", "commissioning.organic.conventional"],
    ["biodynamic", "biodynamic"],
    ["", "-"],
    [null, "-"],
    [undefined, "-"],
  ])("shows the status %s as %s", (value, shown) => {
    tenantState.organicControlNumber = "DE-ÖKO-006";
    const { result } = renderHook(() => useOrganicStatusColumn());

    renderCell(result.current[0], value, row({ organic_status: value }));

    expect(screen.getByText(shown)).toBeInTheDocument();
  });

  it("drops the column when the tenant loses its certification", () => {
    tenantState.organicControlNumber = "DE-ÖKO-006";
    const { result, rerender } = renderHook(() => useOrganicStatusColumn());
    expect(result.current).toHaveLength(1);

    tenantState.organicControlNumber = null;
    rerender();

    expect(result.current).toEqual([]);
  });
});

// ── useShareArticlePriceColumn ──────────────────────────────────────────────

describe("useShareArticlePriceColumn", () => {
  it("is a read-only, fixed action column without a title", () => {
    const { result } = renderHook(() => useShareArticlePriceColumn(vi.fn()));

    expect(result.current).toMatchObject({
      title: "",
      dataIndex: "actions",
      key: "actions",
      fixed: true,
      readOnly: true,
      disabled: true,
      align: "center",
    });
  });

  it("opens the prices of a saved article", async () => {
    const openPrices = vi.fn();
    const { result } = renderHook(() => useShareArticlePriceColumn(openPrices));
    const article = row({ key: "sa-carrots", id: "sa-carrots", name: "Karotten" });

    renderCell(result.current as EditableColumnConfig<TableRecord>, undefined, article);
    const button = screen.getByRole("button", { name: "commissioning.prices" });
    expect(button).toHaveAttribute("title", "commissioning.manage_prices");
    await userEvent.click(button);

    expect(openPrices).toHaveBeenCalledTimes(1);
    expect(openPrices).toHaveBeenCalledWith(article);
  });

  it.each([
    ["a new row", { key: -1, id: undefined }],
    ["a row without an id", { key: "tmp", id: "" }],
  ])("keeps the button disabled for %s", async (_case, fields) => {
    const openPrices = vi.fn();
    const { result } = renderHook(() => useShareArticlePriceColumn(openPrices));

    renderCell(result.current as EditableColumnConfig<TableRecord>, undefined, { ...fields } as TableRecord);
    const button = screen.getByRole("button", { name: "commissioning.prices" });
    expect(button).toBeDisabled();
    await userEvent.click(button);

    expect(openPrices).not.toHaveBeenCalled();
  });

  it("keeps the column while the handler stays the same", () => {
    const openPrices = vi.fn();
    const { result, rerender } = renderHook(() => useShareArticlePriceColumn(openPrices));
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });
});
