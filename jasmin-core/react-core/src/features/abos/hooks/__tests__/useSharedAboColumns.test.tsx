/**
 * The delivery-station-day cell renders ``"<short weekday> - <station>"`` from
 * the annotated ``delivery_day_number`` / ``delivery_station_name`` pair, via
 * the shared ``DELIVERY_DAY_SHORT_KEYS`` map (0 = Monday … 6 = Sunday). Monday
 * is 0, so the render must null-check rather than test truthiness, and a
 * day_number outside the map falls back to the backend's annotated string.
 *
 * The per-index cases pin the map's order: a reordered or 1-based
 * ``DELIVERY_DAY_SHORT_KEYS`` would label every row with the wrong weekday.
 * ``useAbosColumns.test.tsx`` deliberately stubs this module out, so these are
 * the only cases that execute the real render.
 *
 * Boundary mocked: react-i18next (echoes the key back) and the hooks barrel.
 * The weekday map itself is the real module — it is what these cases pin.
 */
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/index", () => ({
  useTenant: () => ({
    getSetting: (_key: string, defaultValue?: unknown) => defaultValue,
  }),
  useVariationLabel: () => (value?: string | null) => value ?? "",
}));

import type { AboRecord } from "@features/abos/pages/types";
import { useSharedAboColumns } from "../columns/useSharedAboColumns";

// What the backend annotates onto the row; the render falls back to it whenever
// it cannot build a translated label.
const ANNOTATED_STRING = "Mo - Station A";

function aboRecord(overrides: Partial<AboRecord>): AboRecord {
  return {
    key: "abo-1",
    default_delivery_station_day_string: ANNOTATED_STRING,
    delivery_station_name: "Station A",
    ...overrides,
  };
}

function renderStationDayCell(record: AboRecord) {
  const { result } = renderHook(() =>
    useSharedAboColumns({
      disabled: false,
      memberOptions: [],
      memberWidth: "12em",
      shareTypeVariationOptions: [],
      shareTypeVariationWidth: "12em",
      onShareTypeVariationChange: undefined,
      deliveryStationDayOptions: [],
      deliveryStationDayAlign: "left",
    }),
  );
  const { render } = result.current.deliveryStationDayColumn;
  expect(render).toBeDefined();
  return render?.(record.default_delivery_station_day_string, record, 0);
}

describe("useSharedAboColumns delivery-station-day render", () => {
  it.each([
    [0, "delivery.mo"],
    [1, "delivery.di"],
    [2, "delivery.mi"],
    [3, "delivery.do"],
    [4, "delivery.fr"],
    [5, "delivery.sa"],
    [6, "delivery.su"],
  ])("labels day_number %i with %s", (dayNumber, expectedKey) => {
    expect(
      renderStationDayCell(aboRecord({ delivery_day_number: dayNumber })),
    ).toBe(`${expectedKey} - Station A`);
  });

  it("labels Monday when the wire sends day_number as the string \"0\"", () => {
    expect(
      renderStationDayCell(aboRecord({ delivery_day_number: "0" })),
    ).toBe("delivery.mo - Station A");
  });

  it("falls back to the annotated string for an out-of-range day_number", () => {
    expect(
      renderStationDayCell(aboRecord({ delivery_day_number: 9 })),
    ).toBe(ANNOTATED_STRING);
  });

  it.each([
    ["null", null],
    ["an empty string", ""],
  ])("falls back to the annotated string when day_number is %s", (_label, dayNumber) => {
    expect(
      renderStationDayCell(aboRecord({ delivery_day_number: dayNumber })),
    ).toBe(ANNOTATED_STRING);
  });

  it("falls back to the annotated string when the station name is missing", () => {
    expect(
      renderStationDayCell(
        aboRecord({ delivery_day_number: 0, delivery_station_name: undefined }),
      ),
    ).toBe(ANNOTATED_STRING);
  });
});
