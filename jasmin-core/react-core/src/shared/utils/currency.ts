/**
 * Currency-code → display-symbol mapping shared across the UI
 * (``useCurrency()`` hook) and non-React callsites (PDF generators,
 * CSV exporters) that can't depend on React hooks.
 *
 * Keep this tight and additive: the values are what we *print* on
 * invoices and customer-facing surfaces. ISO 4217 ALPHA-3 codes that
 * have no widely-recognised one-character symbol fall back to the
 * code itself (e.g. ``"CHF"``), which is what the React UI did
 * historically.
 *
 * Tests live in ``utils/__tests__/currency.test.ts``.
 */

const CURRENCY_SYMBOLS: Readonly<Record<string, string>> = {
  EUR: "€",
  USD: "$",
  GBP: "£",
  CHF: "CHF",
};

/**
 * Best-effort symbol for an ISO 4217 currency code.
 *
 * Falls back to the input string when no entry is registered, then to
 * ``"€"`` when even that is empty/undefined — matches the behaviour of
 * ``useCurrency().currencySymbol`` so the two sources stay in sync.
 */
export function currencyCodeToSymbol(code: string | null | undefined): string {
  if (!code) return "€";
  return CURRENCY_SYMBOLS[code] ?? code ?? "€";
}
