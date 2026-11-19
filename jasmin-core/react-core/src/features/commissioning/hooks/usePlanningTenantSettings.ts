import { useTenant } from "@hooks/index";
import { usePackingStationCount } from "./usePackingStationCount";

/** The tenant settings the share-content planning page reads, with defaults. */
export function usePlanningTenantSettings() {
  const { getSetting } = useTenant();
  const numberPackingStations = usePackingStationCount();
  return {
    defaultPlanningGranularity:
      getSetting("default_planning_granularity", "basic") || "basic",
    numberPackingStations,
    showSummaryOnTop:
      getSetting("show_summary_in_harvest_share_planning_on_top", true) ??
      true,
    hasPurchases: getSetting("has_purchases", true) !== false,
  };
}
