import { describe, expect, it, vi } from "vitest";
import { render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";

import { TenantContext } from "@shared/contexts/TenantContext";
import { useTenant } from "../useTenant";

interface FakeTenant {
  settings?: Record<string, unknown>;
  current_settings?: Record<string, unknown>;
}

function makeProvider(tenant: FakeTenant | null) {
  // Build the same shape the real TenantProvider exposes — just enough of it
  // to drive getSetting / getCurrency / getTimezone.
  const getSetting = (key: string, defaultValue: unknown = null) => {
    if (!tenant?.settings) return defaultValue;
    const keys = key.split(".");
    let value: unknown = tenant.settings;
    for (const k of keys) {
      if (value && typeof value === "object" && k in value) {
        value = (value as Record<string, unknown>)[k];
      } else {
        return defaultValue;
      }
    }
    return value;
  };

  const getCurrency = () => getSetting("currency", "EUR");
  const getTimezone = () => getSetting("timezone", "UTC");

  const value = {
    tenant,
    currentTenant: tenant,
    loading: false,
    error: null,
    getSetting,
    getCurrentSetting: getSetting,
    getCurrency,
    getTimezone,
  } as unknown as Parameters<typeof TenantContext.Provider>[0]["value"];

  return ({ children }: { children: ReactNode }) => (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  );
}

describe("useTenant", () => {
  it("throws a clear error when used outside a TenantProvider", () => {
    // React logs the throw; suppress noise.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Probe() {
      useTenant();
      return null;
    }
    expect(() => render(<Probe />)).toThrow(
      "useTenant must be used within a TenantProvider",
    );
    spy.mockRestore();
  });

  it("returns the context value when wrapped in a provider", () => {
    const { result } = renderHook(() => useTenant(), {
      wrapper: makeProvider({ settings: { currency: "EUR" } }),
    });
    expect(result.current.getCurrency()).toBe("EUR");
  });
});

describe("useTenant().getSetting", () => {
  it("walks dotted keys into nested settings", () => {
    const { result } = renderHook(() => useTenant(), {
      wrapper: makeProvider({
        settings: {
          members: { allows_trial_members: true, trial_days: 30 },
        },
      }),
    });
    expect(result.current.getSetting("members.allows_trial_members")).toBe(
      true,
    );
    expect(result.current.getSetting("members.trial_days")).toBe(30);
  });

  it("returns the provided default when a dotted key misses anywhere on the path", () => {
    const { result } = renderHook(() => useTenant(), {
      wrapper: makeProvider({
        settings: { members: { allows_trial_members: true } },
      }),
    });
    expect(
      result.current.getSetting("members.does_not_exist", "fallback"),
    ).toBe("fallback");
    expect(result.current.getSetting("nonexistent.deep.path", 42)).toBe(42);
  });

  it("uses the function's default value (null) when the dotted key misses and no default is given", () => {
    const { result } = renderHook(() => useTenant(), {
      wrapper: makeProvider({ settings: {} }),
    });
    expect(result.current.getSetting("anything")).toBeNull();
  });

  it("never confuses a falsy value (0, false, '') for missing", () => {
    const { result } = renderHook(() => useTenant(), {
      wrapper: makeProvider({
        settings: { count: 0, on: false, label: "" },
      }),
    });
    expect(result.current.getSetting("count", 99)).toBe(0);
    expect(result.current.getSetting("on", true)).toBe(false);
    expect(result.current.getSetting("label", "x")).toBe("");
  });
});
