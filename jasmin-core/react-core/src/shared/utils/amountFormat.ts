import { UnitEnum } from "@shared/api/generated/models";

/** The tenant-locale number formatter returned by `useNumberFormat` — passed
 *  in so these stay plain (non-hook) utils importable from anywhere. */
type NumberFormatter = (value: number, decimals: number) => string;

/**
 * Display precision for a produce amount by its unit: KG (and a missing unit)
 * render at 2 decimals, every other unit (PCS / BUNCH / L / G) at 1. The
 * missing-unit → 2dp fallback is deliberate.
 */
export const decimalsForUnit = (unit: string | null | undefined): number =>
  unit && unit !== UnitEnum.KG ? 1 : 2;

/**
 * Format a produce amount at its unit's display precision (see
 * {@link decimalsForUnit}).
 */
export const formatAmountForUnit = (
  value: number,
  unit: string | null | undefined,
  format: NumberFormatter,
): string => format(value, decimalsForUnit(unit));

/**
 * Build a numeric table-cell renderer that blanks null / empty / non-finite
 * values and otherwise formats via `format` at the given precision. Replaces
 * the copy-pasted `value ? format(Number(value), N) : ""` cell bodies.
 */
export const renderNumber =
  (format: NumberFormatter, decimals: number) =>
  (value: unknown): string => {
    if (value == null || value === "" || !Number.isFinite(Number(value)))
      return "";
    return format(Number(value), decimals);
  };
