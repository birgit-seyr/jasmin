import type { TFunction } from "i18next";

/**
 * Localize a PaymentCycleOptions code (WEEKLY, BIWEEKLY, MONTHLY, QUARTERLY,
 * SEMI_ANNUALLY, ANNUALLY) via the shared `configuration.payment_cycle_*` keys.
 */
export function paymentCycleLabel(t: TFunction, code?: string | null): string {
  if (!code) return "—";
  return t(`configuration.payment_cycle_${code.toLowerCase()}`);
}

/**
 * Localize a DeliveryCycleOptions code (WEEKLY, ODD_WEEKS, EVEN_WEEKS, MONTHLY,
 * QUARTERLY, HALF_YEARLY, YEARLY) via the shared `commissioning.*` keys.
 */
export function deliveryCycleLabel(t: TFunction, code?: string | null): string {
  if (!code) return "—";
  return t(`commissioning.${code.toLowerCase()}`);
}
