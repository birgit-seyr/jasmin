/**
 * DeliveryNoteModal: the office's editor for one reseller delivery note.
 *
 * The modal owns the delivery-note fetch, the wiring of its two grids (line
 * items and crates), the read-only gate for finalized notes and non-office
 * users, and the VAT-rate autofill a new line needs before it can be saved.
 * EditableTable is replaced by a stub that records the props each grid
 * receives and renders every row through the real column ``render``
 * functions; a test that needs the table's own editing renders the crate
 * grid through the real EditableTable instead. The column hooks are real and
 * only the generated API client is mocked.
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
// ``get_price_info`` annotates each article with its current VAT rate; the
// honey has none, and the seedlings are legitimately VAT-free.
const SHARE_ARTICLES = [
  { id: "art-carrot", name: "Carrots", default_movement_unit: "KG", tax_rate: "7.00" },
  { id: "art-honey", name: "Honey", default_movement_unit: "PCS" },
  { id: "art-seedlings", name: "Seedlings", default_movement_unit: "PCS", tax_rate: "0.00" },
];

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDeliveryNotesRetrieve: (id: string, options: unknown) =>
    api.retrieve(id, options),
  getCommissioningDeliveryNotesRetrieveQueryKey: (id: string) => [
    `/api/commissioning/delivery_notes/${id}/`,
  ],
  commissioningDeliveryNoteContentsCreate: (...args: unknown[]) =>
    api.contentsCreate(...args),
  commissioningDeliveryNoteContentsPartialUpdate: (...args: unknown[]) =>
    api.contentsPartialUpdate(...args),
  commissioningDeliveryNoteContentsDestroy: (...args: unknown[]) =>
    api.contentsDestroy(...args),
  commissioningCrateContentsDeliveryNoteCreate: (...args: unknown[]) =>
    api.cratesCreate(...args),
  commissioningCrateContentsDeliveryNotePartialUpdate: (...args: unknown[]) =>
    api.cratesPartialUpdate(...args),
  commissioningCrateContentsDeliveryNoteDestroy: (...args: unknown[]) =>
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

import DeliveryNoteModal from "../DeliveryNoteModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const CARROT_LINE = {
  id: "line-1",
  delivery_note: "dn-1",
  share_article: "art-carrot",
  share_article_name: "Carrots",
  amount: "2.500",
  unit: "KG",
  size: "M",
  price_per_unit: "3.50",
  rabatt: 0,
  tax_rate: "7.00",
  note: "washed",
};

const HONEY_LINE = {
  id: "line-2",
  delivery_note: "dn-1",
  share_article: "art-honey",
  share_article_name: "Honey",
  amount: "12.000",
  unit: "PCS",
  size: "M",
  price_per_unit: "6.00",
  rabatt: 0,
  tax_rate: "7.00",
};

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

// Small crates delivered at two prices: two lines of one crate type, each
// named by a crate row of its own.
const SMALL_CRATES_AT_125 = { ...SMALL_CRATES, id: "ct-small_row-1" };
const SMALL_CRATES_AT_150 = {
  ...SMALL_CRATES,
  id: "ct-small_row-7",
  amount: 2,
  price_per_unit: "1.50",
  line_netto: "3.00",
};

function makeDeliveryNote(overrides: Record<string, unknown> = {}) {
  return {
    id: "dn-1",
    prefix: "LS",
    delivery_note_number: "2026-011",
    delivery_note_date: "2026-09-30",
    reseller_name: "Acme Grocers",
    order_prefix: "BE",
    order_number: "2026-005",
    order_date: "2026-09-25",
    is_finalized: false,
    finalized_at: null,
    line_items: [CARROT_LINE, HONEY_LINE],
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
  deliveryNote = makeDeliveryNote() as Record<string, unknown> | undefined,
  visible = true,
  onClose = vi.fn(),
} = {}) {
  // Same object on every call, like a settled TanStack query.
  api.retrieve.mockReturnValue({ data: deliveryNote, isFetching: false });
  const client = makeQueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const modalFor = (deliveryNoteId: string) => (
    <QueryClientProvider client={client}>
      <DeliveryNoteModal
        visible={visible}
        deliveryNoteId={deliveryNoteId}
        onClose={onClose}
      />
    </QueryClientProvider>
  );
  const { rerender } = render(modalFor("dn-1"));
  /** Shows ``note`` in the open modal, as read again or as the next note picked. */
  const show = (note: Record<string, unknown>) => {
    api.retrieve.mockReturnValue({ data: note, isFetching: false });
    rerender(modalFor(note.id as string));
  };
  return { invalidateSpy, onClose, show };
}

function grid(name: GridName): EditableTableProps {
  const props = grids.props[name];
  if (!props) throw new Error(`the ${name} grid never rendered`);
  return props as EditableTableProps;
}

function makeForm() {
  return { setFieldsValue: vi.fn() } as unknown as FormInstance & {
    setFieldsValue: ReturnType<typeof vi.fn>;
  };
}

const DELIVERY_NOTE_QUERY_KEY = ["/api/commissioning/delivery_notes/dn-1/"];

// ── The real crate grid ─────────────────────────────────────────────────────

const CRATE_TYPE = "commissioning.crate_type_name";
const AMOUNT = "commissioning.amount";
const NOTE = "commissioning.note";

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

describe("DeliveryNoteModal header", () => {
  it("does not fetch the delivery note while the modal is closed", () => {
    renderModal({ visible: false });

    expect(api.retrieve).toHaveBeenCalledWith("dn-1", {
      query: { enabled: false },
    });
    expect(screen.queryByTestId("lines-grid")).not.toBeInTheDocument();
  });

  it("shows the number, the reseller, the tenant-formatted date and the order it was delivered for", () => {
    renderModal();

    expect(api.retrieve).toHaveBeenCalledWith("dn-1", {
      query: { enabled: true },
    });
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("commissioning.delivery_note_details LS-2026-011"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Acme Grocers")).toBeInTheDocument();
    expect(within(dialog).getByText("30.09.2026")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/commissioning\.corresponding_order/)
        .parentElement,
    ).toHaveTextContent("BE-2026-005 (25.09.2026)");
  });

  it("still names the order without printing a bogus date when the order has no date", () => {
    renderModal({ deliveryNote: makeDeliveryNote({ order_date: null }) });

    const orderLine = screen.getByText(
      /commissioning\.corresponding_order/,
    ).parentElement;
    expect(orderLine).toHaveTextContent("BE-2026-005");
    expect(orderLine).not.toHaveTextContent(/Invalid Date|null|-$/);
  });

  it("calls onClose from the footer button", async () => {
    const { onClose } = renderModal();

    await userEvent.click(screen.getByRole("button", { name: "common.close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ── Cells ───────────────────────────────────────────────────────────────────

describe("DeliveryNoteModal cells", () => {
  it("formats amounts at their unit's precision in the tenant's number format", () => {
    renderModal();

    expect(screen.getByTestId("lines-line-1-amount")).toHaveTextContent("2,50");
    expect(screen.getByTestId("lines-line-2-amount")).toHaveTextContent("12,0");
    const amount = grid("lines").columns.find((c) => c.dataIndex === "amount");
    expect(amount?.inputType).toBe("positive_decimal3");
  });

  it("shows no VAT column, so the rate is only corrected on the invoice", () => {
    renderModal();

    expect(
      grid("lines").columns.some((column) => column.dataIndex === "tax_rate"),
    ).toBe(false);
    expect(screen.getByTestId("lines-line-1-note")).toHaveTextContent("washed");
  });

  it("shows crates without prices", () => {
    renderModal();

    const crateColumns = grid("crates").columns.map((column) => column.key);
    expect(crateColumns).toContain("crate_type_name");
    expect(crateColumns).toContain("amount");
    expect(crateColumns).not.toContain("price_per_unit");
    expect(crateColumns).not.toContain("line_netto");
  });
});

// ── Finalized note and roles ────────────────────────────────────────────────

describe("DeliveryNoteModal read-only states", () => {
  it("locks both grids of a finalized delivery note and shows when it was finalized", () => {
    renderModal({
      deliveryNote: makeDeliveryNote({
        is_finalized: true,
        finalized_at: "2026-09-30T08:15:00",
      }),
    });

    for (const name of ["lines-grid", "crates-grid"]) {
      const table = screen.getByTestId(name);
      expect(table).toHaveAttribute("data-can-add", "false");
      expect(table).toHaveAttribute("data-can-edit", "false");
      expect(table).toHaveAttribute("data-can-delete", "false");
    }
    expect(
      screen.getByText(/commissioning\.delivery_note_finalized_notice/),
    ).toHaveTextContent("30.09.2026 08:15");
  });

  it("shows no finalized notice while the delivery note is open", () => {
    renderModal();

    expect(
      screen.queryByText(/commissioning\.delivery_note_finalized_notice/),
    ).not.toBeInTheDocument();
  });

  it("lets an office user add, edit and delete lines of an open delivery note", () => {
    renderModal();

    const table = screen.getByTestId("lines-grid");
    expect(table).toHaveAttribute("data-can-add", "true");
    expect(table).toHaveAttribute("data-can-edit", "true");
    expect(table).toHaveAttribute("data-can-delete", "true");
  });

  it("keeps an open delivery note read-only for a user without the office role", () => {
    authState.roles = ["staff"];
    renderModal();

    for (const name of ["lines-grid", "crates-grid"]) {
      const table = screen.getByTestId(name);
      expect(table).toHaveAttribute("data-can-add", "false");
      expect(table).toHaveAttribute("data-can-edit", "false");
      expect(table).toHaveAttribute("data-can-delete", "false");
    }
  });
});

// ── VAT autofill on a new line ──────────────────────────────────────────────

describe("DeliveryNoteModal VAT autofill", () => {
  const pickArticle = (articleId: string) => {
    const articleColumn = grid("lines").columns.find(
      (column) => column.dataIndex === "share_article_name",
    )!;
    const form = makeForm();
    const patch = articleColumn.onFieldChange!(
      articleId,
      { key: -1 },
      form,
      "share_article_name",
    );
    return { form, patch };
  };

  it("takes the VAT rate of the picked share article", () => {
    renderModal();

    const { form, patch } = pickArticle("art-carrot");

    expect(form.setFieldsValue).toHaveBeenCalledWith({ tax_rate: 7 });
    expect(patch).toEqual({ tax_rate: 7 });
  });

  it("falls back to the tenant's default article VAT rate when the article carries none", () => {
    tenantSettings.values = { default_tax_rate_articles: 10.7 };
    renderModal();

    const { form } = pickArticle("art-honey");

    expect(form.setFieldsValue).toHaveBeenCalledWith({ tax_rate: 10.7 });
  });

  it("keeps a VAT-free article at 0 % instead of the tenant default", () => {
    tenantSettings.values = { default_tax_rate_articles: 10.7 };
    renderModal();

    const { form } = pickArticle("art-seedlings");

    expect(form.setFieldsValue).toHaveBeenCalledWith({ tax_rate: 0 });
  });

  it("seeds a new line with size M, unit KG and the tenant's default article VAT rate", () => {
    tenantSettings.values = { default_tax_rate_articles: 10.7 };
    renderModal();
    const form = makeForm();

    const seeded = grid("lines").customEdit!({ key: -1 }, form);

    expect(seeded).toEqual({ key: -1, size: "M", unit: "KG", tax_rate: 10.7 });
    expect(form.setFieldsValue).toHaveBeenCalledWith({
      size: "M",
      unit: "KG",
      tax_rate: 10.7,
    });
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

// ── Persistence ─────────────────────────────────────────────────────────────

describe("DeliveryNoteModal line persistence", () => {
  it("stamps the delivery note onto a new line, creates it through the generated client and refetches the note", async () => {
    const { invalidateSpy } = renderModal();
    const created = { ...CARROT_LINE, id: "line-9" };
    api.contentsCreate.mockResolvedValue(created);

    const lines = grid("lines");
    const payload = lines.customSave!(
      { share_article: "art-carrot", amount: 1, unit: "KG", tax_rate: 7 },
      { key: -1 },
    );
    expect(payload).toEqual({
      share_article: "art-carrot",
      amount: 1,
      unit: "KG",
      tax_rate: 7,
      delivery_note: "dn-1",
    });

    await expect(lines.apiFunctions!.create!(payload!)).resolves.toEqual({
      data: created,
    });
    expect(api.contentsCreate).toHaveBeenCalledWith(payload);

    act(() => lines.onSaveSuccess?.({ ...created, key: "line-9" }, "create"));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: DELIVERY_NOTE_QUERY_KEY,
    });
  });

  it("updates an existing line through the generated client without refetching the note", async () => {
    const { invalidateSpy } = renderModal();
    api.contentsPartialUpdate.mockResolvedValue({ ...CARROT_LINE, amount: "3" });

    const lines = grid("lines");
    await lines.apiFunctions!.update!("line-1", { amount: "3" });
    act(() =>
      lines.onSaveSuccess?.({ ...CARROT_LINE, key: "line-1" }, "update"),
    );

    expect(api.contentsPartialUpdate).toHaveBeenCalledWith("line-1", {
      amount: "3",
    });
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("deletes a line through the generated client and refetches the note", async () => {
    const { invalidateSpy } = renderModal();
    api.contentsDestroy.mockResolvedValue(undefined);

    const lines = grid("lines");
    await lines.apiFunctions!.delete!("line-2");
    act(() => lines.onDeleteSuccess?.("line-2"));

    expect(api.contentsDestroy).toHaveBeenCalledWith("line-2");
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: DELIVERY_NOTE_QUERY_KEY,
    });
  });
});

// ── Crates ──────────────────────────────────────────────────────────────────

describe("DeliveryNoteModal crates", () => {
  const crateTypeOptions = () =>
    (
      grid("crates").columns.find((c) => c.key === "crate_type_name")
        ?.options as { value: string }[]
    ).map((option) => option.value);

  it("offers only the crate types that are not on the delivery note yet", () => {
    renderModal();

    expect(crateTypeOptions()).toEqual(["ct-large"]);
    expect(screen.getByTestId("crates-grid")).toHaveAttribute(
      "data-can-add",
      "true",
    );
  });

  it("stops adding crates once every crate type is used, but keeps the crates editable", () => {
    renderModal({
      deliveryNote: makeDeliveryNote({
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

  it("stamps the delivery note onto a new crate line and creates it through the generated client", async () => {
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
      delivery_note_id: "dn-1",
    });
  });

  it("deletes a crate line by its crate type and the delivery note", async () => {
    const { invalidateSpy } = renderModal();
    api.cratesDestroy.mockResolvedValue(undefined);

    const crates = grid("crates");
    const params = crates.customDelete!({ ...SMALL_CRATES, key: "crate-1" });
    await crates.apiFunctions!.delete!("crate-1", params!);
    act(() => crates.onDeleteSuccess?.("crate-1"));

    expect(api.cratesDestroy).toHaveBeenCalledWith("crate-1", {
      crate_type: "ct-small",
      delivery_note_id: "dn-1",
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: DELIVERY_NOTE_QUERY_KEY,
    });
  });

  it("hides the crate grid when the tenant keeps crates off documents and the note has none", () => {
    tenantSettings.values = { crates_should_be_on_documents: false };
    renderModal({ deliveryNote: makeDeliveryNote({ crate_items: [] }) });

    expect(screen.queryByTestId("crates-grid")).not.toBeInTheDocument();
    expect(screen.queryByText("commissioning.crates")).not.toBeInTheDocument();
  });

  it("still shows crates already on the note when the tenant keeps crates off documents", () => {
    tenantSettings.values = { crates_should_be_on_documents: false };
    renderModal();

    expect(screen.getByTestId("crates-grid")).toBeInTheDocument();
    expect(screen.getByTestId("crates-crate-1-amount")).toHaveTextContent("4");
  });

  it("reads the delivery note again after a crate line is saved, since the server can merge it with another line", () => {
    const { invalidateSpy } = renderModal();

    act(() =>
      grid("crates").onSaveSuccess?.({ ...SMALL_CRATES, key: "crate-1" }, "update"),
    );

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: DELIVERY_NOTE_QUERY_KEY,
    });
  });
});

// ── Crate lines in the real table ───────────────────────────────────────────

describe("DeliveryNoteModal crate lines", () => {
  beforeEach(() => {
    grids.realCrates = true;
  });

  it("shows each line of a crate type on its own row, opens one at a time and saves it under its own id", async () => {
    const user = crateGridUser();
    renderModal({
      deliveryNote: makeDeliveryNote({
        crate_items: [SMALL_CRATES_AT_125, SMALL_CRATES_AT_150],
      }),
    });
    api.cratesPartialUpdate.mockImplementation(
      async (id: string, body: Record<string, unknown>) => ({
        ...SMALL_CRATES_AT_150,
        id,
        amount: Number(body.amount),
      }),
    );
    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["4", "2"]));
    expect(shownUnder(CRATE_TYPE)).toEqual(["Small", "Small"]);

    const amount = await openAt(user, crateRows()[1], AMOUNT);

    expect(screen.getAllByRole("button", { name: "table.save" })).toHaveLength(1);
    expect(editingRow()).toBe(crateRows()[1]);

    await user.clear(amount);
    await user.type(amount, "5");
    await saveLine(user);

    await waitFor(() => expect(api.cratesPartialUpdate).toHaveBeenCalledTimes(1));
    expect(api.cratesPartialUpdate).toHaveBeenCalledWith(
      "ct-small_row-7",
      expect.objectContaining({
        crate_type: "ct-small",
        amount: "5",
        delivery_note_id: "dn-1",
      }),
    );
    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["4", "5"]));
  });

  it("refuses a new line whose crate type the note lists by the time it is saved, on the crate type, and sends nothing", async () => {
    const user = crateGridUser();
    const { show } = renderModal();
    await waitFor(() => expect(crateRows()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /table\.add_plus_icon/ }));
    await pickCrateType(user, "Large");
    await user.type(within(editingRow()).getByLabelText(AMOUNT), "2");
    // Meanwhile a large-crate line was added to the note elsewhere.
    show(
      makeDeliveryNote({
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

    const refused = "validation.unique.delivery_note_modal_crate";
    expect(
      await screen.findByText(`${refused} — table.save_failed_hint`),
    ).toBeInTheDocument();
    expect(
      within(crateCell(editingRow(), CRATE_TYPE)).getByRole("alert"),
    ).toHaveTextContent(refused);
    expect(api.cratesCreate).not.toHaveBeenCalled();
  });

  it("shows the next delivery note's own crate line, not what was saved on the one before", async () => {
    const user = crateGridUser();
    // Both notes name their small-crate line by the crate type, so the line
    // has the same id on either note.
    const firstLine = { ...SMALL_CRATES, id: "ct-small", note: null };
    const nextLine = { ...firstLine, amount: 3 };
    const { show } = renderModal({
      deliveryNote: makeDeliveryNote({ crate_items: [firstLine] }),
    });
    api.cratesPartialUpdate.mockImplementation(
      async (id: string, body: Record<string, unknown>) => ({
        ...firstLine,
        id,
        note: body.note,
      }),
    );
    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["4"]));

    const note = await openAt(user, crateRows()[0], NOTE);
    await user.type(note, "Two came back broken");
    await saveLine(user);
    await waitFor(() =>
      expect(shownUnder(NOTE)).toEqual(["Two came back broken"]),
    );

    show(
      makeDeliveryNote({
        id: "dn-2",
        delivery_note_number: "2026-012",
        crate_items: [nextLine],
      }),
    );

    await waitFor(() => expect(shownUnder(AMOUNT)).toEqual(["3"]));
    expect(shownUnder(NOTE)).toEqual([""]);
  });
});
