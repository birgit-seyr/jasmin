/**
 * Client-side line-netto money math — the single mirror of the backend
 * `LinePricingMixin` (`apps/commissioning/models/mixin.py`).
 *
 * Kept here (and not inline at each call site) so a discount / rounding change
 * happens once: the order page, the crate column, the invoice modal and the
 * reseller PDFs all derive their net line totals from the same two functions.
 * Backend money arrives as canonical Decimal strings, so every field is
 * coerced through `Number()`.
 */

/** The fields the line-netto helpers read off a row/line item. */
export interface LineNettoInput {
  amount?: number | string | null;
  price_per_unit?: number | string | null;
  rabatt?: number | string | null;
  /** Net line total supplied by the backend (canonical Decimal string). */
  line_netto?: number | string | null;
}

/**
 * Round half-up to `decimals` places (default 2), mirroring the backend's
 * Decimal ROUND_HALF_UP. The single client-side money rounder so the order
 * page, crate column, invoice modal and reseller PDFs stay identical to the
 * persisted, legally-binding backend figure (a half-even rounder would
 * disagree by a cent on a value landing exactly on a half-cent).
 */
export function roundHalfUp(value: number, decimals = 2): number {
  if (!Number.isFinite(value)) return 0;
  const factor = 10 ** decimals;
  const shifted = value * factor;
  const sign = shifted < 0 ? -1 : 1;
  const abs = Math.abs(shifted);
  const floor = Math.floor(abs);
  const diff = abs - floor;
  // Guard against binary-float noise: treat anything within eps of .5 as .5,
  // which HALF_UP rounds away from zero.
  const eps = 1e-9;
  const roundedAbs = diff >= 0.5 - eps ? floor + 1 : floor;
  return (sign * roundedAbs) / factor;
}

/**
 * Net line total from inputs: `amount * price_per_unit * (1 - rabatt/100)`,
 * quantized per line to 0.01 ROUND_HALF_UP to mirror the backend's
 * `_calc_line_netto`. Does NOT prefer a backend-supplied `line_netto` — use
 * this where the value must be recomputed from the (possibly just-edited)
 * inputs. Rounding here (not only at the group total) keeps the
 * round-each-line-then-sum order identical to the backend `tax_breakdown`.
 */
export function computeLineNetto(item: LineNettoInput): number {
  const base = Number(item.amount || 0) * Number(item.price_per_unit || 0);
  const discount = (base * Number(item.rabatt || 0)) / 100;
  return roundHalfUp(base - discount);
}

/**
 * Net line total preferring the backend-supplied `line_netto` when present and
 * finite, else computing it via {@link computeLineNetto}. This is what a
 * read-only display of a fetched document should use.
 */
export function itemLineNetto(item: LineNettoInput): number {
  // An empty string counts as "no backend value" (a live-edit row that hasn't
  // been recomputed yet), not as zero — fall back to computing in that case.
  if (
    item.line_netto !== undefined &&
    item.line_netto !== null &&
    item.line_netto !== ""
  ) {
    const n = Number(item.line_netto);
    if (Number.isFinite(n)) return n;
  }
  return computeLineNetto(item);
}
