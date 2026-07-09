/**
 * Tier-4 integration smoke for the resellers ``DeliveryNotes`` page.
 *
 * Focused on the two things the page actually owns (everything else
 * lives in separately-tested seams: BulkActionButton, EditableTable,
 * the API client, etc.):
 *
 *   1. The query fires with the right ``year/delivery_week/reseller``
 *      params and the page mounts cleanly.
 *   2. The bulk-finalize button wires through to
 *      ``commissioningBulkFinalizeDocumentsCreate`` with the right
 *      ``{ ids, model }`` payload — and when that call rejects with a
 *      409 ``FinalizedError`` (the plan-item we care about), the
 *      shared ``notify.error`` toast fires via ``BulkActionButton``'s
 *      built-in catch path.
 *
 * Everything below the action bar (EditableTable rows, per-row action
 * cell, modal contents) is stubbed — covering it again here would
 * duplicate seam tests.
 */

import { render, screen, waitFor } from "@testing-library/react";
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

// Notify must come from vi.hoisted — the factory references it as a
// direct property value (see CustomerOrderPage test for the canonical
// case where lazy wrapping wasn't possible).
const { notifyMock } = vi.hoisted(() => ({
  notifyMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  getErrorMessage: (err: unknown, fallback?: string) => {
    const e = err as { response?: { data?: { message?: string } } };
    return e?.response?.data?.message ?? fallback ?? "Action failed";
  },
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  // Real implementation — it's a pure React-state hook (no API/tenant deps),
  // and these tests exercise actual row-selection behaviour.
  const { useTableRowSelection } = await import(
    "@hooks/useTableRowSelection"
  );
  // Pure React-state hook (+ its module-const currentYear/currentWeek) — use
  // the real implementation so year/week selection behaves as in production.
  const { useYearWeekState, currentYear, currentWeek } = await import(
    "@hooks/useYearWeekState"
  );
  const tenant = makeUseTenantMock({
    tenant: { id: "t-1" },
    logoUrl: "https://example.test/logo.png",
  });
  return {
    useTenant: () => tenant,
    useDateFormat: () => ({
      formatDate: (iso?: string | null) => iso ?? "",
    }),
    useTableRowSelection,
    useYearWeekState,
    currentYear,
    currentWeek,
  };
});

vi.mock("@shared/services/api", () => ({
  default: vi.fn(),
}));

// ── Generated API mocks ─────────────────────────────────────────────────────

const ordersOverviewListHookMock = vi.fn();
const ordersOverviewListFnMock = vi.fn();
const bulkFinalizeMock = vi.fn();
const bulkCreateDocsMock = vi.fn();
const bulkDeleteDocsMock = vi.fn();
const dnContentsCreateMock = vi.fn();
const dnContentsPatchMock = vi.fn();
const dnDestroyMock = vi.fn();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningOrdersOverviewList: (params: unknown, opts?: unknown) =>
    ordersOverviewListHookMock(params, opts),
  commissioningOrdersOverviewList: (...args: unknown[]) =>
    ordersOverviewListFnMock(...args),
  commissioningBulkFinalizeDocumentsCreate: (...args: unknown[]) =>
    bulkFinalizeMock(...args),
  commissioningBulkCreateDocumentsFromOrdersCreate: (...args: unknown[]) =>
    bulkCreateDocsMock(...args),
  commissioningBulkDeleteDocumentsCreate: (...args: unknown[]) =>
    bulkDeleteDocsMock(...args),
  commissioningDeliveryNoteContentsCreate: (...args: unknown[]) =>
    dnContentsCreateMock(...args),
  commissioningDeliveryNoteContentsPartialUpdate: (...args: unknown[]) =>
    dnContentsPatchMock(...args),
  commissioningDeliveryNotesDestroy: (...args: unknown[]) =>
    dnDestroyMock(...args),
}));

// ── Sub-component stubs ─────────────────────────────────────────────────────

vi.mock("@features/commissioning/modals", () => ({
  DeliveryNoteModal: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="delivery-note-modal" /> : null,
}));

vi.mock("@features/commissioning/pdfs", () => ({
  DeliveryNotePDFButtons: () => <div data-testid="dn-pdf-buttons" />,
  generateAndUploadDeliveryNotePDF: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@shared/selectors", () => ({
  WeekSelector: () => <div data-testid="week-selector" />,
  ResellerSelector: () => <div data-testid="reseller-selector" />,
}));

vi.mock("@shared/ui", () => ({
  // Keep ExplainerText and ViewDetailsButton tiny — they're presentational.
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer">{children}</div>
  ),
  ViewDetailsButton: () => <button>view-details</button>,
  // The page renders ``BulkActionButton`` directly with apiFunction +
  // selectedIds. We mirror just enough of its real behaviour to surface
  // the catch → notify.error path — that's the FinalizedError plan item.
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
          notifyMock.error(
            e?.response?.data?.message ?? "Action failed",
          );
        }
      }}
    >
      {buttonText}
    </button>
  ),
}));

// EditableTable stub: expose a "select-first-row" button so we can drive
// rowSelection without dragging the real table behaviour into this test.
vi.mock("@shared/tables", async () => {
  // wrapApiFunctions is pure (type-only deps) — use the real one.
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  return {
    READ_ONLY_PERMISSION: {},
    wrapApiFunctions,
    EditableTable: ({
      onSelectedRowsChange,
      initialData,
    }: {
      onSelectedRowsChange?: (ids: (string | number)[]) => void;
      initialData?: Array<{ id: string | number }>;
    }) => (
      <div data-testid="editable-table">
        <button
          onClick={() =>
            onSelectedRowsChange?.(initialData?.map((r) => r.id) ?? [])
          }
        >
          select-all
        </button>
        <span data-testid="row-count">{initialData?.length ?? 0}</span>
      </div>
    ),
  };
});

import DeliveryNotes from "../DeliveryNotes";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeRow(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "ord-1",
    order_date: "2026-05-20",
    order_number: "BE-2026-001",
    order_is_finalized: false,
    reseller_name: "Acme Co",
    has_delivery_note: true,
    delivery_note_id: "dn-7",
    delivery_note_date: "2026-05-21",
    delivery_note_number: "LS-2026-001",
    delivery_note_is_finalized: false,
    delivery_note_has_been_sent_to_reseller: false,
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
      <DeliveryNotes />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  ordersOverviewListHookMock.mockReset().mockReturnValue({
    data: [makeRow()],
    refetch: vi.fn(),
  });
  ordersOverviewListFnMock.mockReset();
  bulkFinalizeMock.mockReset().mockResolvedValue({ results: [] });
  bulkCreateDocsMock.mockReset().mockResolvedValue({ results: [] });
  bulkDeleteDocsMock.mockReset().mockResolvedValue({ results: [] });
  dnContentsCreateMock.mockReset();
  dnContentsPatchMock.mockReset();
  dnDestroyMock.mockReset();
  notifyMock.success.mockReset();
  notifyMock.error.mockReset();
  notifyMock.warning.mockReset();
  notifyMock.info.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("DeliveryNotes (render-loop smoke)", () => {
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        {profiler.wrap(<DeliveryNotes />, "delivery-notes")}
      </QueryClientProvider>,
    );
    await screen.findByTestId("editable-table");
    await flushMicrotasks(50);
    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("DeliveryNotes mount", () => {
  it("queries the orders overview with year + delivery_week (current ISO week defaults)", () => {
    renderPage();
    expect(ordersOverviewListHookMock).toHaveBeenCalled();
    const [params] = ordersOverviewListHookMock.mock.calls[0];
    const p = params as { year: number; delivery_week?: number };
    // currentYear / currentWeek are computed from dayjs at module load.
    // We don't pin the values — just verify the shape.
    expect(typeof p.year).toBe("number");
    expect(typeof p.delivery_week).toBe("number");
  });

  it("renders the page header, the selectors, the table, and the explainer", () => {
    renderPage();
    expect(screen.getByText("commissioning.delivery_notes")).toBeInTheDocument();
    expect(screen.getByTestId("week-selector")).toBeInTheDocument();
    expect(screen.getByTestId("reseller-selector")).toBeInTheDocument();
    expect(screen.getByTestId("editable-table")).toBeInTheDocument();
    expect(screen.getByTestId("explainer")).toBeInTheDocument();
  });

  it("hands the orders list into the EditableTable as initialData", () => {
    ordersOverviewListHookMock.mockReturnValue({
      data: [makeRow(), makeRow({ id: "ord-2" })],
      refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByTestId("row-count").textContent).toBe("2");
  });
});

// ── Bulk finalize button wiring ─────────────────────────────────────────────

describe("bulk finalize button", () => {
  // The "Finalize delivery notes" bulk button uses the page's
  // ``bulkFinalizeDocuments`` callback which wraps
  // ``commissioningBulkFinalizeDocumentsCreate``. The disabled state is
  // computed from the row-selection + finalized flag.
  const FINALIZE_BUTTON_TESTID = "bulk-commissioning.finalize_delivery_notes";

  it("is disabled until at least one row is selected", () => {
    renderPage();
    expect(screen.getByTestId(FINALIZE_BUTTON_TESTID)).toBeDisabled();
  });

  it("stays disabled when the selection contains an already-finalized row", async () => {
    ordersOverviewListHookMock.mockReturnValue({
      data: [makeRow({ delivery_note_is_finalized: true })],
      refetch: vi.fn(),
    });
    renderPage();
    await userEvent.click(screen.getByText("select-all"));
    expect(screen.getByTestId(FINALIZE_BUTTON_TESTID)).toBeDisabled();
  });

  it("calls commissioningBulkFinalizeDocumentsCreate with { ids, model: delivery_note } when fired with a fresh row selected", async () => {
    renderPage();
    await userEvent.click(screen.getByText("select-all"));
    const btn = screen.getByTestId(FINALIZE_BUTTON_TESTID);
    expect(btn).not.toBeDisabled();
    await userEvent.click(btn);

    await waitFor(() => {
      expect(bulkFinalizeMock).toHaveBeenCalledTimes(1);
    });
    const arg = bulkFinalizeMock.mock.calls[0][0] as {
      ids: (string | number)[];
      model: string;
    };
    expect(arg.ids).toEqual(["ord-1"]);
    expect(arg.model).toBe("delivery_note");
  });

  it("surfaces a notify.error toast when the backend bounces with a 409 FinalizedError", async () => {
    // Mimic the axios error shape that getErrorMessage understands.
    const finalizedError = {
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          code: "FinalizedError",
          message: "Already finalized — unfinalize the invoice first.",
        },
      },
    };
    bulkFinalizeMock.mockRejectedValueOnce(finalizedError);

    renderPage();
    await userEvent.click(screen.getByText("select-all"));
    await userEvent.click(screen.getByTestId(FINALIZE_BUTTON_TESTID));

    await waitFor(() => {
      expect(notifyMock.error).toHaveBeenCalledWith(
        "Already finalized — unfinalize the invoice first.",
      );
    });
    expect(notifyMock.success).not.toHaveBeenCalled();
  });
});
