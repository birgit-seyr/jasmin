import { useMemo } from "react";
import { useNumberFormat } from "../useNumberFormat";
import { currencyCodeToSymbol } from "@shared/utils/currency";
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
  const { getSetting } = useTenant();
  const { format } = useNumberFormat();

  const currencyCode = getSetting("currency", "EUR") as string;

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
  const formatCurrency = useMemo(
    () =>
      (amount: number | null | undefined, decimals = 2) => {
        if (amount === null || amount === undefined || isNaN(amount)) {
          return "";
        }

        const formattedAmount = format(Number(amount), decimals);

        // Currencies that go before the amount
        if (["$", "£", "C$", "A$"].includes(currencySymbol)) {
          return `${currencySymbol}${formattedAmount}`;
        }

        // Most currencies go after
        return `${formattedAmount} ${currencySymbol}`;
      },
    [currencySymbol, format]
  );

  return {
    currencyCode,
    currencySymbol,
    formatCurrency,
  };
};
