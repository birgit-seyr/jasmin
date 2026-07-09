/**
 * @vitest-environment node
 *
 * The zip util reads blobs via ``Blob.arrayBuffer()``. jsdom's Blob does not
 * implement it, so run this suite in Node's env where the native Blob does.
 */
import { unzipSync, strFromU8 } from "fflate";
import { describe, expect, it } from "vitest";

import { zipFilesToBlob } from "../zip";

async function unzip(blob: Blob): Promise<Record<string, string>> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const files = unzipSync(bytes);
  const out: Record<string, string> = {};
  for (const [name, data] of Object.entries(files)) {
    out[name] = strFromU8(data);
  }
  return out;
}

describe("zipFilesToBlob", () => {
  it("bundles each entry under its name and round-trips the bytes", async () => {
    const blob = await zipFilesToBlob([
      { name: "a.txt", blob: new Blob(["hello"]) },
      { name: "b.txt", blob: new Blob(["world"]) },
    ]);

    expect(blob.type).toBe("application/zip");
    const contents = await unzip(blob);
    expect(contents).toEqual({ "a.txt": "hello", "b.txt": "world" });
  });

  it("disambiguates duplicate names with a (n) suffix instead of dropping one", async () => {
    const blob = await zipFilesToBlob([
      { name: "Rechnung-RE-1.pdf", blob: new Blob(["first"]) },
      { name: "Rechnung-RE-1.pdf", blob: new Blob(["second"]) },
    ]);

    const contents = await unzip(blob);
    expect(Object.keys(contents).sort()).toEqual([
      "Rechnung-RE-1(2).pdf",
      "Rechnung-RE-1.pdf",
    ]);
    expect(contents["Rechnung-RE-1.pdf"]).toBe("first");
    expect(contents["Rechnung-RE-1(2).pdf"]).toBe("second");
  });

  it("produces an empty but valid archive for no entries", async () => {
    const blob = await zipFilesToBlob([]);
    const contents = await unzip(blob);
    expect(contents).toEqual({});
  });
});
