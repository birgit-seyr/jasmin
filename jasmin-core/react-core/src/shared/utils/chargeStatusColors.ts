/**
 * Canonical color + ordering for the six ChargeStatus values, shared by the
 * member-detail PaymentsCard and the office ChargesAbos page so the two views
 * can't drift on what a charge status looks like.
 */
export const CHARGE_STATUS_COLOR: Record<string, string> = {
  PLANNED: "blue",
  ISSUED: "gold",
  PAID: "green",
  PARTIAL: "orange",
  FAILED: "red",
  WAIVED: "default",
};

// Display / summary order (logical lifecycle), not alphabetical.
export const CHARGE_STATUS_ORDER = Object.keys(CHARGE_STATUS_COLOR);
