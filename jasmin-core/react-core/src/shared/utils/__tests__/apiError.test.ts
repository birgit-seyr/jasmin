import { describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";

import { getErrorMessage, getServerErrorMessage } from "../apiError";

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

  it("keeps a thrown JS error's message ahead of the fallback", () => {
    expect(getErrorMessage(new Error("Translated reason"), "Default")).toBe(
      "Translated reason",
    );
  });

  it("prefers the fallback over axios' text when the server gave no reason", () => {
    expect(getErrorMessage(axiosErrorWith({}, 503), "Speichern fehlgeschlagen")).toBe(
      "Speichern fehlgeschlagen",
    );
  });

  it("prefers the fallback over axios' text for a network failure", () => {
    const err = new AxiosError("Network Error", "ERR_NETWORK");
    (err as unknown as { isAxiosError: boolean }).isAxiosError = true;
    expect(getErrorMessage(err, "Speichern fehlgeschlagen")).toBe(
      "Speichern fehlgeschlagen",
    );
  });

  it("still prefers the server's reason over the fallback", () => {
    expect(
      getErrorMessage(axiosErrorWith({ message: "Mail server down" }, 503), "Default"),
    ).toBe("Mail server down");
  });
});

describe("getServerErrorMessage", () => {
  it("returns the message the server gave", () => {
    expect(getServerErrorMessage(axiosErrorWith({ message: "Mail server down" }))).toBe(
      "Mail server down",
    );
    expect(getServerErrorMessage(axiosErrorWith({ email: ["Enter a valid email."] }))).toBe(
      "Enter a valid email.",
    );
  });

  it.each([
    ["an empty body", axiosErrorWith({}, 503)],
    ["an empty string body", axiosErrorWith("", 503)],
    ["a thrown JS error", new Error("Plain JS")],
    ["anything else", {}],
  ])("returns nothing for %s, leaving the caller its own message", (_, err) => {
    expect(getServerErrorMessage(err)).toBeUndefined();
  });

  it("leaves getErrorMessage without a fallback on the axios text", () => {
    expect(getErrorMessage(axiosErrorWith({}, 503))).toBe("Request failed");
  });
});
