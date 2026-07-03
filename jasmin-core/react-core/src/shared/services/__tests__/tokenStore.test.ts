import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
  subscribeAccessToken,
} from "../tokenStore";

afterEach(() => {
  // Always end clean — the store is module-scoped, so state leaks between tests.
  clearAccessToken();
});

describe("tokenStore", () => {
  it("returns null before any token has been set", () => {
    expect(getAccessToken()).toBeNull();
  });

  it("setAccessToken / getAccessToken round-trips a value", () => {
    setAccessToken("abc.def.ghi");
    expect(getAccessToken()).toBe("abc.def.ghi");
  });

  it("clearAccessToken resets the value to null", () => {
    setAccessToken("token");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });

  it("notifies subscribers on every change with the new value", () => {
    const cb = vi.fn();
    subscribeAccessToken(cb);

    setAccessToken("first");
    setAccessToken("second");
    clearAccessToken();

    expect(cb).toHaveBeenCalledTimes(3);
    expect(cb).toHaveBeenNthCalledWith(1, "first");
    expect(cb).toHaveBeenNthCalledWith(2, "second");
    expect(cb).toHaveBeenNthCalledWith(3, null);
  });

  it("returns an unsubscribe function that stops further notifications", () => {
    const cb = vi.fn();
    const unsubscribe = subscribeAccessToken(cb);

    setAccessToken("one");
    unsubscribe();
    setAccessToken("two");

    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith("one");
  });

  it("isolates a throwing subscriber from the rest", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const noisy = vi.fn(() => {
      throw new Error("boom");
    });
    const quiet = vi.fn();

    subscribeAccessToken(noisy);
    subscribeAccessToken(quiet);

    setAccessToken("x");

    expect(noisy).toHaveBeenCalledOnce();
    expect(quiet).toHaveBeenCalledWith("x");
    errorSpy.mockRestore();
  });
});
