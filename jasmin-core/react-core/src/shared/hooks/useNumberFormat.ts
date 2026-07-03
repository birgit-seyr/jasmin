/**
 * Single source of truth for decimal display + parsing in the UI.
 *
 * Reads `number_locale` from the active tenant's settings (BCP-47 tag,
 * e.g. "de-DE" → "1.234,50") and exposes:
 *
 *   - `format(value, decimals)`  — render-side; replaces every
 *     `value.toFixed(N)` call site in cell renders, summaries, PDFs.
 *   - `parse(input)`             — input-side; converts a user-typed
 *     string back to a canonical JS number (used by FormInput to keep
 *     the form/wire payload in canonical "." form).
 *   - `locale`                   — exposed for callers that need to
 *     hand it to `Intl.NumberFormat` directly (rare).
 */

import { useMemo } from "react";
import { useTenant } from "./configuration/useTenant";
import {
  formatNumber,
  parseLocaleNumber,
  getLocaleSeparators,
} from "@shared/utils/numberFormat";

export function useNumberFormat() {
  const { getSetting } = useTenant();
  const locale = (getSetting("number_locale", "de-DE") as string) || "de-DE";

  return useMemo(
    () => ({
      locale,
      separators: getLocaleSeparators(locale),
      format: (value: number | string | null | undefined, decimals = 2) =>
        formatNumber(value, decimals, locale),
      parse: (input: string | number | null | undefined) =>
        parseLocaleNumber(input, locale),
    }),
    [locale],
  );
}
