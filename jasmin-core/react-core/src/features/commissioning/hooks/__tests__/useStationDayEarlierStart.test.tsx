/**
 * useStationDayEarlierStart: in onboarding mode a saved station day may move
 * back, but not before its delivery day starts nor into the station's earlier
 * row for the same delivery day.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareDeliveryDayOption } from "../useShareDeliveryDays";

const tenantSettings = vi.hoisted(() => ({ onboarding_mode: true as unknown }));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "onboarding_mode" ? tenantSettings.onboarding_mode : defaultValue,
  });
  return { useTenant: () => tenant };
});

import { useStationDayEarlierStart } from "../useStationDayEarlierStart";

const deliveryDays = [
  { id: "tue", value: "tue", label: "Tue", valid_from: "2025-03-03" },
  { id: "thu", value: "thu", label: "Thu", valid_from: "2026-06-01" },
] as unknown as ShareDeliveryDayOption[];

const rows = [
  { key: "old-tue", id: "old-tue", delivery_day: "tue", valid_from: "2025-03-03", valid_until: "2025-12-28" },
  { key: "new-tue", id: "new-tue", delivery_day: "tue", valid_from: "2026-03-02", valid_until: null },
  { key: "thu", id: "thu", delivery_day: "thu", valid_from: "2026-09-07", valid_until: null },
];

const windowFor = (id: string) => {
  const { result } = renderHook(() => useStationDayEarlierStart(rows, deliveryDays));
  return result.current({ key: id, id });
};

beforeEach(() => {
  tenantSettings.onboarding_mode = true;
});

describe("useStationDayEarlierStart", () => {
  it("floors a row at the day after its earlier row of the same delivery day", () => {
    const window = windowFor("new-tue");
    expect(window?.savedStart.format("YYYY-MM-DD")).toBe("2026-03-02");
    expect(window?.floor?.format("YYYY-MM-DD")).toBe("2025-12-29");
  });

  it("floors a row at its delivery day's start when that is later", () => {
    expect(windowFor("thu")?.floor?.format("YYYY-MM-DD")).toBe("2026-06-01");
  });

  it("ignores another delivery day's rows", () => {
    expect(windowFor("old-tue")?.floor?.format("YYYY-MM-DD")).toBe("2025-03-03");
  });

  it("opens no window outside onboarding mode", () => {
    tenantSettings.onboarding_mode = false;
    expect(windowFor("new-tue")).toBeNull();
  });
});
