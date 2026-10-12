// @vitest-environment node
/**
 * downloadCsvBlob: every saved CSV starts with exactly one UTF-8 BOM, whether
 * the frontend built the text or the backend wrote the file with its own BOM.
 * Runs in node, whose Blob reads its bytes back (jsdom's lacks `arrayBuffer`);
 * the browser download is recorded instead of saved.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const downloads = vi.hoisted(() => ({ files: [] as { name: string; blob: Blob }[] }));
vi.mock("../downloadBlob", () => ({
  downloadBlob: (blob: Blob, filename: string) => {
    downloads.files.push({ name: filename, blob });
  },
}));

import { downloadCsvBlob } from "../csv";

const BOM = [0xef, 0xbb, 0xbf];
const CSV = "Nr;Name\n1;Karotten\n";

async function savedBytes(): Promise<number[]> {
  expect(downloads.files).toHaveLength(1);
  return [...new Uint8Array(await downloads.files[0].blob.arrayBuffer())];
}

const utf8 = (text: string) => [...new TextEncoder().encode(text)];

beforeEach(() => {
  downloads.files = [];
});

describe("downloadCsvBlob", () => {
  it("prepends a BOM to a string without one", async () => {
    await downloadCsvBlob(CSV, "members");

    expect(await savedBytes()).toEqual([...BOM, ...utf8(CSV)]);
    expect(downloads.files[0].name).toBe("members.csv");
    expect(downloads.files[0].blob.type).toBe("text/csv;charset=utf-8;");
  });

  it("saves a string at once, before the returned promise settles", () => {
    void downloadCsvBlob(CSV, "members.csv");

    expect(downloads.files.map((file) => file.name)).toEqual(["members.csv"]);
  });

  it("keeps the single BOM of a string that has one", async () => {
    await downloadCsvBlob(`﻿${CSV}`, "members");

    expect(await savedBytes()).toEqual([...BOM, ...utf8(CSV)]);
  });

  it("prepends a BOM to a blob without one", async () => {
    await downloadCsvBlob(new Blob([CSV]), "members");

    expect(await savedBytes()).toEqual([...BOM, ...utf8(CSV)]);
  });

  it("keeps the single BOM of a backend blob that has one", async () => {
    await downloadCsvBlob(new Blob([`﻿${CSV}`], { type: "text/csv" }), "members");

    expect(await savedBytes()).toEqual([...BOM, ...utf8(CSV)]);
    expect(downloads.files[0].blob.type).toBe("text/csv;charset=utf-8;");
  });

  it("prepends a BOM to a blob shorter than one", async () => {
    await downloadCsvBlob(new Blob(["a"]), "members");

    expect(await savedBytes()).toEqual([...BOM, ...utf8("a")]);
  });

  it("reads the BOM of binary content that is not a blob", async () => {
    await downloadCsvBlob(new Uint8Array([...BOM, ...utf8(CSV)]), "members");

    expect(await savedBytes()).toEqual([...BOM, ...utf8(CSV)]);
  });
});
