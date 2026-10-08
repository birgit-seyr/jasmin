/**
 * InvoiceModal: the office's editor for one reseller invoice.
 *
 * The modal owns the invoice fetch, the two grids' wiring (line items and
 * crates), the read-only gate for finalized invoices and non-office users,
 * and the money summary under the grids. EditableTable is replaced by a stub
 * that records the props each grid receives and renders every row through
 * the real column ``render`` functions, so cell money goes through the real
 * ``useCurrency`` / ``useNumberFormat`` formatting (de-DE, EUR); a test that
 * needs the table's own editing renders the crate grid through the real
 * EditableTable instead. The column hooks themselves are real; only the
 * generated API client is mocked.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { PointerEventsCheckLevel } from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  EditableColumnConfig,
  EditableTableProps,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

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

// Per-test tenant settings; anything unset falls back to the caller's default.
const tenantSettings = vi.hoisted(() => ({
  values: {} as Record<string, unknown>,
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the roles of the logged-in user from here.
const authState = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: authState.roles } }),
}));

// The real crate grid edits its rows inline.
vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const api = vi.hoisted(() => ({
  retrieve: vi.fn(),
  contentsCreate: vi.fn(),
  contentsPartialUpdate: vi.fn(),
  contentsDestroy: vi.fn(),
  cratesCreate: vi.fn(),
  cratesPartialUpdate: vi.fn(),
  cratesDestroy: vi.fn(),
}));

const CRATE_TYPES = [
  { id: "ct-small", name: "Small crate", short_name: "Small" },
  { id: "ct-large", name: "Large crate", short_name: "Large" },
];
const SHARE_ARTICLES = [
  { id: "art-carrot", name: "Carrots", default_movement_unit: "KG" },
  { id: "art-leek", name: "Leeks", default_movement_unit: "PCS" },
];

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningInvoicesRetrieve: (id: string, options: unknown) =>
    api.retrieve(id, options),
  getCommissioningInvoicesRetrieveQueryKey: (id: string) => [
    `/api/commissioning/invoices/${id}/`,
  ],
  commissioningInvoiceContentsCreate: (...args: unknown[]) =>
    api.contentsCreate(...args),
  commissioningInvoiceContentsPartialUpdate: (...args: unknown[]) =>
    api.contentsPartialUpdate(...args),
  commissioningInvoiceContentsDestroy: (...args: unknown[]) =>
    api.contentsDestroy(...args),
  commissioningCrateContentsInvoiceCreate: (...args: unknown[]) =>
    api.cratesCreate(...args),
  commissioningCrateContentsInvoicePartialUpdate: (...args: unknown[]) =>
    api.cratesPartialUpdate(...args),
  commissioningCrateContentsInvoiceDestroy: (...args: unknown[]) =>
    api.cratesDestroy(...args),
  // Option sources of the real crate / share-article column hooks.
  useCommissioningCratesList: () => ({
    data: CRATE_TYPES,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCommissioningShareArticlesList: () => ({
    data: SHARE_ARTICLES,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@features/commissioning/components/InvoiceSendStatus", () => ({
  default: ({ canSend }: { canSend: boolean }) => (
    <div data-testid="invoice-send-status" data-can-send={String(canSend)} />
  ),
}));

vi.mock("@features/commissioning/pdfs/forResellers/InvoicePDFGenerator", () => ({
  default: ({ buttonText }: { buttonText: string }) => (
    <button type="button">{buttonText}</button>
  ),
}));

// The props each grid received on its latest render. The crate grid is the one
// with a crate type column. With ``realCrates`` set, the crate grid is the
// real EditableTable.
type GridName = "lines" | "crates";
const grids = vi.hoisted(() => ({
  props: {} as Partial<Record<"lines" | "crates", unknown>>,
  realCrates: false,
}));

vi.mock("@shared/tables", async () => {
  const { gatedByPermission } = await import("@shared/tables/tablePermissions");
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  const { default: RealEditableTable } = await import(
    "@shared/tables/BasicEditableTable"
  );
  const leafColumns = (
    columns: EditableColumnConfig<TableRecord>[],
  ): EditableColumnConfig<TableRecord>[] =>
    columns.flatMap((column) =>
      column.children ? leafColumns(column.children) : [column],
    );
  return {
    gatedByPermission,
    wrapApiFunctions,
    EditableTable: (props: EditableTableProps) => {
      const name: GridName = props.columns.some(
        (column) => column.key === "crate_type_name",
      )
        ? "crates"
        : "lines";
      grids.props[name] = props;
      if (name === "crates" && grids.realCrates) {
        return <RealEditableTable {...props} />;
      }
      const columns = leafColumns(props.columns).filter((c) => !c.hidden);
      return (
        <table
          data-testid={`${name}-grid`}
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
                      data-testid={`${name}-${String(row.id)}-${column.key ?? column.dataIndex}`}
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

import InvoiceModal from "../InvoiceModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

// 2 kg carrots at 3.50 with 10 % off = 6.30 net at 7 % VAT.
const CARROT_LINE = {
  id: "line-1",
  invoice: "inv-1",
  share_article: "art-carrot",
  share_article_name: "Carrots",
  amount: "2.000",
  unit: "KG",
  size: "M",
  price_per_unit: "3.50",
  rabatt: 10,
  tax_rate: "7.00",
  line_netto: "6.30",
};

// 3 leeks at 1.00 = 3.00 net at 19 % VAT.
const LEEK_LINE = {
  id: "line-2",
  invoice: "inv-1",
  share_article: "art-leek",
  share_article_name: "Leeks",
  amount: "3.000",
  unit: "PCS",
  size: "M",
  price_per_unit: "1.00",
  rabatt: 0,
  tax_rate: "19.00",
  line_netto: "3.00",
};

// 4 small crates at 1.25 = 5.00 net at 19 % VAT.
const SMALL_CRATES = {
  id: "crate-1",
  crate_type: "ct-small",
  crate_type_name: "Small",
  amount: 4,
  price_per_unit: "1.25",
  rabatt: 0,
  line_netto: "5.00",
  tax_rate: 19,
};

// Small crates billed at two prices: two lines of one crate type, each named
// by a crate row of its own. 4 at 1.25 = 5.00 and 2 at 1.50 = 3.00 net.
const SMALL_CRATES_AT_125 = { ...SMALL_CRATES, id: "ct-small_row-1" };
const SMALL_CRATES_AT_150 = {
  ...SMALL_CRATES,
  id: "ct-small_row-7",
  amount: 2,
  price_per_unit: "1.50",
  line_netto: "3.00",
};

function makeInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: "inv-1",
    prefix: "RE",
    invoice_number: "2026-007",
    reseller_name: "Acme Grocers",
    invoice_date: "2026-09-28",
    corresponding_delivery_notes: "LS-2026-011, LS-2026-012",
    is_finalized: false,
    finalized_at: null,
    // The cached aggregates of an open invoice are stale by design: the
    // modal derives its summary from the rows instead.
    sum_netto: "999.00",
    sum_brutto: "999.99",
    tax_breakdown: [],
    line_items: [CARROT_LINE, LEEK_LINE],
    crate_items: [SMALL_CRATES],
    ...overrides,
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderModal({
  invoice = makeInvoice() as Record<string, unknown> | undefined,
  visible = true,
  onClose = vi.fn(),
} = {}) {
  // Same object on every call, like a settled TanStack query.
  api.retrieve.mockReturnValue({ data: invoice, isFetching: false });
  const client = makeQueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const modalFor = (invoiceId: string) => (
    <QueryClientProvider client={client}>
      <InvoiceModal visible={visible} invoiceId={invoiceId} onClose={onClose} />
    </QueryClientProvider>
  );
  const { rerender } = render(modalFor("inv-1"));
  /** Shows ``other`` in the open modal, as read again or as the next invoice picked. */
  const show = (other: Record<string, unknown>) => {
    api.retrieve.mockReturnValue({ data: other, isFetching: false });
    rerender(modalFor(other.id as string));
  };
  return { invalidateSpy, onClose, show };
}

function grid(name: GridName): EditableTableProps {
  const props = grids.props[name];
  if (!props) throw new Error(`the ${name} grid never rendered`);
  return props as EditableTableProps;
}

const INVOICE_QUERY_KEY = ["/api/commissioning/invoices/inv-1/"];

// ── The real crate grid ─────────────────────────────────────────────────────

const CRATE_TYPE = "commissioning.crate_type_name";
const AMOUNT = "commissioning.amount";
const PRICE = "commissioning.single_price";
const DISCOUNT = "commissioning.rabatt";

type User = ReturnType<typeof userEvent.setup>;

// Checking ``pointer-events`` before each click reads every ancestor's computed
// style, which the styles AntD injects make slow in jsdom; the crate grid's
// cells and buttons all take clicks.
const crateGridUser = () =>
  userEvent.setup({ delay: null, pointerEventsCheck: PointerEventsCheckLevel.Never });

const crateRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

function crateCell(row: HTMLElement, title: string): HTMLElement {
  const headers = Array.from(document.querySelectorAll(".ant-table-thead > tr > th"));
  const index = headers.findIndex((header) => header.textContent?.trim() === title);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No crate column titled ${title}`);
  return cell;
}

/** What each crate line shows under ``title``. */
const shownUnder = (title: string) =>
  crateRows().map((row) => crateCell(row, title).textContent);

/** The crate line open for editing: the one offering a save button. */
function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No crate line is being edited");
  return row;
}

/** Opens a crate line by clicking its cell under ``title``, ready for typing. */
async function openAt(user: User, row: HTMLElement, title: string) {
  await user.click(crateCell(row, title));
  const input = within(editingRow()).getByLabelText(title);
  await waitFor(() => expect(input).toHaveFocus());
  return input;
}

async function pickCrateType(user: User, label: string) {
  await user.click(
    within(editingRow()).getByRole("combobox", { name: CRATE_TYPE }),
  );
  const option = await waitFor(() => {
    const match = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => item.textContent === label);
    if (!match) throw new Error(`No crate type ${label} is offered`);
    return match;
  });
  await user.click(option);
}

const saveLine = (user: User) =>
  user.click(screen.getByRole("button", { name: "table.save" }));

beforeEach(() => {
  tenantSettings.values = {};
  authState.roles = ["office"];
  grids.props = {};
  grids.realCrates = false;
  Object.values(api).forEach((fn) => fn.mockReset());
});

// ── Fetching and header ─────────────────────────────────────────────────────

describe("InvoiceModal header", () => {
  it("does not fetch the invoice while the modal is closed", () => {
    renderModal({ visible: false });

    expect(api.retrieve).toHaveBeenCalledWith("inv-1", {
      query: { enabled: false },
    });
    expect(screen.queryByTestId("lines-grid")).not.toBeInTheDocument();
  });

  it("shows the invoice number, the reseller, the tenant-formatted date and the delivery notes it covers", () => {
    renderModal();

    expect(api.retrieve).toHaveBeenCalledWith("inv-1", {
      query: { enabled: true },
    });
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("commissioning.invoice_details RE-2026-007"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Acme Grocers")).toBeInTheDocument();
    expect(within(dialog).getByText("28.09.2026")).toBeInTheDocument();
    expect(
      within(dialog).getByText("LS-2026-011, LS-2026-012"),
    ).toBeInTheDocument();
  });

  it("calls onClose from the footer button", async () => {
    const { onClose } = renderModal();

    await userEvent.click(screen.getByRole("button", { name: "common.close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ── Line and crate cells ────────────────────────────────────────────────────

describe("InvoiceModal cells", () => {
  it("formats a line's price, discount, net amount and VAT rate with the tenant's currency and number format and takes a fractional VAT rate", () => {
    renderModal();

    expect(screen.getByTestId("lines-line-1-price_per_unit")).toHaveTextContent(
      "3,50 €/commissioning.units.kg",
    );
    expect(screen.getByTestId("lines-line-1-rabatt")).toHaveTextContent("10 %");
    expect(screen.getByTestId("lines-line-1-line_netto")).toHaveTextContent(
      "6,30 €",
    );
    expect(screen.getByTestId("lines-line-1-tax_rate")).toHaveTextContent(
      "7,00 %",
    );
    expect(screen.getByTestId("lines-line-1-amount")).toHaveTextContent("2,00");
    for (const name of ["lines", "crates"] as const) {
      const vat = grid(name).columns.find((c) => c.dataIndex === "tax_rate");
      expect(vat?.inputType).toBe("positive_decimal2");
    }
  });

  it("shows the backend's net line amount rather than recomputing it", () => {
    renderModal({
      invoice: makeInvoice({
        line_items: [{ ...CARROT_LINE, line_netto: "6.29" }],
      }),
    });

    expect(screen.getByTestId("lines-line-1-line_netto")).toHaveTextContent(
      "6,29 €",
    );
  });

  it("shows the delivery-note price under a price that was changed on the invoice", () => {
    renderModal({
      invoice: makeInvoice({
        line_items: [
          {
            ...CARROT_LINE,
            price_per_unit_differs: true,
            original_price_per_unit: "3.20",
          },
        ],
      }),
    });

    expect(screen.getByTestId("lines-line-1-price_per_unit")).toHaveTextContent(
      "3,50 €/commissioning.units.kg3,20 €",
    );
  });

  it("formats the crate price and net amount with the tenant's currency", () => {
    renderModal();

    expect(
      screen.getByTestId("crates-crate-1-price_per_unit"),
    ).toHaveTextContent("1,25 €");
    expect(screen.getByTestId("crates-crate-1-line_netto")).toHaveTextContent(
      "5,00 €",
    );
  });
});

// ── Totals ──────────────────────────────────────────────────────────────────

describe("InvoiceModal totals of an open invoice", () => {
  it("derives the per-rate breakdown and the totals from the lines and crates, ignoring the cached sums", () => {
    renderModal();

    // 7 %: 6.30 net -> 0.44 VAT. 19 %: 3.00 + 5.00 = 8.00 net -> 1.52 VAT.
    expect(
      screen.getByText("commissioning.netto (7%): 6,30 €"),
    ).toBeInTheDocument();
    expect(screen.getByText("commissioning.ust (7%): 0,44 €")).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.netto (19%): 8,00 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.ust (19%): 1,52 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_netto_invoice_details 14,30 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_ust_invoice_details 1,96 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_brutto_invoice_details 16,26 €"),
    ).toBeInTheDocument();
  });

  it("recomputes the totals from an in-place edit without refetching the invoice", () => {
    const { invalidateSpy } = renderModal();

    // The grid reports the edited rows: 4 kg instead of 2. The row still
    // carries the old cached line_netto, so the summary must recompute it.
    const editedCarrots = { ...CARROT_LINE, key: "line-1", amount: "4" };
    act(() => {
      grid("lines").onDataChange?.([
        editedCarrots,
        { ...LEEK_LINE, key: "line-2" },
      ]);
      grid("lines").onSaveSuccess?.(editedCarrots, "update");
    });

    // 4 * 3.50 * 0.9 = 12.60 net at 7 % -> 0.88 VAT; 19 % group unchanged.
    expect(
      screen.getByText("commissioning.netto (7%): 12,60 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_netto_invoice_details 20,60 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_ust_invoice_details 2,40 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_brutto_invoice_details 23,00 €"),
    ).toBeInTheDocument();
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("recomputes the totals when the crate grid reports a changed crate", () => {
    renderModal();

    act(() => {
      grid("crates").onDataChange?.([
        { ...SMALL_CRATES, key: "crate-1", amount: 8 },
      ]);
    });

    // 8 * 1.25 = 10.00 crates + 3.00 leeks = 13.00 net at 19 % -> 2.47 VAT.
    expect(
      screen.getByText("commissioning.netto (19%): 13,00 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.ust (19%): 2,47 €"),
    ).toBeInTheDocument();
  });
});

// ── Finalized invoice ───────────────────────────────────────────────────────

describe("InvoiceModal finalized invoice", () => {
  const finalizedInvoice = () =>
    makeInvoice({
      is_finalized: true,
      finalized_at: "2026-09-29T14:30:00",
      // The legally binding figures; they deliberately differ from what the
      // rows would compute, so the test can tell which source is shown.
      tax_breakdown: [
        { rate: "7.00", netto: "6.31", tax: "0.44", brutto: "6.75" },
        { rate: "19.00", netto: "8.00", tax: "1.52", brutto: "9.52" },
      ],
      sum_netto: "14.31",
      sum_brutto: "16.27",
    });

  // The PDF button is lazy-loaded; waiting for it keeps its Suspense
  // resolution inside the test.
  async function renderFinalized() {
    renderModal({ invoice: finalizedInvoice() });
    return screen.findByRole("button", { name: "commissioning.pdf" });
  }

  it("shows the backend's tax breakdown and totals verbatim", async () => {
    await renderFinalized();

    expect(
      screen.getByText("commissioning.netto (7%): 6,31 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_netto_invoice_details 14,31 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_ust_invoice_details 1,96 €"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.total_sum_brutto_invoice_details 16,27 €"),
    ).toBeInTheDocument();
  });

  it("locks both grids, even for an office user", async () => {
    await renderFinalized();

    for (const name of ["lines-grid", "crates-grid"]) {
      const table = screen.getByTestId(name);
      expect(table).toHaveAttribute("data-can-add", "false");
      expect(table).toHaveAttribute("data-can-edit", "false");
      expect(table).toHaveAttribute("data-can-delete", "false");
    }
  });

  it("shows the finalized notice with the tenant-formatted timestamp and offers the PDF", async () => {
    const pdfButton = await renderFinalized();

    expect(
      screen.getByText(/commissioning\.invoice_finalized_notice/),
    ).toHaveTextContent("29.09.2026 14:30");
    expect(pdfButton).toBeInTheDocument();
  });

  it("offers no PDF and no finalized notice while the invoice is open", () => {
    renderModal();

    expect(
      screen.queryByRole("button", { name: "commissioning.pdf" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/commissioning\.invoice_finalized_notice/),
    ).not.toBeInTheDocument();
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("InvoiceModal role gating", () => {
  it("lets an office user add, edit and delete lines of an open invoice and send it", () => {
    renderModal();

    const table = screen.getByTestId("lines-grid");
    expect(table).toHaveAttribute("data-can-add", "true");
    expect(table).toHaveAttribute("data-can-edit", "true");
    expect(table).toHaveAttribute("data-can-delete", "true");
    expect(screen.getByTestId("invoice-send-status")).toHaveAttribute(
      "data-can-send",
      "true",
    );
  });

  it("keeps an open invoice read-only for a user without the office role", () => {
    authState.roles = ["gardener", "staff"];
    renderModal();

    for (const name of ["lines-grid", "crates-grid"]) {
      const table = screen.getByTestId(name);
      expect(table).toHaveAttribute("data-can-add", "false");
      expect(table).toHaveAttribute("data-can-edit", "false");
      expect(table).toHaveAttribute("data-can-delete", "false");
    }
    expect(screen.getByTestId("invoice-send-status")).toHaveAttribute(
      "data-can-send",
      "false",
    );
  });
});

// ── Saving lines ────────────────────────────────────────────────────────────

describe("InvoiceModal line persistence", () => {
  it("stamps the invoice onto a new line, creates it through the generated client and refetches the invoice", async () => {
    const { invalidateSpy } = renderModal();
    const created = { ...CARROT_LINE, id: "line-9" };
    api.contentsCreate.mockResolvedValue(created);

    const lines = grid("lines");
    const payload = lines.customSave!(
      { share_article: "art-carrot", amount: 2, unit: "KG", size: "M" },
      { key: -1 },
    );
    expect(payload).toEqual({
      share_article: "art-carrot",
      amount: 2,
      unit: "KG",
      size: "M",
      invoice: "inv-1",
    });

    await expect(lines.apiFunctions!.create!(payload!)).resolves.toEqual({
      data: created,
    });
    expect(api.contentsCreate).toHaveBeenCalledWith(payload);

    act(() => lines.onSaveSuccess?.({ ...created, key: "line-9" }, "create"));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: INVOICE_QUERY_KEY });
  });

  it("updates an existing line through the generated client without refetching the invoice", async () => {
    const { invalidateSpy } = renderModal();
    api.contentsPartialUpdate.mockResolvedValue({ ...CARROT_LINE, sort: "B" });

    const lines = grid("lines");
    await lines.apiFunctions!.update!("line-1", { sort: "B", invoice: "inv-1" });
    act(() =>
      lines.onSaveSuccess?.({ ...CARROT_LINE, key: "line-1" }, "update"),
    );

    expect(api.contentsPartialUpdate).toHaveBeenCalledWith("line-1", {
      sort: "B",
      invoice: "inv-1",
    });
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("deletes a line through the generated client and refetches the invoice", async () => {
    const { invalidateSpy } = renderModal();
    api.contentsDestroy.mockResolvedValue(undefined);

    const lines = grid("lines");
    await lines.apiFunctions!.delete!("line-2");
    act(() => lines.onDeleteSuccess?.("line-2"));

    expect(api.contentsDestroy).toHaveBeenCalledWith("line-2");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: INVOICE_QUERY_KEY });
  });

  it("seeds a new line with size M, unit KG and the tenant's default article VAT rate", () => {
    tenantSettings.values = { default_tax_rate_articles: 10 };
    renderModal();
    const form = { setFieldsValue: vi.fn() } as unknown as FormInstance;

    const seeded = grid("lines").customEdit!({ key: -1 }, form);

    expect(seeded).toEqual({ key: -1, size: "M", unit: "KG", tax_rate: 10 });
    expect(form.setFieldsValue).toHaveBeenCalledWith({
      size: "M",
      unit: "KG",
      tax_rate: 10,
    });
  });

  it("leaves an existing line untouched when it enters edit mode", () => {
    renderModal();
    const form = { setFieldsValue: vi.fn() } as unknown as FormInstance;
    const record = { ...CARROT_LINE, key: "line-1" };

    expect(grid("lines").customEdit!(record, form)).toBe(record);
    expect(form.setFieldsValue).not.toHaveBeenCalled();
  });

  it("only lets a new line pick its share article", () => {
    renderModal();
    const articleColumn = grid("lines").columns.find(
      (column) => column.dataIndex === "share_article_name",
    );
    const disabled = articleColumn?.disabled as (record: TableRecord) => boolean;

    expect(disabled({ key: -1 })).toBe(false);
    expect(disabled({ key: "line-1" })).toBe(true);
  });
});

// ── Crates ──────────────────────────────────────────────────────────────────

describe("InvoiceModal crates", () => {
  const crateTypeOptions = () =>
    (
      grid("crates").columns.find((c) => c.key === "crate_type_name")
        ?.options as { value: string }[]
    ).map((option) => option.value);

  it("offers only the crate types that are not on the invoice yet", () => {
    renderModal();

    expect(crateTypeOptions()).toEqual(["ct-large"]);
    expect(screen.getByTestId("crates-grid")).toHaveAttribute(
      "data-can-add",
      "true",
    );
  });

  it("stops adding crates once every crate type is used, but keeps the crates editable", () => {
    renderModal({
      invoice: makeInvoice({
        crate_items: [
          SMALL_CRATES,
          { ...SMALL_CRATES, id: "crate-2", crate_type: "ct-large" },
        ],
      }),
    });

    expect(crateTypeOptions()).toEqual([]);
    const table = screen.getByTestId("crates-grid");
    expect(table).toHaveAttribute("data-can-add", "false");
    expect(table).toHaveAttribute("data-can-edit", "true");
    expect(table).toHaveAttribute("data-can-delete", "true");
  });

  it("stamps the invoice onto a new crate line and creates it through the generated client", async () => {
    renderModal();
    api.cratesCreate.mockResolvedValue({ id: "crate-9" });

    const crates = grid("crates");
    const payload = crates.customSave!(
      { crate_type: "ct-large", amount: 2 },
      { key: -1 },
    );
    await crates.apiFunctions!.create!(payload!);

    expect(api.cratesCreate).toHaveBeenCalledWith({
      crate_type: "ct-large",
      amount: 2,
      invoice_id: "inv-1",
    });
  });

  it("deletes a crate line by its crate type and the invoice", async () => {
    const { invalidateSpy } = renderModal();
    api.cratesDestroy.mockResolvedValue(undefined);

    const crates = grid("crates");
    const params = crates.customDelete!({ ...SMALL_CRATES, key: "crate-1" });
    await crates.apiFunctions!.delete!("crate-1", params!);
    act(() => crates.onDeleteSuccess?.("crate-1"));

    expect(api.cratesDestroy).toHaveBeenCalledWith("crate-1", {
      crate_type: "ct-small",
      invoice_id: "inv-1",
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: INVOICE_QUERY_KEY });
  });

  it("hides the crate grid when the tenant keeps crates off documents and the invoice has none", () => {
    tenantSettings.values = { crates_should_be_on_documents: false };
    renderModal({ invoice: makeInvoice({ crate_items: [] }) });

    expect(screen.queryByTestId("crates-grid")).not.toBeInTheDocument();
    expect(
      screen.queryByText("commissioning.crates_invoicemodal"),
    ).not.toBeInTheDocument();
  });

  it("still shows crates already on the invoice when the tenant keeps crates off documents", () => {
    tenantSettings.values = { crates_should_be_on_documents: false };
    renderModal();

    expect(screen.getByTestId("crates-grid")).toBeInTheDocument();
    // The existing crates still count towards the totals.
    expect(
      screen.getByText("commissioning.netto (19%): 8,00 €"),
    ).toBeInTheDocument();
  });

  it("reads the invoice again after a crate line is saved, since the server can merge it with another line", () => {
    const { invalidateSpy } = renderModal();

    act(() =>
      grid("crates").onSaveSuccess?.({ ...SMALL_CRATES, key: "crate-1" }, "update"),
    );

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: INVOICE_QUERY_KEY });
  });
});

// ── Crate lines in the real table ───────────────────────────────────────────

describe("InvoiceModal crate lines", () => {
  beforeEach(() => {
    grids.realCrates = true;
  });

  it("shows each price of a crate type on its own line, opens one at a time and saves it under its own id", async () => {
    const user = crateGridUser();
    renderModal({
      invoice: makeInvoice({
        crate_items: [SMALL_CRATES_AT_125, SMALL_CRATES_AT_150],
      }),
    });
    api.cratesPartialUpdate.mockImplementation(
      async (id: string, body: Record<string, unknown>) => ({
        ...SMALL_CRATES_AT_150,
        id,
        amount: Number(body.amount),
        line_netto: "4.50",
      }),
    );
    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["4", "2"]));
    expect(shownUnder(PRICE)).toEqual(["1,25 €", "1,50 €"]);
    // 3.00 leeks + 5.00 + 3.00 crates at 19 %.
    expect(
      screen.getByText("commissioning.netto (19%): 11,00 €"),
    ).toBeInTheDocument();

    const amount = await openAt(user, crateRows()[1], AMOUNT);

    expect(screen.getAllByRole("button", { name: "table.save" })).toHaveLength(1);
    expect(editingRow()).toBe(crateRows()[1]);

    await user.clear(amount);
    await user.type(amount, "3");
    await saveLine(user);

    await waitFor(() => expect(api.cratesPartialUpdate).toHaveBeenCalledTimes(1));
    expect(api.cratesPartialUpdate).toHaveBeenCalledWith(
      "ct-small_row-7",
      expect.objectContaining({
        crate_type: "ct-small",
        amount: "3",
        invoice_id: "inv-1",
      }),
    );
    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["4", "3"]));
    expect(shownUnder(PRICE)).toEqual(["1,25 €", "1,50 €"]);
    // 3.00 leeks + 5.00 + 4.50 crates at 19 %.
    expect(
      screen.getByText("commissioning.netto (19%): 12,50 €"),
    ).toBeInTheDocument();
  });

  it("refuses a new line whose crate type the invoice lists by the time it is saved, on the crate type, and sends nothing", async () => {
    const user = crateGridUser();
    const { show } = renderModal();
    await waitFor(() => expect(crateRows()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /table\.add_plus_icon/ }));
    await pickCrateType(user, "Large");
    await user.type(within(editingRow()).getByLabelText(AMOUNT), "2");
    // Meanwhile a large-crate line was added to the invoice elsewhere.
    show(
      makeInvoice({
        crate_items: [
          SMALL_CRATES,
          {
            ...SMALL_CRATES,
            id: "ct-large_row-9",
            crate_type: "ct-large",
            crate_type_name: "Large",
            amount: 1,
          },
        ],
      }),
    );
    await saveLine(user);

    const refused = "validation.unique.invoice_modal_crate";
    expect(
      await screen.findByText(`${refused} — table.save_failed_hint`),
    ).toBeInTheDocument();
    expect(
      within(crateCell(editingRow(), CRATE_TYPE)).getByRole("alert"),
    ).toHaveTextContent(refused);
    expect(api.cratesCreate).not.toHaveBeenCalled();
  });

  it("shows the next invoice's own crate line, not what was saved on the one before", async () => {
    const user = crateGridUser();
    // Both invoices name their small-crate line by the crate type, so the
    // line has the same id on either invoice.
    const firstLine = { ...SMALL_CRATES, id: "ct-small" };
    const nextLine = { ...firstLine, amount: 2, line_netto: "2.50" };
    const { show } = renderModal({
      invoice: makeInvoice({ crate_items: [firstLine] }),
    });
    api.cratesPartialUpdate.mockImplementation(
      async (id: string, body: Record<string, unknown>) => ({
        ...firstLine,
        id,
        rabatt: Number(body.rabatt),
        line_netto: "4.50",
      }),
    );
    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["4"]));

    const discount = await openAt(user, crateRows()[0], DISCOUNT);
    await user.clear(discount);
    await user.type(discount, "10");
    await saveLine(user);
    await waitFor(() => expect(shownUnder(DISCOUNT)).toEqual(["10 %"]));

    show(
      makeInvoice({
        id: "inv-2",
        invoice_number: "2026-008",
        crate_items: [nextLine],
      }),
    );

    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["2"]));
    expect(shownUnder(DISCOUNT)).toEqual([""]);
  });
});
