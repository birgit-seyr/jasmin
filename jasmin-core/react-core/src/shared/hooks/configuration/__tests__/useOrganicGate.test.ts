import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useOrganicGate } from "../useOrganicGate";

// useOrganicGate's only dependency is useTenant — mock it so the gate logic
// (trim + non-empty) is tested in isolation, with no TenantContext/i18n load.
const mockUseTenant = vi.fn();
vi.mock("../useTenant", () => ({
  useTenant: () => mockUseTenant(),
}));

describe("useOrganicGate", () => {
  const gate = (organic_control_number: unknown) => {
    mockUseTenant.mockReturnValue({ tenant: { organic_control_number } });
    return renderHook(() => useOrganicGate()).result.current;
  };

  it("is enabled and echoes the control number when it is non-empty", () => {
    const r = gate("DE-ÖKO-001");
    expect(r.enabled).toBe(true);
    expect(r.controlNumber).toBe("DE-ÖKO-001");
  });

  it("is disabled when the control number is missing or empty", () => {
    expect(gate(undefined).enabled).toBe(false);
    expect(gate(null).enabled).toBe(false);
    expect(gate("").enabled).toBe(false);
  });

  it("treats a whitespace-only control number as disabled (trimmed)", () => {
    const r = gate("   ");
    expect(r.enabled).toBe(false);
    expect(r.controlNumber).toBe("");
  });

  it("trims surrounding whitespace from the control number", () => {
    const r = gate("  DE-1  ");
    expect(r.enabled).toBe(true);
    expect(r.controlNumber).toBe("DE-1");
  });

  it("is disabled when there is no tenant", () => {
    mockUseTenant.mockReturnValue({ tenant: null });
    expect(
      renderHook(() => useOrganicGate()).result.current.enabled,
    ).toBe(false);
  });
});
