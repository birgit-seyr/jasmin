/**
 * The thin query hooks over the generated commissioning client: what each
 * one asks for, when it waits, and how it shapes the answer. The generated
 * client is the mocking boundary.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  stationsList: vi.fn(),
  stationsQueryOptions: vi.fn(),
  shareOptionsList: vi.fn(),
  granularityRetrieve: vi.fn(),
  historicalAveragesRetrieve: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDeliveryStationsList: client.stationsList,
  getCommissioningDeliveryStationsListQueryOptions: client.stationsQueryOptions,
  useCommissioningShareOptionsList: client.shareOptionsList,
  useCommissioningGranularityRetrieve: client.granularityRetrieve,
  useCommissioningHistoricalShareTypeVariationAveragesRetrieve:
    client.historicalAveragesRetrieve,
}));

import { useDeliveryStations, useDeliveryStationsPerDay } from "../useDeliveryStations";
import { useHistoricalShareTypeVariationAverages } from "../useHistoricalShareTypeVariationAverages";
import { useShareContentGranularity } from "../useShareContentGranularity";
import { useShareOptions } from "../useShareOptions";

const queryOptionsOf = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.at(-1)?.[1] as { query: { enabled: boolean } };

beforeEach(() => {
  vi.clearAllMocks();
  client.stationsList.mockReturnValue({ data: undefined, isLoading: false, error: null });
  client.shareOptionsList.mockReturnValue({ data: undefined, isLoading: true });
  client.granularityRetrieve.mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  client.historicalAveragesRetrieve.mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
  });
});

describe("useDeliveryStations", () => {
  it("asks for active stations and waits for a delivery day", () => {
    renderHook(() => useDeliveryStations());
    expect(client.stationsList).toHaveBeenCalledWith({ is_active: true }, expect.anything());
    expect(queryOptionsOf(client.stationsList).query.enabled).toBe(false);

    renderHook(() => useDeliveryStations({ delivery_day: "day-1" }));
    expect(client.stationsList).toHaveBeenLastCalledWith(
      { is_active: true, delivery_day: "day-1" },
      expect.anything(),
    );
    expect(queryOptionsOf(client.stationsList).query.enabled).toBe(true);
  });

  it("fetches without a day when the caller enables it", () => {
    renderHook(() => useDeliveryStations({}, { enabled: true }));
    expect(queryOptionsOf(client.stationsList).query.enabled).toBe(true);
  });

  it("labels a station by its short name, else its company name", () => {
    client.stationsList.mockReturnValue({
      data: [
        { id: "s1", short_name: "Market", company_name: "Market Hall Ltd" },
        { id: "s2", short_name: "", company_name: "Corner Shop" },
        { id: "s3", short_name: null, company_name: null },
      ],
      isLoading: false,
      error: null,
    });
    const { result } = renderHook(() => useDeliveryStations({ delivery_day: "day-1" }));
    expect(result.current.deliveryStations.map((s) => [s.value, s.label])).toEqual([
      ["s1", "Market"],
      ["s2", "Corner Shop"],
      ["s3", ""],
    ]);
  });
});

describe("useDeliveryStationsPerDay", () => {
  it("gives each day its own active stations, in the order of the days", async () => {
    client.stationsQueryOptions.mockImplementation(
      (params: { delivery_day: string; is_active: boolean }) => ({
        queryKey: ["stations", params],
        queryFn: async () => [
          { id: `${params.delivery_day}-station`, short_name: params.delivery_day },
        ],
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useDeliveryStationsPerDay(["tue", "thu"]), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(client.stationsQueryOptions).toHaveBeenCalledWith({ is_active: true, delivery_day: "tue" });
    expect(
      result.current.stationsPerDay.map((stations) => stations.map((s) => s.value)),
    ).toEqual([["tue-station"], ["thu-station"]]);
  });
});

describe("useShareOptions", () => {
  it("gives an empty list while loading", () => {
    const { result } = renderHook(() => useShareOptions());
    expect(result.current).toEqual({ shareOptions: [], loading: true });
  });
});

describe("useShareContentGranularity", () => {
  it("waits for a year and a week", () => {
    const { result } = renderHook(() => useShareContentGranularity({ year: 2026 }));
    expect(queryOptionsOf(client.granularityRetrieve).query.enabled).toBe(false);
    expect(result.current.daysOk).toBeNull();
    expect(result.current.toursOk).toBeNull();
  });

  it("forwards the scope and reads both answers", () => {
    client.granularityRetrieve.mockReturnValue({
      data: { days_ok: true, tours_ok: false },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    const params = { year: 2026, delivery_week: 42, share_type: "st-1", day_number: 1 };
    const { result } = renderHook(() => useShareContentGranularity(params));
    expect(client.granularityRetrieve).toHaveBeenCalledWith(params, { query: { enabled: true } });
    expect(result.current.daysOk).toBe(true);
    expect(result.current.toursOk).toBe(false);
  });
});

describe("useHistoricalShareTypeVariationAverages", () => {
  const paramsOf = () =>
    client.historicalAveragesRetrieve.mock.calls.at(-1)?.[0] as Record<string, unknown>;

  it("waits for a week and either variation ids or a share option", () => {
    renderHook(() => useHistoricalShareTypeVariationAverages({ year: 2026, delivery_week: 42 }));
    expect(queryOptionsOf(client.historicalAveragesRetrieve).query.enabled).toBe(false);

    renderHook(() =>
      useHistoricalShareTypeVariationAverages({
        year: 2026,
        delivery_week: 42,
        share_type_variation_ids: [],
      }),
    );
    expect(queryOptionsOf(client.historicalAveragesRetrieve).query.enabled).toBe(false);
  });

  it("joins the variation ids and looks two years back by default", () => {
    renderHook(() =>
      useHistoricalShareTypeVariationAverages({
        year: 2026,
        delivery_week: 42,
        share_type_variation_ids: ["v1", "v2"],
      }),
    );
    expect(queryOptionsOf(client.historicalAveragesRetrieve).query.enabled).toBe(true);
    expect(paramsOf()).toEqual({
      year: 2026,
      delivery_week: 42,
      share_type_variation_ids: "v1,v2",
      years_back: 2,
    });
  });

  it("resolves the variations from a share option", () => {
    renderHook(() =>
      useHistoricalShareTypeVariationAverages({
        year: 2026,
        delivery_week: 42,
        share_option: "HARVEST_SHARE",
        active_at_date: "2026-10-17",
        years_back: 3,
      }),
    );
    expect(queryOptionsOf(client.historicalAveragesRetrieve).query.enabled).toBe(true);
    expect(paramsOf()).toEqual({
      year: 2026,
      delivery_week: 42,
      share_type_variation_ids: "",
      share_option: "HARVEST_SHARE",
      active_at_date: "2026-10-17",
      years_back: 3,
    });
  });

  it("skips the request when the caller turns it off", () => {
    renderHook(() =>
      useHistoricalShareTypeVariationAverages({
        year: 2026,
        delivery_week: 42,
        share_option: "HARVEST_SHARE",
        enabled: false,
      }),
    );
    expect(queryOptionsOf(client.historicalAveragesRetrieve).query.enabled).toBe(false);
  });

  it("gives null data until the answer arrives", () => {
    const { result } = renderHook(() =>
      useHistoricalShareTypeVariationAverages({ year: 2026, delivery_week: 42 }),
    );
    expect(result.current.data).toBeNull();
  });
});
