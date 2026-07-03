import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";

import { TenantContext } from "@shared/contexts/TenantContext";
import { useNumberFormat } from "../useNumberFormat";

/**
 * Minimal TenantContext provider — enough for `useTenant().getSetting`
 * to return what we want. Mirrors the shape used by the real
 * TenantProvider; matches the pattern in `useTenant.test.tsx`.
 */
function makeTenantWrapper(numberLocale: string | undefined) {
  const getSetting = (key: string, defaultValue: unknown = null) => {
    if (key === "number_locale") return numberLocale ?? defaultValue;
    return defaultValue;
  };

  const value = {
    tenant: null,
    currentTenant: null,
    loading: false,
    error: null,
    getSetting,
    getCurrentSetting: getSetting,
    getCurrency: () => "EUR",
    getTimezone: () => "UTC",
  } as unknown as Parameters<typeof TenantContext.Provider>[0]["value"];

  return ({ children }: { children: ReactNode }) => (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  );
}

describe("useNumberFormat", () => {
  it("reads number_locale from the tenant and formats accordingly", () => {
    const { result } = renderHook(() => useNumberFormat(), {
      wrapper: makeTenantWrapper("de-DE"),
    });
    expect(result.current.locale).toBe("de-DE");
    expect(result.current.format(12.34, 2)).toBe("12,34");
    expect(result.current.format("98.00", 2)).toBe("98,00");
  });

  it("flips behaviour when the tenant locale flips", () => {
    const { result: de } = renderHook(() => useNumberFormat(), {
      wrapper: makeTenantWrapper("de-DE"),
    });
    const { result: us } = renderHook(() => useNumberFormat(), {
      wrapper: makeTenantWrapper("en-US"),
    });
    expect(de.current.format(1234.5, 2)).toBe("1.234,50");
    expect(us.current.format(1234.5, 2)).toBe("1,234.50");
  });

  it("falls back to de-DE when the tenant setting is missing", () => {
    const { result } = renderHook(() => useNumberFormat(), {
      wrapper: makeTenantWrapper(undefined),
    });
    expect(result.current.locale).toBe("de-DE");
  });

  it("exposes a `parse` that round-trips the locale's display format", () => {
    const { result } = renderHook(() => useNumberFormat(), {
      wrapper: makeTenantWrapper("de-DE"),
    });
    const displayed = result.current.format(1234.56, 2); // "1.234,56"
    expect(result.current.parse(displayed)).toBe(1234.56);
  });
});
