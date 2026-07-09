/**
 * Tier-4 seam test for ``useCustomerOrderColumns``.
 *
 * The hook builds the AntD column list for the customer-order grid:
 *   - 3 static columns (article, description, per-PU),
 *   - 0-N dynamic tier columns (one per active price tier),
 *   - 1 order column whose cell renders ``OrderAmountCell``.
 *
 * What we verify:
 *   - Column count matches active-tier inclusion / exclusion rules
 *   - Each column's ``render()`` produces the right text for the
 *     fallback / formatting branches the source code threads through
 *   - The order column wires ``isReadOnly`` into its cell background
 *     (and stubs ``OrderAmountCell`` so this test stays scoped to the
 *     column factory).
 *
 * Boundary mocks: every helper hook is replaced with a tiny synchronous
 * implementation so we can predict the rendered strings exactly.
 */

import { render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useCurrency", () => ({
  useCurrency: () => ({
    currencySymbol: "€",
    // Mirror the real formatCurrency for the suffix-currency (€) case so the
    // tier-price cell assertions ("1.50 €/KG") hold.
    formatCurrency: (n: number) => `${n.toFixed(2)} €`,
  }),
}));

vi.mock("@hooks/useNumberFormat", () => ({
  useNumberFormat: () => ({
    format: (n: number, d: number) => n.toFixed(d),
  }),
}));

vi.mock("@hooks/useUnitOptions", () => ({
  useUnitOptions: () => ({
    getUnitLabel: (u: string) => (u === "kg" ? "KG" : u),
  }),
}));

vi.mock("@hooks/useSizeOptions", () => ({
  useSizeOptions: () => ({
    getSizeLabel: (s: string) => (s === "L" ? "Large" : s),
  }),
}));

vi.mock("@features/customer/components/OrderAmountCell", () => ({
  default: ({ record }: { record: Record<string, unknown> }) => (
    <div data-testid="order-amount-cell" data-offer-id={record.id as string} />
  ),
}));

import { useCustomerOrderColumns } from "../useCustomerOrderColumns";
import type {
  CustomerOrderRow,
  CustomerOrderTableRow,
} from "@features/customer/types";

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Fixture helper: the column factory only reads a handful of row fields. */
const rows = (list: Partial<CustomerOrderRow>[]) =>
  list as CustomerOrderTableRow[];

type ColRender = (value: unknown, record: Record<string, unknown>) => unknown;
type ColumnDescriptor = {
  key: string;
  dataIndex?: string;
  title?: unknown;
  align?: string;
  width?: number;
  render?: ColRender;
  onCell?: (record?: Record<string, unknown>) => { style: React.CSSProperties };
  onHeaderCell?: () => { style: React.CSSProperties };
};

function makeParams(
  overrides: Partial<Parameters<typeof useCustomerOrderColumns>[0]> = {},
) {
  return {
    tableData: [] as CustomerOrderTableRow[],
    finalTiers: [1, 3, 5],
    orderAmounts: {} as Record<string, number>,
    editMode: false,
    saving: false,
    isReadOnly: false,
    orderLocked: false,
    stockErrors: {},
    onAmountChange: vi.fn(),
    onEnterEdit: vi.fn(),
    onCancelEdit: vi.fn(),
    onSaveAll: vi.fn(),
    ...overrides,
  };
}

/** Pull a column out of the result by ``key`` (TS narrowing helper). */
function findCol(cols: unknown[], key: string): ColumnDescriptor {
  const col = (cols as ColumnDescriptor[]).find((c) => c.key === key);
  if (!col) throw new Error(`column not found: ${key}`);
  return col;
}

/** Evaluate a column's ``render(value, record)`` to a string. */
function renderCellText(
  col: ColumnDescriptor,
  value: unknown,
  record: Record<string, unknown>,
): string {
  const { container } = render(<>{col.render!(value, record) as React.ReactNode}</>);
  return container.textContent ?? "";
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ── Column count & active-tier filtering ────────────────────────────────────

describe("active price tier filtering", () => {
  it("emits one tier column per non-zero price across tableData", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(
        makeParams({
          tableData: rows([
            { price_1: "1.50", price_2: "1.20", price_3: "1.00" },
          ]),
        }),
      ),
    );
    const keys = (result.current as unknown as ColumnDescriptor[]).map(
      (c) => c.key,
    );
    // 3 static + 3 tier + 1 order
    expect(keys).toEqual([
      "share_article_name",
      "description",
      "amount_per_pu",
      "price_1",
      "price_2",
      "price_3",
      "order_col",
    ]);
  });

  it("excludes a tier when every row's price for that tier is 0 or null", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(
        makeParams({
          tableData: rows([
            { price_1: "1.50", price_2: "0", price_3: null },
            { price_1: "1.50", price_2: "0", price_3: "0" },
          ]),
        }),
      ),
    );
    const keys = (result.current as unknown as ColumnDescriptor[]).map(
      (c) => c.key,
    );
    expect(keys).toContain("price_1");
    expect(keys).not.toContain("price_2");
    expect(keys).not.toContain("price_3");
    expect(keys).toContain("order_col");
  });

  it("emits zero tier columns when every row has zero prices everywhere", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(
        makeParams({
          tableData: rows([{ price_1: "0", price_2: "0", price_3: "0" }]),
        }),
      ),
    );
    const keys = (result.current as unknown as ColumnDescriptor[]).map(
      (c) => c.key,
    );
    expect(keys).toEqual([
      "share_article_name",
      "description",
      "amount_per_pu",
      "order_col",
    ]);
  });
});

// ── Article column ──────────────────────────────────────────────────────────

describe("article column render", () => {
  function articleCol(tableData: CustomerOrderTableRow[] = []) {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(makeParams({ tableData })),
    );
    return findCol(result.current as unknown[], "share_article_name");
  }

  it("renders just the name when size is missing", () => {
    const text = renderCellText(articleCol(), "Carrots", { id: "x" });
    expect(text).toBe("Carrots");
  });

  it('treats size "M" as the default and omits it from the suffix', () => {
    const text = renderCellText(articleCol(), "Carrots", {
      id: "x",
      size: "M",
    });
    expect(text).toBe("Carrots");
  });

  it("appends a size suffix when size is something other than M", () => {
    const text = renderCellText(articleCol(), "Carrots", {
      id: "x",
      size: "L",
    });
    // getSizeLabel mock turns "L" into "Large"
    expect(text).toBe("Carrots, Large");
  });

  it("falls back to record.share_article_name when offer_share_article_name is missing", () => {
    // The dataIndex value passed to render() is null here; the renderer
    // reaches into record.share_article_name as the fallback.
    const text = renderCellText(articleCol(), null, {
      id: "x",
      share_article_name: "Beets",
    });
    expect(text).toBe("Beets");
  });
});

// ── Description column ──────────────────────────────────────────────────────

describe("description column render", () => {
  function descCol() {
    const { result } = renderHook(() => useCustomerOrderColumns(makeParams()));
    return findCol(result.current as unknown[], "description");
  }

  it("joins sort + description with a space", () => {
    const text = renderCellText(descCol(), null, {
      sort: "Nantes",
      description: "long & sweet",
    });
    expect(text).toBe("Nantes long & sweet");
  });

  it("emits a dash when both sort and description are absent", () => {
    const text = renderCellText(descCol(), null, {});
    expect(text).toBe("-");
  });
});

// ── Per-PU column ───────────────────────────────────────────────────────────

describe("per-PU column render", () => {
  function perPuCol() {
    const { result } = renderHook(() => useCustomerOrderColumns(makeParams()));
    return findCol(result.current as unknown[], "amount_per_pu");
  }

  it("formats amount + unit + /pu", () => {
    const text = renderCellText(perPuCol(), "2", { unit: "kg" });
    // format(2,2) = "2.00", getUnitLabel("kg") = "KG", t("commissioning.pu") = key
    expect(text).toBe("2.00 KG/commissioning.pu");
  });

  it("emits a dash when amount_per_pu is missing", () => {
    const text = renderCellText(perPuCol(), "", {});
    expect(text).toBe("-");
  });
});

// ── Tier price columns ──────────────────────────────────────────────────────

describe("tier price columns", () => {
  function tier1Col() {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(
        makeParams({
          tableData: rows([{ price_1: "1.50" }]),
        }),
      ),
    );
    return findCol(result.current as unknown[], "price_1");
  }

  it("formats price + currency / unit", () => {
    const text = renderCellText(tier1Col(), "1.50", { unit: "kg" });
    expect(text).toBe("1.50 €/KG");
  });

  it("emits a dash when the price is 0 or missing on this row", () => {
    expect(renderCellText(tier1Col(), "0", { unit: "kg" })).toBe("-");
    expect(renderCellText(tier1Col(), null, { unit: "kg" })).toBe("-");
  });

  it("is right-aligned (downstream styling depends on this)", () => {
    expect(tier1Col().align).toBe("right");
  });
});

// ── Order column ────────────────────────────────────────────────────────────

describe("order column", () => {
  it("renders OrderAmountCell wired with the row record", () => {
    const { result } = renderHook(() => useCustomerOrderColumns(makeParams()));
    const orderCol = findCol(result.current as unknown[], "order_col");
    const { getByTestId } = render(
      <>{orderCol.render!(undefined, { id: "offer-7" }) as React.ReactNode}</>,
    );
    const cell = getByTestId("order-amount-cell");
    expect(cell.getAttribute("data-offer-id")).toBe("offer-7");
  });

  it("paints the cell green when isReadOnly is false (editable)", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(makeParams({ isReadOnly: false })),
    );
    const orderCol = findCol(result.current as unknown[], "order_col");
    expect(orderCol.onCell!().style.backgroundColor).toBe("#e6f7e6");
    expect(orderCol.onHeaderCell!().style.backgroundColor).toBe("#e6f7e6");
  });

  it("paints the cell subtle when isReadOnly is true", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(makeParams({ isReadOnly: true })),
    );
    const orderCol = findCol(result.current as unknown[], "order_col");
    expect(orderCol.onCell!().style.backgroundColor).toBe(
      "var(--color-bg-subtle)",
    );
  });

  it("keeps a fixed 260px width and centered alignment", () => {
    const { result } = renderHook(() => useCustomerOrderColumns(makeParams()));
    const orderCol = findCol(result.current as unknown[], "order_col");
    expect(orderCol.width).toBe(260);
    expect(orderCol.align).toBe("center");
  });

  it("header shows the Aktualisieren toggle in view mode and enters edit on click", async () => {
    const onEnterEdit = vi.fn();
    const { result } = renderHook(() =>
      useCustomerOrderColumns(makeParams({ editMode: false, onEnterEdit })),
    );
    const orderCol = findCol(result.current as unknown[], "order_col");
    render(<>{orderCol.title as React.ReactNode}</>);

    // The icon (EditOutlined, aria-label "edit") joins the button's accessible
    // name, so match the label text as a substring.
    const btn = screen.getByRole("button", { name: /customer\.update/ });
    expect(
      screen.queryByRole("button", { name: "common.save" }),
    ).not.toBeInTheDocument();
    await userEvent.click(btn);
    expect(onEnterEdit).toHaveBeenCalledTimes(1);
  });

  it("header shows Save + Cancel in edit mode and wires them to the bulk handlers", async () => {
    const onSaveAll = vi.fn();
    const onCancelEdit = vi.fn();
    const tableData = rows([{ id: "offer-1" }, { id: "offer-2" }]);
    const { result } = renderHook(() =>
      useCustomerOrderColumns(
        makeParams({ editMode: true, tableData, onSaveAll, onCancelEdit }),
      ),
    );
    const orderCol = findCol(result.current as unknown[], "order_col");
    render(<>{orderCol.title as React.ReactNode}</>);

    await userEvent.click(screen.getByRole("button", { name: "common.save" }));
    expect(onSaveAll).toHaveBeenCalledWith(tableData);
    await userEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    expect(onCancelEdit).toHaveBeenCalledTimes(1);
  });

  it("hides the edit toggle entirely when the order is locked", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(makeParams({ orderLocked: true })),
    );
    const orderCol = findCol(result.current as unknown[], "order_col");
    render(<>{orderCol.title as React.ReactNode}</>);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("hides the edit toggle when the week is read-only", () => {
    const { result } = renderHook(() =>
      useCustomerOrderColumns(makeParams({ isReadOnly: true })),
    );
    const orderCol = findCol(result.current as unknown[], "order_col");
    render(<>{orderCol.title as React.ReactNode}</>);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
