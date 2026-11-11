// @vitest-environment node
// jsdom's Blob can't be read back as text; a download's body is read in Node.
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it, vi } from "vitest";

// The real i18n setup reads the DOM; no code here has a keyed message.
vi.mock("@shared/i18n", () => ({ default: { t: (key: string) => key } }));

import { getErrorDetails, getErrorMessage, readBlobErrorBody } from "../apiError";

/** A failed blob request as axios hands it over, its body still a Blob. */
function blobError(body: Blob, status: number): AxiosError {
  const err = new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, null, {
    data: body,
    status,
    statusText: "",
    headers: {},
    config: { headers: new AxiosHeaders() } as never,
  });
  (err as unknown as { isAxiosError: boolean }).isAxiosError = true;
  return err;
}

describe("readBlobErrorBody", () => {
  it("reads the JSON error a download got back", async () => {
    const body = new Blob(
      [
        JSON.stringify({
          code: "scale_unit.unsupported",
          message: "The scale can't sell PLU 7 in its unit.",
          details: { plu_numbers: "7" },
        }),
      ],
      { type: "application/json" },
    );

    const err = await readBlobErrorBody(blobError(body, 409));

    expect(getErrorMessage(err, "Export failed")).toBe(
      "The scale can't sell PLU 7 in its unit.",
    );
    expect(getErrorDetails(err)).toEqual({ plu_numbers: "7" });
  });

  it("leaves a body that isn't JSON to the fallback", async () => {
    const body = new Blob(["<html>Bad gateway</html>"], { type: "text/html" });

    const err = await readBlobErrorBody(blobError(body, 502));

    expect(getErrorMessage(err, "Export failed")).toBe("Export failed");
  });

  it("passes an error without a response on unchanged", async () => {
    const err = new Error("offline");

    expect(await readBlobErrorBody(err)).toBe(err);
  });
});
