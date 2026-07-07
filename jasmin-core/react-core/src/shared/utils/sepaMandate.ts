import dayjs from "dayjs";
import type { SepaMandateStatus } from "@shared/api/generated/models";

/**
 * Whether a member's SEPA mandate was active *during a subscription's term*.
 *
 * A mandate has no explicit end date in the model — it's usable from its
 * signed date onward (until deactivated). So "active during the term" reduces
 * to: the member currently has a ready/usable mandate
 * (``has_active_sepa_mandate``) AND it was signed on or before the term ends
 * (a mandate signed *after* the subscription already expired never covered it).
 * An open-ended term (no ``valid_until``) is covered by any ready mandate.
 */
export function isSepaMandateActiveForTerm(
  status: SepaMandateStatus | undefined,
  validUntil: string | null | undefined,
): boolean {
  if (!status?.has_active_sepa_mandate) return false;
  if (!validUntil) return true;
  const signed = status.sepa_mandate_signed_at;
  if (!signed) return false;
  return !dayjs(signed).isAfter(dayjs(validUntil), "day");
}
