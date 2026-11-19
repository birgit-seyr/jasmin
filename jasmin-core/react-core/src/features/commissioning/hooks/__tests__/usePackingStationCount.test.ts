import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Per-test tenant settings; a setting left out takes the caller's default.
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, fallback?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : fallback,
  });
  return { useTenant: () => tenant };
});

import { usePackingStationCount } from "../usePackingStationCount";

const count = () => renderHook(() => usePackingStationCount()).result.current;

beforeEach(() => {
  tenantSettings.values = {};
});

describe("usePackingStationCount", () => {
  it("is the farm's setting where boxes are packed", () => {
    tenantSettings.values = { packing_mode: "BOXES", number_packing_stations: 3 };
    expect(count()).toBe(3);

    tenantSettings.values = { packing_mode: "MIXED", number_packing_stations: 2 };
    expect(count()).toBe(2);
  });

  it("is one where every size goes out loose, whatever is stored", () => {
    tenantSettings.values = { packing_mode: "BULK", number_packing_stations: 3 };

    expect(count()).toBe(1);
  });

  it("is one for a farm that hasn't set it", () => {
    expect(count()).toBe(1);
  });
});
