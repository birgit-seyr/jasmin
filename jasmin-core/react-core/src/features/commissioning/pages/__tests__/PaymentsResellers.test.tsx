/**
 * Tier-4 integration smoke for the resellers ``PaymentsResellers`` page.
 *
 * Three things this test owns (everything else lives in separately-tested
 * seams: BulkActionButton, EditableTable, the API client, etc.):
 *
 *   1. Mount + query wiring — ``useCommissioningOrdersOverviewList`` is
 *      called with ``year/delivery_week/reseller`` derived from
 *      ``WeekSelector`` / ``ResellerSelector`` defaults.
 *   2. "Finalize blocks edits" — the page filters ``initialData`` down to
 *      rows where ``has_finalized_invoice`` is true. Unfinalized rows
 *      never reach the EditableTable, so the office can't accidentally
 *      mark payment on something that isn't actually invoiced yet.
 *      The ``showOnlyNotPaid`` switch further narrows the visible rows.
 *   3. Per-row + bulk wiring — the per-row "set to paid" button only
 *      renders when the row is unpaid, and the three bulk actions
 *      (paid / unpaid / send reminders) hit
 *      ``commissioningBulkSetToPaidDocumentsCreate`` /
 *      ``commissioningBulkSendInvoiceRemindersViaEmailCreate``
 *      with ``{ ids, model: "invoice" }`` — and with ``{ undo: true }``
 *      for the set-to-unpaid variant.
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

// notify must come from vi.hoisted — the factory references it as a
// direct property value inside the BulkActionButton stub below.
const { notifyMock, isPastFlag } = vi.hoisted(() => ({
  notifyMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  // The page now derives ``isPast`` from ``isWeekInPast(year, week)`` instead
  // of a WeekSelector ``onPastChange`` callback. Drive it via this flag.
  isPastFlag: { value: false },
}));
vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  getErrorMessage: (err: unknown, fallback?: string) => {
    const e = err as { response?: { data?: { message?: string } } };
    return e?.response?.data?.message ?? fallback ?? "Action failed";
  },
  isWeekInPast: () => isPastFlag.value,
}));

vi.mock("@shared/services/api", () => ({ default: vi.fn() }));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  // Real implementation — it's a pure React-state hook (no API/tenant deps),
  // and these tests exercise actual row-selection behaviour.
  const { useTableRowSelection } = await import(
    "@hooks/useTableRowSelection"
  );
  const { useYearWeekState, currentYear, currentWeek } = await import(
    "@hooks/useYearWeekState"
  );
  const tenant = makeUseTenantMock({
    tenant: { id: "t-1" },
    logoUrl: "https://example.test/logo.png",
  });
  return {
    useTenant: () => tenant,
    useTableRowSelection,
    useYearWeekState,
    currentYear,
    currentWeek,
    useDateFormat: () => ({ formatDate: (iso?: string | null) => iso ?? "" }),
    useCurrency: () => ({ currencySymbol: "€" }),
    useNumberFormat: () => ({ format: (n: number, d: number) => n.toFixed(d) }),
    // useNoteColumn returns the object spread into the columns array — the
    // real hook is just glue around a single EditableColumnConfig.
    useNoteColumn: () => ({
      noteColumn: {
        title: "Note",
        dataIndex: "note",
        key: "note",
        readOnly: false,
        disabled: false,
      },
    }),
    // No-op stub: the page uses the helper to gate list-query
    // invalidation, but in tests we don't care about cache refresh.
    useInvalidateAfterTableMutation: () => ({
      onSaveSuccess: () => {},
      onDeleteSuccess: () => {},
    }),
  };
});

// useRoles is consumed via the page's permission gate. ``isOffice: true``
// keeps the table editable, which is what we want for these tests.
vi.mock("@shared/auth", () => ({
  useRoles: () => ({ isOffice: true, isMember: false, isAdmin: false }),
}));

// ── Generated API mocks ─────────────────────────────────────────────────────

const ordersOverviewHookMock = vi.fn();
const ordersOverviewListFnMock = vi.fn();
const bulkSetToPaidMock = vi.fn();
const bulkSendRemindersMock = vi.fn();
const setInvoiceNotePatchMock = vi.fn();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningOrdersOverviewList: (params: unknown, opts?: unknown) =>
    ordersOverviewHookMock(params, opts),
  commissioningOrdersOverviewList: (...args: unknown[]) =>
    ordersOverviewListFnMock(...args),
  commissioningBulkSetToPaidDocumentsCreate: (...args: unknown[]) =>
    bulkSetToPaidMock(...args),
  commissioningBulkSendInvoiceRemindersViaEmailCreate: (...args: unknown[]) =>
    bulkSendRemindersMock(...args),
  commissioningSetInvoiceNotePartialUpdate: (...args: unknown[]) =>
    setInvoiceNotePatchMock(...args),
  getCommissioningOrdersOverviewListQueryKey: (p?: unknown) => ["orders", p],
}));

// ── Sub-component stubs ─────────────────────────────────────────────────────

// The page derives ``isPast`` from ``isWeekInPast(year, week)``. The stub flips
// the ``isPastFlag`` and changes the selected week so the page's ``isWeekInPast``
// useMemo (deps: year/week) recomputes — exercising the past-week behaviour.
vi.mock("@shared/selectors", () => ({
  WeekSelector: ({
    selectedWeek,
    setSelectedWeek,
  }: {
    selectedWeek?: number | null;
    setSelectedWeek?: (value: number | null) => void;
  }) => (
    <div data-testid="week-selector">
      <button
        data-testid="mark-as-past"
        onClick={() => {
          isPastFlag.value = true;
          setSelectedWeek?.((selectedWeek ?? 1) === 1 ? 2 : 1);
        }}
      >
        mark-past
      </button>
    </div>
  ),
  ResellerSelector: () => <div data-testid="reseller-selector" />,
}));

vi.mock("@shared/ui", () => ({
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer">{children}</div>
  ),
  ToolTipIcon: () => null,
  // LabeledSwitch — render a native checkbox so userEvent.click drives
  // ``onChange`` with the next boolean. ``showOnlyNotPaid`` is the only
  // switch on the page.
  LabeledSwitch: ({
    value,
    onChange,
    label,
  }: {
    value: boolean;
    onChange: (next: boolean) => void;
    label: React.ReactNode;
  }) => (
    <label>
      <input
        type="checkbox"
        data-testid="show-only-not-paid"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  ),
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

// EditableTable stub: expose a row-count probe, a select-all hook, AND
// render the first row's actions column so the per-row "set to paid"
// button is reachable from the test (mirrors the Invoices test pattern).
vi.mock("@shared/tables", async () => {
  // wrapApiFunctions is pure (type-only deps) — use the real one.
  const { wrapApiFunctions } = await import(
    "@shared/tables/BasicEditableTable/wrapApiFunctions"
  );
  return {
    READ_ONLY_PERMISSION: {},
    wrapApiFunctions,
    // gatedByPermissionOnlyEdit must return *something* truthy — the page
    // memoises it but doesn't read individual fields in this test surface.
    gatedByPermissionOnlyEdit: (isOffice: boolean) => ({
      canEdit: isOffice,
      canDelete: false,
    }),
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
            data-testid="select-all"
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

import PaymentsResellers from "../PaymentsResellers";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeRow(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "ord-1",
    invoice_id: "inv-1",
    invoice_date: "2026-05-21",
    invoice_number: "RE-2026-001",
    has_finalized_invoice: true,
    invoice_has_been_sent_to_reseller: false,
    invoice_has_been_sent_to_accounting: false,
    has_been_paid: false,
    sum_netto: "120.00",
    note: "",
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
      <PaymentsResellers />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  isPastFlag.value = false;
  ordersOverviewHookMock.mockReset().mockReturnValue({
    data: [makeRow()],
    refetch: vi.fn(),
  });
  ordersOverviewListFnMock.mockReset().mockResolvedValue([]);
  bulkSetToPaidMock.mockReset().mockResolvedValue({ results: [] });
  bulkSendRemindersMock.mockReset().mockResolvedValue({ results: [] });
  setInvoiceNotePatchMock.mockReset();
  notifyMock.success.mockReset();
  notifyMock.error.mockReset();
  notifyMock.warning.mockReset();
  notifyMock.info.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── Mount ───────────────────────────────────────────────────────────────────

describe("PaymentsResellers (render-loop smoke)", () => {
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        {profiler.wrap(<PaymentsResellers />, "payments-resellers")}
      </QueryClientProvider>,
    );
    await screen.findByTestId("editable-table");
    await flushMicrotasks(50);
    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("PaymentsResellers mount", () => {
  it("queries the orders overview with year + delivery_week derived from dayjs", () => {
    renderPage();
    expect(ordersOverviewHookMock).toHaveBeenCalled();
    const [params] = ordersOverviewHookMock.mock.calls[0];
    const p = params as {
      year: number;
      delivery_week?: number;
      reseller?: string;
    };
    expect(typeof p.year).toBe("number");
    expect(typeof p.delivery_week).toBe("number");
    // Reseller defaults to null → undefined in the listParams memo.
    expect(p.reseller).toBeUndefined();
  });

  it("renders header, selectors, the show-only-not-paid switch, the explainer, and the table", () => {
    renderPage();
    expect(screen.getByText("commissioning.payments")).toBeInTheDocument();
    expect(screen.getByTestId("week-selector")).toBeInTheDocument();
    expect(screen.getByTestId("reseller-selector")).toBeInTheDocument();
    expect(screen.getByTestId("show-only-not-paid")).toBeInTheDocument();
    expect(screen.getByTestId("editable-table")).toBeInTheDocument();
    expect(screen.getByTestId("explainer")).toBeInTheDocument();
  });
});

// ── "Finalize blocks edits" filter ──────────────────────────────────────────

describe("filteredData — only finalized invoices reach the table", () => {
  it("drops rows where has_finalized_invoice is false", () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [
        makeRow({ id: "ord-1", has_finalized_invoice: true }),
        makeRow({ id: "ord-2", has_finalized_invoice: false }),
        makeRow({ id: "ord-3", has_finalized_invoice: true }),
      ],
      refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByTestId("row-count").textContent).toBe("2");
  });

  it("further narrows to unpaid rows when the showOnlyNotPaid switch is on", async () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [
        makeRow({ id: "ord-1", has_been_paid: false }),
        makeRow({ id: "ord-2", has_been_paid: true }),
        makeRow({ id: "ord-3", has_been_paid: false }),
      ],
      refetch: vi.fn(),
    });
    renderPage();
    // Before flipping the switch: all three finalized rows render.
    expect(screen.getByTestId("row-count").textContent).toBe("3");
    await userEvent.click(screen.getByTestId("show-only-not-paid"));
    await waitFor(() =>
      expect(screen.getByTestId("row-count").textContent).toBe("2"),
    );
  });
});

// ── Per-row action ──────────────────────────────────────────────────────────

describe("per-row Set-to-paid button", () => {
  it("renders the per-row 'set to paid' button only when the row is unpaid", () => {
    renderPage();
    const rowActions = screen.getByTestId("row-actions");
    expect(
      within(rowActions).getByText("commissioning.set_to_paid"),
    ).toBeInTheDocument();
  });

  it("hides the per-row button once the row is already paid", () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [makeRow({ has_been_paid: true })],
      refetch: vi.fn(),
    });
    renderPage();
    const rowActions = screen.getByTestId("row-actions");
    expect(
      within(rowActions).queryByText("commissioning.set_to_paid"),
    ).not.toBeInTheDocument();
  });

  it("calls bulkSetToPaid with the single row id when the per-row button fires", async () => {
    renderPage();
    const rowActions = screen.getByTestId("row-actions");
    await userEvent.click(
      within(rowActions).getByText("commissioning.set_to_paid"),
    );
    await waitFor(() => {
      expect(bulkSetToPaidMock).toHaveBeenCalledTimes(1);
    });
    const arg = bulkSetToPaidMock.mock.calls[0][0] as {
      ids: (string | number)[];
      model: string;
    };
    expect(arg.ids).toEqual(["ord-1"]);
    expect(arg.model).toBe("invoice");
  });
});

// ── Bulk actions ────────────────────────────────────────────────────────────

describe("bulk action bar", () => {
  const SET_PAID_TESTID = "bulk-commissioning.set_to_paid_bulk";
  const SET_UNPAID_TESTID = "bulk-commissioning.set_to_unpaid_bulk";
  const SEND_REMINDERS_TESTID =
    "bulk-commissioning.send_reminders_bulk_via_email";

  it("hides the bulk action bar when the selected week is in the past", async () => {
    renderPage();
    // Before: the bulk-action bar is mounted and all three buttons render.
    expect(screen.getByTestId(SET_PAID_TESTID)).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("mark-as-past"));
    await waitFor(() =>
      expect(screen.queryByTestId(SET_PAID_TESTID)).not.toBeInTheDocument(),
    );
    expect(screen.queryByTestId(SET_UNPAID_TESTID)).not.toBeInTheDocument();
    expect(
      screen.queryByTestId(SEND_REMINDERS_TESTID),
    ).not.toBeInTheDocument();
  });

  it("disables all three bulk buttons until at least one row is selected", () => {
    renderPage();
    expect(screen.getByTestId(SET_PAID_TESTID)).toBeDisabled();
    expect(screen.getByTestId(SET_UNPAID_TESTID)).toBeDisabled();
    expect(screen.getByTestId(SEND_REMINDERS_TESTID)).toBeDisabled();
  });

  it("disables 'set unpaid' when the only selected row is already unpaid", async () => {
    renderPage();
    await userEvent.click(screen.getByTestId("select-all"));
    expect(screen.getByTestId(SET_UNPAID_TESTID)).toBeDisabled();
    // The other two should now be enabled for an unpaid row.
    expect(screen.getByTestId(SET_PAID_TESTID)).not.toBeDisabled();
    expect(screen.getByTestId(SEND_REMINDERS_TESTID)).not.toBeDisabled();
  });

  it("disables 'send reminders' (and 'set paid') when the only selected row is already paid", async () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [makeRow({ has_been_paid: true })],
      refetch: vi.fn(),
    });
    renderPage();
    await userEvent.click(screen.getByTestId("select-all"));
    expect(screen.getByTestId(SEND_REMINDERS_TESTID)).toBeDisabled();
    expect(screen.getByTestId(SET_PAID_TESTID)).toBeDisabled();
    expect(screen.getByTestId(SET_UNPAID_TESTID)).not.toBeDisabled();
  });

  it("posts { ids, model: 'invoice' } when set-to-paid bulk fires", async () => {
    renderPage();
    await userEvent.click(screen.getByTestId("select-all"));
    await userEvent.click(screen.getByTestId(SET_PAID_TESTID));
    await waitFor(() => {
      expect(bulkSetToPaidMock).toHaveBeenCalledTimes(1);
    });
    const arg = bulkSetToPaidMock.mock.calls[0][0] as {
      ids: (string | number)[];
      model: string;
    };
    expect(arg.ids).toEqual(["ord-1"]);
    expect(arg.model).toBe("invoice");
  });

  it("passes { undo: true } as the second arg when set-to-unpaid bulk fires", async () => {
    ordersOverviewHookMock.mockReturnValue({
      data: [makeRow({ has_been_paid: true })],
      refetch: vi.fn(),
    });
    renderPage();
    await userEvent.click(screen.getByTestId("select-all"));
    await userEvent.click(screen.getByTestId(SET_UNPAID_TESTID));
    await waitFor(() => {
      expect(bulkSetToPaidMock).toHaveBeenCalledTimes(1);
    });
    // The page's apiFunction calls
    //   commissioningBulkSetToPaidDocumentsCreate(payload, { undo: true })
    // — verify both args reach the underlying call. `undo` is a boolean: the
    // param is catalogued as a bool and the generated client types it as one
    // (it serialises to the same `?undo=true` on the wire).
    const call = bulkSetToPaidMock.mock.calls[0];
    expect(call[0]).toMatchObject({ ids: ["ord-1"], model: "invoice" });
    expect(call[1]).toEqual({ undo: true });
  });

  it("posts { ids, model: 'invoice' } when send-reminders-bulk fires", async () => {
    renderPage();
    await userEvent.click(screen.getByTestId("select-all"));
    await userEvent.click(screen.getByTestId(SEND_REMINDERS_TESTID));
    await waitFor(() => {
      expect(bulkSendRemindersMock).toHaveBeenCalledTimes(1);
    });
    const arg = bulkSendRemindersMock.mock.calls[0][0] as {
      ids: (string | number)[];
      model: string;
    };
    expect(arg.ids).toEqual(["ord-1"]);
    expect(arg.model).toBe("invoice");
  });

  it("surfaces notify.error when the bulk endpoint rejects (FinalizedError-style)", async () => {
    bulkSetToPaidMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 409,
        data: { code: "FinalizedError", message: "Cannot edit a finalized invoice" },
      },
    });
    renderPage();
    await userEvent.click(screen.getByTestId("select-all"));
    await userEvent.click(screen.getByTestId(SET_PAID_TESTID));
    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith(
        "Cannot edit a finalized invoice",
      ),
    );
    expect(notifyMock.success).not.toHaveBeenCalled();
  });
});
