// useOnboardingMode reads the tenant's onboarding_mode setting and treats only a
// stored true as on.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

const tenantState = vi.hoisted(() => ({
  settings: {} as Record<string, unknown>,
}));

vi.mock("@shared/hooks/configuration/useTenant", () => ({
  useTenant: () => ({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.settings ? tenantState.settings[key] : defaultValue,
  }),
}));

import { useOnboardingMode } from "../configuration/useOnboardingMode";

beforeEach(() => {
  tenantState.settings = {};
});

describe("useOnboardingMode", () => {
  it("is on when the setting is true", () => {
    tenantState.settings = { onboarding_mode: true };
    const { result } = renderHook(() => useOnboardingMode());
    expect(result.current).toBe(true);
  });

  it("is off when the setting is false", () => {
    tenantState.settings = { onboarding_mode: false };
    const { result } = renderHook(() => useOnboardingMode());
    expect(result.current).toBe(false);
  });

  it("is off when the tenant has no such setting", () => {
    const { result } = renderHook(() => useOnboardingMode());
    expect(result.current).toBe(false);
  });

  it("is off for a truthy value that isn't true", () => {
    tenantState.settings = { onboarding_mode: "true" };
    const { result } = renderHook(() => useOnboardingMode());
    expect(result.current).toBe(false);
  });
});
