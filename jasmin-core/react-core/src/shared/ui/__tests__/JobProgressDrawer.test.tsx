/**
 * ``JobProgressDrawer`` lists every per-item outcome of a finished job: the
 * per-order jobs report their failures in ``result.errors``, the offers job
 * inside ``result.results``, and both have to show up with their reason.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { useJobMock } = vi.hoisted(() => ({ useJobMock: vi.fn() }));

vi.mock("@hooks/useJob", () => ({ useJob: useJobMock }));

import { JobProgressDrawer } from "../JobProgressDrawer";

const finishedJob = (result: Record<string, unknown>) => ({
  data: { id: "job-1", status: "done", progress: {}, result },
  isLoading: false,
});

beforeEach(() => {
  useJobMock.mockReset();
});

describe("JobProgressDrawer", () => {
  it("lists the sent, the already sent and the failed orders of a document send", () => {
    useJobMock.mockReturnValue(
      finishedJob({
        total_processed: 3,
        successful: 2,
        failed: 1,
        results: [
          {
            order_id: "ord-1",
            order_number: "BE-1",
            document_number: "RE-1",
            success: true,
          },
          {
            order_id: "ord-2",
            order_number: "BE-2",
            document_number: "RE-2",
            success: true,
            already_sent: true,
          },
        ],
        errors: [
          {
            order_id: "ord-3",
            order_number: "BE-3",
            error: "PDF not yet uploaded",
            success: false,
          },
        ],
      }),
    );

    render(<JobProgressDrawer jobId="job-1" onClose={vi.fn()} />);

    expect(screen.getByText("RE-1")).toBeInTheDocument();
    expect(screen.getByText("RE-2")).toBeInTheDocument();
    expect(screen.getByText("BE-3")).toBeInTheDocument();
    expect(screen.getByText("PDF not yet uploaded")).toBeInTheDocument();
    expect(screen.getByText("job_progress.already_sent")).toBeInTheDocument();
    expect(screen.getByText("job_progress.failure")).toBeInTheDocument();
  });

  it("keys each row by its order or reseller, never by its position", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    useJobMock.mockReturnValue(
      finishedJob({
        results: [
          { order_id: "ord-1", document_number: "RE-1", success: true },
          { reseller_id: "res-1", reseller_name: "Hofladen", success: true },
        ],
        errors: [{ order_id: "ord-3", error: "PDF not yet uploaded", success: false }],
      }),
    );

    render(<JobProgressDrawer jobId="job-1" onClose={vi.fn()} />);

    const rowKeys = Array.from(document.querySelectorAll("tr[data-row-key]")).map((row) =>
      row.getAttribute("data-row-key"),
    );
    expect(rowKeys).toEqual(["ord-1", "res-1", "ord-3"]);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("rowKey");
    consoleError.mockRestore();
  });

  it("still lists a failure the offers job keeps inside its results", () => {
    useJobMock.mockReturnValue(
      finishedJob({
        results: [
          {
            reseller_id: "res-1",
            reseller_name: "Hofladen",
            success: false,
            error: "No email address",
          },
        ],
      }),
    );

    render(<JobProgressDrawer jobId="job-1" onClose={vi.fn()} />);

    expect(screen.getByText("Hofladen")).toBeInTheDocument();
    expect(screen.getByText("No email address")).toBeInTheDocument();
  });
});
