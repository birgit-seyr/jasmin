import { useTenant } from "@hooks/index";

/**
 * How many packing stations the farm's boxes are packed at: its setting, and
 * one where every size goes out loose, as no box is packed there and the
 * setting is hidden. One station needs no column to pick it from.
 */
export function usePackingStationCount(): number {
  const { getSetting } = useTenant();
  if (getSetting("packing_mode", "BOXES") === "BULK") return 1;
  return Number(getSetting("number_packing_stations", 1) ?? 1);
}
