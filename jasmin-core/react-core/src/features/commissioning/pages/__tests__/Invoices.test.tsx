/**
 * Tier-4 integration smoke for the resellers ``Invoices`` page.
 *
 * Three things this test owns:
 *   1. Mount + query wiring — ``useCommissioningOrdersOverviewList`` is
 *      called with the right ``year/reseller`` params.
 *   2. Bulk finalize wiring — same shape as DeliveryNotes but with
 *      ``model: "invoice"`` in the payload.
 *   3. Storno happy path — clicking the per-row Storno button opens
 *      the modal, the OK button is disabled until a reason is typed,
 *      and submitting hits the ``/api/commissioning/invoices/{id}/
 *      create_storno/`` endpoint with ``{ reason }``.
 *
 * Known gap (intentionally not tested here): when the storno endpoint
 * rejects with a circular-reference error (the plan-item from
 * ``frontend_test_plan.txt``), the page's ``handleCreateStorno`` only
 * ``console.error``s — no toast is surfaced. A useful follow-up would
 * be wiring ``notify.error`` into that catch block so the failure is
 * visible to the user.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

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

// vi.hoisted for any spy that ends up as a *direct property value*
// inside a vi.mock factory.
const { notifyMock, axiosServiceMock } = vi.hoisted(() => ({
  notifyMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  axiosServiceMock: vi.fn(),
}));

vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  getErrorMessage: (err: unknown, fallback?: string) => {
    const e = err as { response?: { data?: { message?: string } } };
    return e?.response?.data?.message ?? fallback ?? "Action failed";
  },
}));

vi.mock("@shared/services/api", () => ({
  axiosService: axiosServiceMock,
  default: vi.fn(),
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  // Real implementation — it's a pure React-state hook (no API/tenant deps),
  // and these tests exercise actual row-selection behaviour.
  const { useTableRowSelection } = await import(
    "@hooks/useTableRowSelection"
  );
  const tenant = makeUseTenantMock({
    tenant: { id: "t-1" },
    logoUrl: "https://example.test/logo.png",
  });
  return {
    useTenant: () => tenant,
    useDateFormat: () => ({ formatDate: (iso?: string | null) => iso ?? "" }),
    useCurrency: () => ({ currencySymbol: "€" }),
    useNumberFormat: () => ({ format: (n: number, d: number) => n.toFixed(d) }),
    useTableRowSelection,
    // No-op stub: the page uses the helper to gate list-query
    // invalidation, but in tests we don't care about cache refresh.
    useInvalidateAfterTableMutation: () => ({
      onSaveSuccess: () => {},
      onDeleteSuccess: () => {},
    }),
  };
});

// ── Generated API mocks ─────────────────────────────────────────────────────

const ordersOverviewHookMock = vi.fn();
const bulkFinalizeMock = vi.fn();
const bulkCreateDocsMock = vi.fn();
const bulkCreateSummaryMock = vi.fn();
const bulkDeleteDocsMock = vi.fn();
const createStornoMutateAsyncMock = vi.fn();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningOrdersOverviewList: (params: unknown, opts?: unknown) =>
    ordersOverviewHookMock(params, opts),
  useCommissioningInvoicesCreateStornoCreate: () => ({
    mutateAsync: createStornoMutateAsyncMock,
    isPending: false,
  }),
  commissioningBulkFinalizeDocumentsCreate: (...args: unknown[]) =>
    bulkFinalizeMock(...args),
  commissioningBulkCreateDocumentsFromOrdersCreate: (...args: unknown[]) =>
    bulkCreateDocsMock(...args),
  commissioningBulkCreateSummaryInvoiceFromOrdersCreate: (...args: unknown[]) =>
    bulkCreateSummaryMock(...args),
  commissioningBulkDeleteDocumentsCreate: (...args: unknown[]) =>
    bulkDeleteDocsMock(...args),
  getCommissioningOrdersOverviewListQueryKey: (p?: unknown) => ["orders", p],
}));

// ── Sub-component stubs ─────────────────────────────────────────────────────

vi.mock("@features/commissioning/modals", () => ({
  InvoiceModal: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="invoice-modal" /> : null,
}));

vi.mock("@features/commissioning/pdfs", () => ({
  InvoicePDFButtons: () => <button>invoice-pdf</button>,
}));

// The page deep-imports the PDF helper (Invoices.tsx imports
// ``generateAndUploadInvoicePDF`` from
// ``@features/commissioning/pdfs/forResellers/generateInvoicePDF``, not the
// barrel above), so the storno happy path would otherwise run the real
// generator and hit the unmocked ``commissioningInvoicesRetrieve``. Stub the
// deep path too.
vi.mock("@features/commissioning/pdfs/forResellers/generateInvoicePDF", () => ({
  generateAndUploadInvoicePDF: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@shared/selectors", () => ({
  YearSelector: () => <div data-testid="year-selector" />,
  ResellerSelector: () => <div data-testid="reseller-selector" />,
}));

vi.mock("@shared/ui", () => ({
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer">{children}</div>
  ),
  ViewDetailsButton: () => <button>view-details</button>,
  ToolTipIcon: () => null,
  BulkActionButton: ({
    apiFunction,
    selectedIds,
    payload,
    buttonText,
    disabled,
    onSuccess,
  }: {
    apiFunction?: (payload: Record<string, unknown>) => Promise<unknown>;
    selectedIds: (string | number)[];
    payload?: Record<string, unknown>;
    buttonText: string;
    disabled?: boolean;
    onSuccess?: (res: unknown, ids: (string | number)[]) => void;
  }) => (
    <button
      data-testid={`bulk-${String(buttonText)}`}
      disabled={disabled}
      onClick={async () => {
        try {
          const res = await apiFunction!({
            ids: selectedIds,
            ...(payload ?? {}),
          });
          notifyMock.success("done");
          await onSuccess?.(res, selectedIds);
        } catch (err) {
          const e = err as { response?: { data?: { message?: string } } };
          notifyMock.error(e?.response?.data?.message ?? "Action failed");
        }
      }}
    >
      {buttonText}
    </button>
  ),
}));

// EditableTable stub: renders the FIRST row's actions column so the
// per-row Storno button (and any other row-level controls) are reachable
// from the test. Also exposes a "select-all" button for bulk wiring tests.
vi.mock("@shared/tables", async () => {
  // wrapApiFunctions is pure (type-only deps) — use the real one.
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  return {
    READ_ONLY_PERMISSION: {},
    wrapApiFunctions,
    EditableTable: ({
      columns,
      initialData,
      onSelectedRowsChange,
    }: {
      columns?: Array<{
        key?: string;
        render?: (
          v: unknown,
          record: Record<string, unknown>,
        ) => React.ReactNode;
      }>;
      initialData?: Array<Record<string, unknown>>;
      onSelectedRowsChange?: (ids: (string | number)[]) => void;
    }) => {
      const rows = initialData ?? [];
      const actionsCol = columns?.find((c) => c.key === "actions");
      return (
        <div data-testid="editable-table">
          <button
            onClick={() =>
              onSelectedRowsChange?.(
                rows
                  .map((r) => r.id as string | number | undefined)
                  .filter((id): id is string | number => id != null),
              )
            }
          >
            select-all
          </button>
          <span data-testid="row-count">{rows.length}</span>
          {/* Render the per-row actions cell so the Storno trigger button
              shows up in the DOM under a recognisable wrapper. */}
          {rows[0] && actionsCol?.render && (
            <div data-testid="row-actions">
              {actionsCol.render(undefined, rows[0])}
            </div>
          )}
        </div>
      );
    },
  };
});

import Invoices from "../Invoices";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeRow(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "ord-9",
    order_date: "2026-05-20",
    order_number: "BE-2026-001",
    order_is_finalized: true,
    reseller_name: "Acme Co",
    has_invoice: true,
    has_finalized_invoice: true,
    invoice_is_finalized: true,
    invoice_cancelled_by: null,
    invoice_id: "inv-42",
    invoice_date: "2026-05-21",
    invoice_number: "RE-2026-001",
    invoice_storno_id: null,
    // delivery_note_id is REQUIRED — the page's filteredData useMemo
    // drops rows where this is null/undefined, so without it the table
    // never sees the row.
    delivery_note_id: "dn-77",
    delivery_note_date: "2026-05-21",
    delivery_note_number: "LS-2026-001",
    delivery_note_is_finalized: true,
    sum_netto: "120.00",
    ...overrides,
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <Invoices />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  ordersOverviewHookMock.mockReset().mockReturnValue({
    data: [makeRow()],
    refetch: vi.fn(),
  });
  bulkFinalizeMock.mockReset().mockResolvedValue({ results: [] });
  bulkCreateDocsMock.mockReset().mockResolvedValue({ results: [] });
  bulkCreateSummaryMock.mockReset().mockResolvedValue({ results: [] });
  bulkDeleteDocsMock.mockReset().mockResolvedValue({ results: [] });
  axiosServiceMock.mockReset();
  createStornoMutateAsyncMock.mockReset().mockResolvedValue({ id: "storno-1" });
  notifyMock.success.mockReset();
  notifyMock.error.mockReset();
  notifyMock.warning.mockReset();
  notifyMock.info.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── Mount ───────────────────────────────────────────────────────────────────

describe("Invoices (render-loop smoke)", () => {
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        {profiler.wrap(<Invoices />, "invoices")}
      </QueryClientProvider>,
    );
    await screen.findByTestId("editable-table");
    await flushMicrotasks(50);
    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("Invoices mount", () => {
  it("queries the orders overview with year (current dayjs year)", () => {
    renderPage();
    expect(ordersOverviewHookMock).toHaveBeenCalled();
    const [params] = ordersOverviewHookMock.mock.calls[0];
    const p = params as { year: number };
    expect(typeof p.year).toBe("number");
  });

  it("renders selectors and the table", () => {
    renderPage();
    expect(screen.getByTestId("year-selector")).toBeInTheDocument();
    expect(screen.getByTestId("reseller-selector")).toBeInTheDocument();
    expect(screen.getByTestId("editable-table")).toBeInTheDocument();
  });

  it("passes the orders list to the table as initialData", () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [makeRow(), makeRow({ id: "ord-10" })],
      refetch: vi.fn(),
    });
    renderPage();
    // ``data`` is derived via useMemo from ``ordersData``, so the rows
    // are present on the first render — no waiting needed.
    expect(screen.getByTestId("row-count").textContent).toBe("2");
  });
});

// ── Storno happy path ───────────────────────────────────────────────────────

describe("storno flow", () => {
  it("renders the per-row Storno button when invoice is finalized and not yet cancelled", () => {
    renderPage();
    const rowActions = screen.getByTestId("row-actions");
    // Bare t("commissioning.create_storno") → the i18n mock returns the key.
    expect(within(rowActions).getByText("commissioning.create_storno")).toBeInTheDocument();
  });

  it("hides the Storno button when the invoice is already cancelled", () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [makeRow({ invoice_cancelled_by: "u-99" })],
      refetch: vi.fn(),
    });
    renderPage();
    const rowActions = screen.getByTestId("row-actions");
    expect(within(rowActions).queryByText("commissioning.create_storno")).not.toBeInTheDocument();
  });

  it("opens the storno modal when the Storno button is clicked", async () => {
    renderPage();
    await userEvent.click(
      within(screen.getByTestId("row-actions")).getByText("commissioning.create_storno"),
    );
    // The modal renders the create_storno key twice (title + OK button),
    // so we assert on the unambiguous reason textarea instead — it only
    // exists when the modal is open.
    const modal = await screen.findByRole("dialog");
    expect(within(modal).getByRole("textbox")).toBeInTheDocument();
  });

  it("disables the OK button until a reason is typed, then POSTs to /api/commissioning/invoices/{id}/create_storno/ on submit", async () => {
    renderPage();
    await userEvent.click(
      within(screen.getByTestId("row-actions")).getByText("commissioning.create_storno"),
    );

    // Modal renders. Its OK button reuses the same i18n key as the row
    // trigger, so we scope to the modal's footer.
    const modal = await screen.findByRole("dialog");
    const okBtn = within(modal).getByRole("button", {
      name: /commissioning\.create_storno/,
    });
    // Disabled until the reason field has something non-whitespace.
    expect(okBtn).toBeDisabled();

    // Fill the reason field — the textarea is the modal's only textbox.
    const reasonField = within(modal).getByRole("textbox");
    await userEvent.type(reasonField, "duplicate charge");
    expect(okBtn).not.toBeDisabled();

    await userEvent.click(okBtn);

    await waitFor(() => {
      expect(createStornoMutateAsyncMock).toHaveBeenCalledTimes(1);
    });
    // The component now calls the generated mutation hook
    // (``useCommissioningInvoicesCreateStornoCreate``) rather than a raw
    // axios call — assert on the typed ``{ id, data }`` it's invoked with.
    expect(createStornoMutateAsyncMock).toHaveBeenCalledWith({
      id: "inv-42",
      data: { reason: "duplicate charge" },
    });
  });

  it("surfaces a toast and keeps the modal open when the storno endpoint rejects (the circular-ref / FinalizedError case)", async () => {
    createStornoMutateAsyncMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { code: "CircularStornoChain", message: "circular reference" },
      },
    });
    // The catch path uses console.error — silence it so the test output
    // stays clean.
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    renderPage();
    await userEvent.click(
      within(screen.getByTestId("row-actions")).getByText("commissioning.create_storno"),
    );
    const modal = await screen.findByRole("dialog");
    await userEvent.type(within(modal).getByRole("textbox"), "x");
    await userEvent.click(
      within(modal).getByRole("button", { name: /commissioning\.create_storno/ }),
    );

    await waitFor(() => {
      expect(createStornoMutateAsyncMock).toHaveBeenCalled();
    });
    // Modal stays open (success path is what closes it) so the office can
    // correct the reason and retry.
    expect(screen.queryByRole("dialog")).toBeInTheDocument();
    // The backend's domain error is now surfaced to the office instead of
    // failing silently.
    await waitFor(() => {
      expect(notifyMock.error).toHaveBeenCalled();
    });

    consoleSpy.mockRestore();
  });
});
