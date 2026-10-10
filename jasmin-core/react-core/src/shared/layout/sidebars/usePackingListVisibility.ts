import { useTenant } from "@hooks/index";

/**
 * Which packing lists the tenant's ``packing_mode`` offers. The boxes list and
 * the commissioning list for packing belong to box packing, the bulk list to
 * bulk packing; ``MIXED`` offers both. Every navigation that links them reads
 * this one rule, so the desktop sidebar and the phone drawer can't disagree.
 */
export function usePackingListVisibility() {
  const { getSetting } = useTenant();
  const packingMode = getSetting("packing_mode", "BOXES");
  return {
    packingMode,
    showBulkPackingList: packingMode === "BULK" || packingMode === "MIXED",
    showBoxesPackingList: packingMode === "BOXES" || packingMode === "MIXED",
  };
}
