import { useTenant } from "@hooks/index";

/** The tenant settings the share-content planning page reads, with defaults. */
export function usePlanningTenantSettings() {
  const { getSetting } = useTenant();
  return {
    defaultPlanningGranularity:
      getSetting("default_planning_granularity", "basic") || "basic",
    numberPackingStations: getSetting("number_packing_stations", 1) ?? 1,
    showSummaryOnTop:
      getSetting("show_summary_in_harvest_share_planning_on_top", true) ??
      true,
  };
}
