import type { TFunction } from "i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ── Mocks ───────────────────────────────────────────────────────────────────

const { notifyMock, downloadBlobMock, zipFilesToBlobMock, retrieveMock } =
  vi.hoisted(() => ({
    notifyMock: {
      info: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
      success: vi.fn(),
    },
    downloadBlobMock: vi.fn(),
    zipFilesToBlobMock: vi.fn(),
    retrieveMock: vi.fn(),
  }));

vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  downloadBlob: downloadBlobMock,
  zipFilesToBlob: zipFilesToBlobMock,
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningDeliveryNotesRetrieve: retrieveMock,
}));

vi.mock("../pdfDownload", () => ({
  // ``<Label>-<prefix>-<number>.pdf`` — enough to assert the entry name.
  deliveryNotePdfFilename: (
    _t: TFunction,
    prefix: unknown,
    number: unknown,
  ) => `Lieferschein-${prefix}-${number}.pdf`,
}));

import { downloadSelectedDeliveryNotePdfsZip } from "../bulkDeliveryNoteZip";

// Bare-key translator; interpolation options are ignored (tests assert on key).
const t = ((key: string) => key) as unknown as TFunction;

function makeDeliveryNote(overrides: Record<string, unknown> = {}) {
  return {
    id: "dn-1",
    prefix: "LS",
    number: 1,
    file: "https://files.test/dn-1.pdf",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  zipFilesToBlobMock.mockResolvedValue(new Blob(["zip"]));
  global.fetch = vi.fn().mockResolvedValue({
    blob: async () => new Blob(["pdf"]),
  } as Response);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("downloadSelectedDeliveryNotePdfsZip", () => {
  it("shows a subtle info notice and downloads nothing when no ids are given", async () => {
    await downloadSelectedDeliveryNotePdfsZip([], t, "delivery_notes.zip");

    expect(notifyMock.info).toHaveBeenCalledWith(
      "download.bulk_zip_no_finalized_delivery_notes",
    );
    expect(retrieveMock).not.toHaveBeenCalled();
    expect(zipFilesToBlobMock).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });

  it("bundles the stored PDFs of qualifying delivery notes and triggers the ZIP download", async () => {
    retrieveMock.mockImplementation(async (id: string) =>
      makeDeliveryNote({ id, number: id === "dn-2" ? 2 : 1 }),
    );

    await downloadSelectedDeliveryNotePdfsZip(
      ["dn-1", "dn-2"],
      t,
      "delivery_notes.zip",
    );

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(zipFilesToBlobMock).toHaveBeenCalledTimes(1);
    const entries = zipFilesToBlobMock.mock.calls[0][0] as { name: string }[];
    expect(entries.map((e) => e.name)).toEqual([
      "Lieferschein-LS-1.pdf",
      "Lieferschein-LS-2.pdf",
    ]);
    expect(downloadBlobMock).toHaveBeenCalledWith(
      expect.any(Blob),
      "delivery_notes.zip",
    );
    expect(notifyMock.warning).not.toHaveBeenCalled();
  });

  it("skips delivery notes missing the stored PDF (no file) and warns about the skips", async () => {
    retrieveMock.mockImplementation(async (id: string) =>
      id === "dn-2"
        ? makeDeliveryNote({ id, file: null })
        : makeDeliveryNote({ id }),
    );

    await downloadSelectedDeliveryNotePdfsZip(
      ["dn-1", "dn-2"],
      t,
      "delivery_notes.zip",
    );

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(downloadBlobMock).toHaveBeenCalledTimes(1);
    expect(notifyMock.warning).toHaveBeenCalledWith(
      "download.bulk_zip_some_skipped_delivery_notes",
    );
  });

  it("shows the info notice (not a download) when none of the finalized delivery notes have a stored PDF", async () => {
    retrieveMock.mockResolvedValue(makeDeliveryNote({ file: null }));

    await downloadSelectedDeliveryNotePdfsZip(["dn-1"], t, "delivery_notes.zip");

    expect(zipFilesToBlobMock).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
    expect(notifyMock.info).toHaveBeenCalledWith(
      "download.bulk_zip_no_finalized_delivery_notes",
    );
  });
});
