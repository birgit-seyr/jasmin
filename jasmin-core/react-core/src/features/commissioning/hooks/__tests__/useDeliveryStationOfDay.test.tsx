/**
 * useDeliveryStationOfDay keeps the selected station to the delivery day's
 * stations: it picks the day's first one when none is selected, drops a
 * selection the day doesn't serve, and holds still while the list loads.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const stations = vi.hoisted(() => ({
  byDay: {} as Record<string, { value: string; label: string }[]>,
  loading: false,
}));

vi.mock("../useDeliveryStations", () => ({
  useDeliveryStations: ({ delivery_day }: { delivery_day?: string }) => ({
    deliveryStations: stations.loading || !delivery_day ? [] : (stations.byDay[delivery_day] ?? []),
    loading: stations.loading,
    error: null,
  }),
}));

import { useDeliveryStationOfDay } from "../useDeliveryStationOfDay";

const station = (value: string) => ({ value, label: value });

beforeEach(() => {
  stations.loading = false;
  stations.byDay = {
    tue: [station("market"), station("shop")],
    thu: [station("shop")],
    sun: [],
  };
});

describe("useDeliveryStationOfDay", () => {
  it("selects the day's first station", () => {
    const { result } = renderHook(() => useDeliveryStationOfDay("tue"));
    expect(result.current[0]).toBe("market");
    expect(result.current[2]).toBe(true);
  });

  it("leaves the selection empty without selectFirst", () => {
    const { result } = renderHook(() => useDeliveryStationOfDay("tue", { selectFirst: false }));
    expect(result.current[0]).toBeNull();
    expect(result.current[2]).toBe(false);
  });

  it("keeps a selection the new day also serves", () => {
    const { result, rerender } = renderHook(({ day }) => useDeliveryStationOfDay(day), {
      initialProps: { day: "tue" },
    });
    act(() => result.current[1]("shop"));
    rerender({ day: "thu" });
    expect(result.current[0]).toBe("shop");
  });

  it("drops a selection the new day doesn't serve", () => {
    const { result, rerender } = renderHook(
      ({ day }) => useDeliveryStationOfDay(day, { selectFirst: false }),
      { initialProps: { day: "tue" } },
    );
    act(() => result.current[1]("market"));
    rerender({ day: "thu" });
    expect(result.current[0]).toBeNull();
  });

  it("drops the selection on a day without stations", () => {
    const { result, rerender } = renderHook(({ day }) => useDeliveryStationOfDay(day), {
      initialProps: { day: "tue" },
    });
    rerender({ day: "sun" });
    expect(result.current[0]).toBeNull();
    expect(result.current[2]).toBe(false);
  });

  it("keeps the selection while the stations load, but doesn't vouch for it", () => {
    const { result, rerender } = renderHook(({ day }) => useDeliveryStationOfDay(day), {
      initialProps: { day: "tue" },
    });
    stations.loading = true;
    rerender({ day: "thu" });
    expect(result.current[0]).toBe("market");
    expect(result.current[2]).toBe(false);
  });

  it("checks nothing without a day", () => {
    const { result } = renderHook(() => useDeliveryStationOfDay(null));
    act(() => result.current[1]("anywhere"));
    expect(result.current[0]).toBe("anywhere");
    expect(result.current[2]).toBe(false);
  });
});
