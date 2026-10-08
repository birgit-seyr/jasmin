/**
 * useHarvestingListData: the deliveries a harvest day serves.
 *
 * The selected week is the harvest's week. A harvest on a weekday later than
 * the delivery's — Saturday's harvest for Monday — serves the next week's
 * delivery, so its date and its variation totals are next week's, while a
 * delivery on or after the harvest day stays in the selected week. The rows
 * themselves are in the harvest's coordinates and aren't touched here.
 *
 * The related days, the delivery days per week and the totals are the mocking
 * boundary; the clock is pinned, though nothing here reads it.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("../../../../test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const { totalsFilters, deliveryDaysAsked } = vi.hoisted(() => ({
  totalsFilters: { current: undefined as unknown },
  deliveryDaysAsked: [] as unknown[],
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey: () => [
    "summary",
  ],
  useCommissioningDocumentationSummarySummaryRetrieve: () => ({
    data: [],
    isLoading: false,
    isFetching: false,
  }),
}));

const SATURDAY = 5; // Backend day numbers: 0 = Monday … 6 = Sunday.
const MONDAY = 0;

// Saturday's harvest serves Monday's delivery and Saturday's own.
vi.mock("../useCurrentDays", () => ({
  useCurrentDays: () => ({
    getRelatedDays: { getDeliveryDaysForHarvesting: () => [MONDAY, SATURDAY] },
    isLoaded: true,
  }),
}));

// Each week has its own delivery-day rows, as after a supersession.
vi.mock("../useShareDeliveryDays", () => ({
  useShareDeliveryDays: (params: { active_at_date: string }) => {
    deliveryDaysAsked.push(params.active_at_date);
    return {
      shareDeliveryDays: [
        { id: `mon@${params.active_at_date}`, day_number: MONDAY },
        { id: `sat@${params.active_at_date}`, day_number: SATURDAY },
      ],
    };
  },
}));

vi.mock("../useAggregatedVariationsTotals", () => ({
  useAggregatedVariationsTotals: (filters: unknown) => {
    totalsFilters.current = filters;
    return { entries: [] };
  },
}));

import { useHarvestingListData } from "../useHarvestingListData";

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 5, 12, 0));
});
afterAll(() => {
  vi.useRealTimers();
});
beforeEach(() => {
  totalsFilters.current = undefined;
  deliveryDaysAsked.length = 0;
});

function renderSaturdayHarvest(selectedYear: number, selectedWeek: number) {
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () =>
      useHarvestingListData({
        selectedYear,
        selectedWeek,
        selectedDay: SATURDAY,
        fallbackWeek: selectedWeek,
        isPast: false,
        isGardenerView: false,
        roundUpToFullPU: false,
      }),
    { wrapper },
  );
  return result.current;
}

describe("a harvest serving next week's delivery", () => {
  it("dates Monday's delivery in the next week and Saturday's in the selected one", () => {
    const { deliveryDateOf } = renderSaturdayHarvest(2026, 41);

    expect(deliveryDateOf(MONDAY).format("YYYY-MM-DD")).toBe("2026-10-12");
    expect(deliveryDateOf(SATURDAY).format("YYYY-MM-DD")).toBe("2026-10-10");
  });

  it("asks for each delivery's totals in its own week, by that week's delivery day", () => {
    renderSaturdayHarvest(2026, 41);

    expect(deliveryDaysAsked).toEqual(
      expect.arrayContaining(["2026-10-10", "2026-10-17"]),
    );
    expect(totalsFilters.current).toMatchObject({
      delivery_day: [
        { id: "mon@2026-10-17", year: 2026, delivery_week: 42 },
        { id: "sat@2026-10-10", year: 2026, delivery_week: 41 },
      ],
    });
  });

  it("rolls the next week into the next ISO year", () => {
    // 2026 has 53 ISO weeks; the one after its last is week 1 of 2027.
    const { deliveryDateOf } = renderSaturdayHarvest(2026, 53);

    expect(deliveryDateOf(MONDAY).format("YYYY-MM-DD")).toBe("2027-01-04");
    expect(totalsFilters.current).toMatchObject({
      delivery_day: [
        { id: "mon@2027-01-09", year: 2027, delivery_week: 1 },
        { id: "sat@2027-01-02", year: 2026, delivery_week: 53 },
      ],
    });
  });
});
