import { useMemo } from "react";
import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import {
  getCommissioningDeliveryStationsListQueryOptions,
  useCommissioningDeliveryStationsList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDeliveryStationsListParams,
  DeliveryStation,
  ErrorResponse,
} from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type DeliveryStationOption = Option<DeliveryStation>;

const deliveryStationLabel = (station: DeliveryStation) =>
  station.short_name || station.company_name || "";

export const useDeliveryStations = (
  params: CommissioningDeliveryStationsListParams = {},
  { enabled }: { enabled?: boolean } = {},
) => {
  const queryParams = { is_active: true, ...params };

  const { data, isLoading, error } = useCommissioningDeliveryStationsList(queryParams, {
    // By default the fetch waits for a ``delivery_day`` (the selector's
    // day-scoped use). Callers that want ALL active stations regardless of day
    // pass ``{ enabled: true }``.
    query: { enabled: enabled ?? params.delivery_day != null },
  });

  const deliveryStations: DeliveryStationOption[] = useMemo(
    () => toOptions(data, deliveryStationLabel),
    [data],
  );

  return {
    deliveryStations,
    loading: isLoading,
    error,
  };
};

// Module-level, so TanStack re-runs it only when a query result changes and
// the lists keep their identity between renders.
const combineStationsPerDay = (
  results: UseQueryResult<DeliveryStation[], ErrorResponse>[],
) => ({
  stationsPerDay: results.map((result) => toOptions(result.data, deliveryStationLabel)),
  loading: results.some((result) => result.isLoading),
});

/**
 * The active stations of each delivery day, in the order of `deliveryDayIds` —
 * for views spanning several days, since every day serves its own stations.
 * Shares its requests with `useDeliveryStations` for the same day.
 */
export const useDeliveryStationsPerDay = (deliveryDayIds: string[]) =>
  useQueries({
    queries: deliveryDayIds.map((deliveryDay) =>
      getCommissioningDeliveryStationsListQueryOptions({
        is_active: true,
        delivery_day: deliveryDay,
      }),
    ),
    combine: combineStationsPerDay,
  });
