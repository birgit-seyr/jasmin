/**
 * ImportShares — what the page does with a validation-failed preview/apply.
 *
 * A 400 from either action carries the batch that failed: preview returns its
 * fields at the top level, apply nests them under ``batch``. The page has to
 * render THAT batch's per-row report — leaving the previously selected batch
 * on screen shows the office a stale (often empty) error table for a file that
 * was just rejected — toast the refusal rather than a raw batch field, and
 * refresh the history list the backend has already moved on.
 *
 * Everything around the two actions (selectors, explainer, mappings modal) is
 * stubbed; the API boundary is mocked rather than going through MSW. The error
 * extractor is deliberately NOT mocked: what reaches the toast is the whole
 * point of these tests.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@shared/i18n";

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

// Referenced as a direct property value of the factory below, so it has to
// come from vi.hoisted.
const { notifyMock } = vi.hoisted(() => ({
  notifyMock: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));
vi.mock("@shared/utils", () => ({ notify: notifyMock }));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

vi.mock("@shared/selectors", () => ({
  WeekSelector: () => <div data-testid="week-selector" />,
}));

vi.mock("@shared/ui", () => ({
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer">{children}</div>
  ),
}));

vi.mock("@features/commissioning/modals", () => ({
  ExternalCodeMappingsModal: () => <div data-testid="mappings-modal" />,
}));

const previewMock = vi.fn();
const applyMock = vi.fn();
const uploadMock = vi.fn();

const LIST_QUERY_KEY = ["share-import-batches"];

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningShareImportBatchesPreviewCreate: (...args: unknown[]) =>
    previewMock(...args),
  commissioningShareImportBatchesApplyCreate: (...args: unknown[]) =>
    applyMock(...args),
  commissioningShareImportBatchesUploadCreate: (...args: unknown[]) =>
    uploadMock(...args),
  getCommissioningShareImportBatchesListQueryKey: () => ["share-import-batches"],
  useCommissioningShareImportBatchesList: () => ({
    data: [selectableBatch],
    isFetching: false,
  }),
}));

// ── Fixtures ────────────────────────────────────────────────────────────────

// The batch the office picks from the history table: validated, no row errors.
const selectableBatch = {
  id: "batch-1",
  original_filename: "week15.csv",
  year: 2026,
  delivery_week: 15,
  status: "validated",
  row_count: 3,
  error_count: 0,
  validation_report: {},
  diff_report: {},
  created_at: "2026-04-01T09:00:00Z",
  applied_at: null,
};

const ROW_ERROR = "unknown delivery_station_code STN-NOPE";

// What the 400 carries: the same batch, re-validated and now failing.
const failedBatch = {
  ...selectableBatch,
  status: "failed",
  error_count: 1,
  validation_report: { "2": [ROW_ERROR] },
};

// The code/message pair the viewset puts beside the batch, verbatim.
const VALIDATION_FAILED_BODY = {
  code: "share_import.validation_failed",
  message: "Some rows in the file are invalid, so the import was not applied.",
};

/** What the real extractor should produce for a code that has a locale entry. */
function expectedToastFor(code: string): string {
  const translated = i18n.t(`errors.${code}`);
  return translated === `errors.${code}` ? "" : translated;
}

function rejection(data: unknown) {
  return Object.assign(new Error("Request failed with status code 400"), {
    isAxiosError: true,
    response: { status: 400, data },
  });
}

import ImportShares from "../ImportShares";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <ImportShares />
    </QueryClientProvider>,
  );
  return { invalidateQueries };
}

/** Select the history row, which is what puts a batch on screen to act on. */
async function selectBatch(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("week15.csv"));
  await screen.findByText("import_shares.preview_btn");
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("ImportShares validation-failed handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the per-row report from a failed preview's 400 body", async () => {
    // Preview returns the batch fields at the top level, next to code/message.
    previewMock.mockRejectedValue(
      rejection({ ...failedBatch, ...VALIDATION_FAILED_BODY }),
    );
    const user = userEvent.setup();
    renderPage();
    await selectBatch(user);

    // The selected batch has no row errors, so the table starts empty.
    expect(screen.queryByText(ROW_ERROR)).not.toBeInTheDocument();

    await user.click(screen.getByText("import_shares.preview_btn"));

    expect(await screen.findByText(ROW_ERROR)).toBeInTheDocument();
  });

  it("renders the per-row report from a failed apply's nested batch", async () => {
    applyMock.mockRejectedValue(
      rejection({
        ...VALIDATION_FAILED_BODY,
        detail: "Validation failed; cannot apply.",
        batch: failedBatch,
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await selectBatch(user);

    await user.click(screen.getByText("import_shares.apply_btn"));

    expect(await screen.findByText(ROW_ERROR)).toBeInTheDocument();
  });

  it("toasts the refusal, not a raw field of the batch beside it", async () => {
    // The real extractor runs here. Without the code/message pair in the body
    // it walks the batch's own fields and toasts the first string it finds —
    // the batch id, a raw identifier the office cannot act on.
    previewMock.mockRejectedValue(
      rejection({ ...failedBatch, ...VALIDATION_FAILED_BODY }),
    );
    const user = userEvent.setup();
    renderPage();
    await selectBatch(user);

    await user.click(screen.getByText("import_shares.preview_btn"));

    await waitFor(() => expect(notifyMock.error).toHaveBeenCalled());
    const toast = notifyMock.error.mock.calls.at(-1)?.[0];
    expect(toast).toBe(expectedToastFor(VALIDATION_FAILED_BODY.code));
    expect(toast).not.toBe(selectableBatch.id);
    expect(toast).not.toBe(failedBatch.original_filename);
    expect(toast).not.toBe("import_shares.action_failed");
  });

  it("refreshes the history list so its row matches the failed batch", async () => {
    // The backend persisted the failure before answering, so the cached row
    // still carries the pre-failure status until the list is invalidated.
    previewMock.mockRejectedValue(
      rejection({ ...failedBatch, ...VALIDATION_FAILED_BODY }),
    );
    const user = userEvent.setup();
    const { invalidateQueries } = renderPage();
    await selectBatch(user);
    invalidateQueries.mockClear();

    await user.click(screen.getByText("import_shares.preview_btn"));

    await waitFor(() =>
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: LIST_QUERY_KEY,
      }),
    );
  });

  it("keeps the batch on screen, and the list untouched, when the failure carries no batch", async () => {
    const code = "share_import.batch_in_terminal_status";
    previewMock.mockRejectedValue(rejection({ code, message: "no" }));
    const user = userEvent.setup();
    const { invalidateQueries } = renderPage();
    await selectBatch(user);
    invalidateQueries.mockClear();

    await user.click(screen.getByText("import_shares.preview_btn"));

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith(expectedToastFor(code)),
    );
    expect(screen.getByText("import_shares.preview_btn")).toBeInTheDocument();
    expect(screen.queryByText(ROW_ERROR)).not.toBeInTheDocument();
    // Nothing was recovered from the error, so there is nothing to resync.
    expect(invalidateQueries).not.toHaveBeenCalled();
  });
});
