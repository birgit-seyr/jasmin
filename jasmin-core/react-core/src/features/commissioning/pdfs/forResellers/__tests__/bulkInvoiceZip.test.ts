import type { TFunction } from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Mocks ───────────────────────────────────────────────────────────────────

const {
  notifyMock,
  downloadBlobMock,
  zipFilesToBlobMock,
  retrieveMock,
  buildZugferdBlobMock,
} = vi.hoisted(() => ({
  notifyMock: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
  },
  downloadBlobMock: vi.fn(),
  zipFilesToBlobMock: vi.fn(),
  retrieveMock: vi.fn(),
  buildZugferdBlobMock: vi.fn(),
}));

vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  downloadBlob: downloadBlobMock,
  zipFilesToBlob: zipFilesToBlobMock,
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningInvoicesRetrieve: retrieveMock,
}));

vi.mock("../pdfDownload", () => ({
  buildZugferdBlob: buildZugferdBlobMock,
  // ``<Label>-<prefix>-<number>.pdf`` — enough to assert the entry name.
  invoicePdfFilename: (
    _t: TFunction,
    prefix: unknown,
    number: unknown,
  ) => `Rechnung-${prefix}-${number}.pdf`,
}));

import { downloadSelectedInvoiceEpdfsZip } from "../bulkInvoiceZip";

// Bare-key translator; interpolation options are ignored (tests assert on key).
const t = ((key: string) => key) as unknown as TFunction;

function makeInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: "inv-1",
    prefix: "RE",
    number: 1,
    file: "https://files.test/inv-1.pdf",
    xml_file: "https://files.test/inv-1.xml",
    document_type: "invoice",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  zipFilesToBlobMock.mockResolvedValue(new Blob(["zip"]));
  buildZugferdBlobMock.mockResolvedValue(new Blob(["epdf"]));
});

describe("downloadSelectedInvoiceEpdfsZip", () => {
  it("shows a subtle info notice and downloads nothing when no ids are given", async () => {
    await downloadSelectedInvoiceEpdfsZip([], t, "invoices.zip");

    expect(notifyMock.info).toHaveBeenCalledWith("download.bulk_zip_no_finalized");
    expect(retrieveMock).not.toHaveBeenCalled();
    expect(zipFilesToBlobMock).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });

  it("bundles the e-PDFs of qualifying invoices and triggers the ZIP download", async () => {
    retrieveMock.mockImplementation(async (id: string) =>
      makeInvoice({ id, number: id === "inv-2" ? 2 : 1 }),
    );

    await downloadSelectedInvoiceEpdfsZip(["inv-1", "inv-2"], t, "invoices.zip");

    expect(buildZugferdBlobMock).toHaveBeenCalledTimes(2);
    expect(zipFilesToBlobMock).toHaveBeenCalledTimes(1);
    const entries = zipFilesToBlobMock.mock.calls[0][0] as { name: string }[];
    expect(entries.map((e) => e.name)).toEqual([
      "Rechnung-RE-1.pdf",
      "Rechnung-RE-2.pdf",
    ]);
    expect(downloadBlobMock).toHaveBeenCalledWith(expect.any(Blob), "invoices.zip");
    expect(notifyMock.warning).not.toHaveBeenCalled();
  });

  it("skips invoices missing the e-PDF (no xml_file) and warns about the skips", async () => {
    retrieveMock.mockImplementation(async (id: string) =>
      id === "inv-2"
        ? makeInvoice({ id, xml_file: null })
        : makeInvoice({ id }),
    );

    await downloadSelectedInvoiceEpdfsZip(["inv-1", "inv-2"], t, "invoices.zip");

    expect(buildZugferdBlobMock).toHaveBeenCalledTimes(1);
    expect(downloadBlobMock).toHaveBeenCalledTimes(1);
    expect(notifyMock.warning).toHaveBeenCalledWith("download.bulk_zip_some_skipped");
  });

  it("shows the info notice (not a download) when none of the finalized invoices have an e-PDF", async () => {
    retrieveMock.mockResolvedValue(makeInvoice({ file: null, xml_file: null }));

    await downloadSelectedInvoiceEpdfsZip(["inv-1"], t, "invoices.zip");

    expect(zipFilesToBlobMock).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
    expect(notifyMock.info).toHaveBeenCalledWith("download.bulk_zip_no_finalized");
  });
});
