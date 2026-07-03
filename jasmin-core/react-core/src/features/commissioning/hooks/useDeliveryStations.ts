import { useCommissioningDeliveryStationsList } from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStation, CommissioningDeliveryStationsListParams } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";

export type DeliveryStationOption = Option<DeliveryStation>;

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

  const deliveryStations: DeliveryStationOption[] = toOptions(
    data,
    (ds) => ds.short_name || ds.company_name || "",
  );

  return {
    deliveryStations,
    loading: isLoading,
    error,
  };
};
