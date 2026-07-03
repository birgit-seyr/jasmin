import { describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";

import { getErrorMessage } from "../apiError";

/** Build a synthetic AxiosError carrying the given response body. */
function axiosErrorWith(data: unknown, status = 400): AxiosError {
  const err = new AxiosError(
    "Request failed",
    "ERR_BAD_REQUEST",
    undefined,
    null,
    {
      data,
      status,
      statusText: "Bad Request",
      headers: {},
      config: { headers: new AxiosHeaders() } as never,
    },
  );
  // Axios sets isAxiosError on the prototype; the helper reads it as an own key.
  (err as unknown as { isAxiosError: boolean }).isAxiosError = true;
  return err;
}

describe("getErrorMessage", () => {
  it("returns the canonical Jasmin message", () => {
    const err = axiosErrorWith({
      code: "share.past_week",
      message: "You can't edit a finalised week.",
    });
    expect(getErrorMessage(err)).toBe("You can't edit a finalised week.");
  });

  it("falls back to legacy { error } shape", () => {
    const err = axiosErrorWith({ error: "Legacy boom" });
    expect(getErrorMessage(err)).toBe("Legacy boom");
  });

  it("falls back to DRF { detail } shape", () => {
    const err = axiosErrorWith({ detail: "Not found." });
    expect(getErrorMessage(err)).toBe("Not found.");
  });

  it("falls back to the first DRF field error", () => {
    const err = axiosErrorWith({
      email: ["Enter a valid email."],
      password: ["Too short."],
    });
    expect(getErrorMessage(err)).toBe("Enter a valid email.");
  });

  it("uses the supplied fallback for non-axios errors", () => {
    expect(getErrorMessage({}, "Default")).toBe("Default");
  });

  it("uses Error.message for thrown JS errors", () => {
    expect(getErrorMessage(new Error("Plain JS"))).toBe("Plain JS");
  });
});
