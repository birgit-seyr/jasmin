import { describe, expect, it } from "vitest";
import { shouldRetryQuery } from "../queryRetry";

const failedWith = (status: number) => ({
  isAxiosError: true,
  response: { status, data: {} },
});

describe("shouldRetryQuery", () => {
  it.each([400, 401, 403, 404, 409, 422, 429])(
    "shows a %i at once",
    (status) => {
      expect(shouldRetryQuery(0, failedWith(status))).toBe(false);
    },
  );

  it.each([500, 502, 503, 504])("retries a %i up to three times", (status) => {
    expect(shouldRetryQuery(0, failedWith(status))).toBe(true);
    expect(shouldRetryQuery(2, failedWith(status))).toBe(true);
    expect(shouldRetryQuery(3, failedWith(status))).toBe(false);
  });

  it("retries a network error without a response up to three times", () => {
    const networkError = { isAxiosError: true, message: "Network Error" };
    expect(shouldRetryQuery(0, networkError)).toBe(true);
    expect(shouldRetryQuery(3, networkError)).toBe(false);
  });

  it("retries an error that isn't from a request up to three times", () => {
    expect(shouldRetryQuery(0, new Error("boom"))).toBe(true);
    expect(shouldRetryQuery(3, new Error("boom"))).toBe(false);
  });
});
