import { useMemo } from "react";
import { useNumberFormat } from "../useNumberFormat";
import { currencyCodeToSymbol, formatCurrency } from "@shared/utils/currency";
import { useTenant } from "./useTenant";

/**
 * Custom hook for currency formatting and symbol retrieval. The
 * currency-code → symbol mapping is shared with non-React callsites
 * (PDF / CSV generators) via ``utils/currency.ts`` so the UI and the
 * exported documents always render with the same character.
 *
 * @returns {Object} Object containing currency utilities
 */
export const useCurrency = () => {
  const { getSetting, tenant } = useTenant();
  const { format } = useNumberFormat();

  // Prefer the settings overlay (authenticated pages); fall back to the
  // tenant's top-level ``currency`` scalar, which the anonymous
  // ``/tenants/current/`` payload carries (the public registration page shows
  // prices), then EUR.
  const currencyCode =
    ((getSetting("currency") as string | undefined) ||
      (tenant?.currency as string | undefined)) ??
    "EUR";

  const currencySymbol = useMemo(
    () => currencyCodeToSymbol(currencyCode),
    [currencyCode],
  );

  /**
   * Format amount with currency symbol
   * @param {number} amount - Amount to format
   * @param {number} decimals - Number of decimal places (default: 2)
   * @returns {string} Formatted price string
   */
  const formatCurrencyMemo = useMemo(
    () =>
      (amount: number | null | undefined, decimals = 2) => {
        if (amount === null || amount === undefined || isNaN(amount)) {
          return "";
        }

        return formatCurrency(format(Number(amount), decimals), currencySymbol);
      },
    [currencySymbol, format]
  );

  return {
    currencyCode,
    currencySymbol,
    formatCurrency: formatCurrencyMemo,
  };
};
