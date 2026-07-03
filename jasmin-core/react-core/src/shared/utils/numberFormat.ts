/**
 * Locale-aware number formatting / parsing.
 *
 * The single point of truth for how numbers look in the UI. Use the
 * `useNumberFormat` hook (which reads the tenant's `number_locale`) in
 * React code; these standalone helpers exist for non-hook contexts
 * (utils, services, PDF generation) where the locale must be passed in
 * explicitly.
 *
 * Backend wire format is always canonical "." — `parseLocaleNumber`
 * normalizes user input back to a JS number so callers never have to
 * deal with the display separator.
 */

const DEFAULT_LOCALE = "de-DE";

// Cache one Intl.NumberFormat instance per (locale, decimals) — these are
// cheap to construct but cheaper still to reuse.
const formatterCache = new Map<string, Intl.NumberFormat>();

function getFormatter(locale: string, decimals: number): Intl.NumberFormat {
  const key = `${locale}:${decimals}`;
  let formatter = formatterCache.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    formatterCache.set(key, formatter);
  }
  return formatter;
}

/**
 * Format a number for display in the given locale.
 *
 * Returns "" for nullish / empty / NaN input — matches the historical
 * `.toFixed()` call sites which all guard against falsy values with
 * `value ? ... : ""`.
 */
export function formatNumber(
  value: number | string | null | undefined,
  decimals = 2,
  locale: string = DEFAULT_LOCALE,
): string {
  if (value === null || value === undefined || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "";
  return getFormatter(locale, decimals).format(n);
}

/**
 * Parse user input (possibly using the locale's decimal/grouping
 * separators) back to a JS number. Returns `null` for empty / invalid
 * input.
 *
 * Heuristic: for "de-*" / "fr-*" locales, "." is the grouping character
 * and "," is the decimal point. For everything else we assume "," is
 * grouping and "." is decimal (en-* / most others). Locales like Swiss
 * German (de-CH) use "'" for grouping — handled explicitly.
 */
export function parseLocaleNumber(
  input: string | number | null | undefined,
  locale: string = DEFAULT_LOCALE,
): number | null {
  if (input === null || input === undefined || input === "") return null;
  if (typeof input === "number") return Number.isFinite(input) ? input : null;

  const { groupChar, decimalChar } = getLocaleSeparators(locale);

  // Strip grouping then swap decimal char for "." for parseFloat.
  let normalized = input.trim();
  if (groupChar) {
    // Escape regex special chars (".", "'" etc.).
    const escaped = groupChar.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    normalized = normalized.replace(new RegExp(escaped, "g"), "");
  }
  if (decimalChar !== ".") {
    normalized = normalized.replace(decimalChar, ".");
  }

  const n = parseFloat(normalized);
  return Number.isFinite(n) ? n : null;
}

/**
 * The decimal and grouping characters this locale uses. Derived from
 * `Intl.NumberFormat.formatToParts` so we don't hard-code per-locale
 * rules — works for any BCP-47 tag the browser knows.
 */
export function getLocaleSeparators(locale: string = DEFAULT_LOCALE): {
  decimalChar: string;
  groupChar: string;
} {
  const parts = new Intl.NumberFormat(locale).formatToParts(1234567.89);
  const decimalChar = parts.find((p) => p.type === "decimal")?.value ?? ".";
  const groupChar = parts.find((p) => p.type === "group")?.value ?? ",";
  return { decimalChar, groupChar };
}

/**
 * Build a keydown handler that hard-blocks non-numeric characters in a numeric
 * input. AntD ``InputNumber`` only coerces invalid text on blur — it does NOT
 * stop you typing "5,kers" while focused — so config number fields need this
 * guard to actually prevent invalid keystrokes. Paste of garbage is still
 * sanitised by InputNumber's own blur coercion.
 *
 * Typed structurally (not React.KeyboardEvent) so this stays a React-free util;
 * the shape is satisfied by a real keyboard event, so it drops straight into
 * ``onKeyDown``.
 */
export function blockNonNumericKeys(opts: {
  allowDecimal: boolean;
  decimalChar: string;
  allowNegative?: boolean;
}) {
  const navKeys = new Set([
    "Backspace",
    "Delete",
    "Tab",
    "Enter",
    "Escape",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
  ]);
  return (e: {
    key: string;
    ctrlKey: boolean;
    metaKey: boolean;
    altKey: boolean;
    preventDefault: () => void;
  }) => {
    // Let shortcuts (copy/paste/select-all) and navigation/editing keys through.
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (navKeys.has(e.key)) return;
    if (/^[0-9]$/.test(e.key)) return;
    if (opts.allowNegative && e.key === "-") return;
    if (opts.allowDecimal && e.key === opts.decimalChar) return;
    e.preventDefault();
  };
}
