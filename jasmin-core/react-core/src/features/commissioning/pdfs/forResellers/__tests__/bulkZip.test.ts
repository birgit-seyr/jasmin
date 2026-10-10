/**
 * downloadRecordsZip: the shared skeleton of the reseller documents' bulk ZIP
 * download. A failed lookup, a record without an entry and a failing entry
 * builder each count as one skipped record; nothing left to zip is a notice,
 * not an empty download.
 */
import type { TFunction } from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { notifyMock, downloadBlobMock, zipFilesToBlobMock } = vi.hoisted(() => ({
  notifyMock: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() },
  downloadBlobMock: vi.fn(),
  zipFilesToBlobMock: vi.fn(),
}));

vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  downloadBlob: downloadBlobMock,
  zipFilesToBlob: zipFilesToBlobMock,
}));

import { downloadRecordsZip } from "../bulkZip";

const t = ((key: string, options?: { count?: number }) =>
  options?.count != null ? `${key}:${options.count}` : key) as unknown as TFunction;

interface Doc {
  id: string;
  file?: string;
}

const entryFor = (doc: Doc) =>
  doc.file ? { name: `${doc.id}.pdf`, blob: new Blob([doc.file]) } : null;

const run = (
  ids: string[],
  retrieve: (id: string) => Promise<Doc>,
  buildEntry: (doc: Doc) => ReturnType<typeof entryFor> | Promise<ReturnType<typeof entryFor>> = entryFor,
) =>
  downloadRecordsZip<Doc>({
    ids,
    retrieve,
    buildEntry,
    emptyKey: "empty",
    skippedKey: "skipped",
    zipFilename: "docs.zip",
    t,
  });

describe("downloadRecordsZip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    zipFilesToBlobMock.mockResolvedValue(new Blob(["zip"]));
  });

  it("notifies and fetches nothing for an empty selection", async () => {
    const retrieve = vi.fn();
    await run([], retrieve);
    expect(notifyMock.info).toHaveBeenCalledWith("empty");
    expect(retrieve).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });

  it("zips every record's entry and downloads it under the zip name", async () => {
    await run(["a", "b"], async (id) => ({ id, file: "x" }));
    expect(zipFilesToBlobMock).toHaveBeenCalledWith([
      expect.objectContaining({ name: "a.pdf" }),
      expect.objectContaining({ name: "b.pdf" }),
    ]);
    expect(downloadBlobMock).toHaveBeenCalledWith(expect.any(Blob), "docs.zip");
    expect(notifyMock.warning).not.toHaveBeenCalled();
  });

  it("counts a failed lookup, a record without an entry and a failing builder as skipped", async () => {
    const retrieve = async (id: string) => {
      if (id === "missing") throw new Error("404");
      return { id, file: id === "no-file" ? undefined : "x" };
    };
    const buildEntry = (doc: Doc) => {
      if (doc.id === "broken") throw new Error("render failed");
      return entryFor(doc);
    };

    await run(["ok", "missing", "no-file", "broken"], retrieve, buildEntry);

    expect(zipFilesToBlobMock).toHaveBeenCalledWith([expect.objectContaining({ name: "ok.pdf" })]);
    expect(downloadBlobMock).toHaveBeenCalledTimes(1);
    expect(notifyMock.warning).toHaveBeenCalledWith("skipped:3");
  });

  it("notifies instead of downloading when no record qualifies", async () => {
    await run(["a"], async (id) => ({ id }));
    expect(notifyMock.info).toHaveBeenCalledWith("empty");
    expect(zipFilesToBlobMock).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });

  it("awaits an asynchronous entry builder", async () => {
    await run(["a"], async (id) => ({ id, file: "x" }), async (doc) => entryFor(doc));
    expect(downloadBlobMock).toHaveBeenCalledTimes(1);
  });
});
