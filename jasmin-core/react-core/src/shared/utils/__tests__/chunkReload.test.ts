import { beforeEach, describe, expect, it, vi } from "vitest";

import { isDynamicImportError, reloadOnceForChunkError } from "../chunkReload";

describe("isDynamicImportError", () => {
  it("detects a failed dynamic import across browser phrasings", () => {
    for (const msg of [
      "Failed to fetch dynamically imported module: https://x/Abos-abc.js", // Chrome
      "error loading dynamically imported module: https://x/Abos.js", // Firefox
      "Importing a module script failed.", // Safari
      "504 (Outdated Optimize Dep)", // Vite dev re-optimization
      "Unable to preload CSS for /assets/Abos.css",
    ]) {
      expect(isDynamicImportError(new Error(msg))).toBe(true);
    }
    expect(
      isDynamicImportError(Object.assign(new Error("x"), { name: "ChunkLoadError" })),
    ).toBe(true);
  });

  it("ignores ordinary app errors and non-errors", () => {
    expect(
      isDynamicImportError(new Error("Cannot read properties of undefined")),
    ).toBe(false);
    expect(isDynamicImportError(null)).toBe(false);
    expect(isDynamicImportError(undefined)).toBe(false);
    expect(isDynamicImportError("a string")).toBe(false);
  });
});

describe("reloadOnceForChunkError", () => {
  const reloadMock = vi.fn();

  beforeEach(() => {
    window.sessionStorage.clear();
    // jsdom's ``location.reload`` throws "Not implemented" — replace it.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload: reloadMock },
    });
    reloadMock.mockClear();
  });

  it("reloads once, then the loop-guard blocks a storm", () => {
    expect(reloadOnceForChunkError()).toBe(true);
    expect(reloadMock).toHaveBeenCalledTimes(1);
    // A second failure right away (chunk genuinely broken) must NOT reload again.
    expect(reloadOnceForChunkError()).toBe(false);
    expect(reloadMock).toHaveBeenCalledTimes(1);
  });
});
