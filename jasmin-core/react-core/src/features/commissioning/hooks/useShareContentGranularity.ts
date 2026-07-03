import { useCommissioningGranularityRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningGranularityRetrieveParams } from "@shared/api/generated/models";

// Granularity is per-share_type: a simple share (honey) can be
// day-consistent while a complex harvest share in the same week is not.
// share_type/share_option scope the backend check accordingly. They're
// typed loosely here until the next generate-api adds them to
// CommissioningGranularityRetrieveParams; orval spreads params, so they're
// forwarded on the request regardless.
type GranularityParams = Partial<CommissioningGranularityRetrieveParams> & {
  share_type?: string;
  share_option?: string;
  // Optional: scope the check to a single delivery day (weekday 0-6). Omit for
  // the across-all-delivery-days result (PlanningHarvestSharesBase); the packing
  // list passes the selected delivery day for per-day granularity.
  day_number?: number;
};

export const useShareContentGranularity = (params: GranularityParams = {}) => {
  const enabled = !!params.year && !!params.delivery_week;

  const { data, isLoading, error, refetch } = useCommissioningGranularityRetrieve(
    params as CommissioningGranularityRetrieveParams,
    { query: { enabled } },
  );

  return {
    daysOk: data?.days_ok ?? null,
    toursOk: data?.tours_ok ?? null,
    loading: isLoading,
    error,
    refetch,
  };
};
