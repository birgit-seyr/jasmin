/**
 * useOrderColumns: the offer line's "still available" cell. The column hooks
 * it composes and the shared formatting hooks are stubbed; only the cell's
 * rendering is under test.
 */
import { render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@features/commissioning/hooks", () => ({
  useCratesColumns: () => ({ cratesColumns: [], crates: [] }),
  useOfferOptions: () => ({ offers: [] }),
  useOfferTiers: () => [1],
  useShareArticleColumn: () => ({
    shareArticleColumn: { key: "share_article", dataIndex: "share_article" },
    handleUnitChange: vi.fn(),
    handleAmountChange: vi.fn(),
  }),
  useWashingCleaningColumns: () => ({ washingCleaningColumns: [] }),
}));
vi.mock("@hooks/index", () => ({
  useCurrency: () => ({ currencySymbol: "€", formatCurrency: String }),
  useNoteColumn: () => ({ noteColumn: { key: "note", dataIndex: "note" } }),
  useNumberFormat: () => ({
    format: (value: number, digits: number) => value.toFixed(digits),
  }),
  useUnitOptions: () => ({ getUnitLabel: String }),
}));
vi.mock("../useAmountUnitSizeColumns", () => ({
  useAmountUnitSizeColumns: () => ({ amountUnitSizeColumns: [] }),
}));

import { useOrderColumns } from "../useOrderColumns";

function availableCell(value: unknown) {
  const { result } = renderHook(() =>
    useOrderColumns({
      params: { year: 2026, delivery_week: 40, day_number: 2, reseller: "r1" },
      dataCrates: [],
    }),
  );
  const column = result.current.columnsOffers.find(
    (col) => col.key === "offer_available_amount",
  );
  const cell = column?.render?.(value, { key: "1" }, 0) as ReactNode;
  render(<>{cell}</>);
  return screen.getByText(/commissioning\.pu/);
}

describe("useOrderColumns still-available cell", () => {
  it("marks an offer with nothing left, small", () => {
    const cell = availableCell(0);

    expect(cell).toHaveClass("amount-none-left", "text-xs");
    expect(cell).not.toHaveAttribute("style");
  });

  it("marks an offer with some left, small", () => {
    const cell = availableCell(3);

    expect(cell).toHaveClass("amount-left", "text-xs");
    expect(cell).not.toHaveAttribute("style");
  });

  it("counts a missing amount as nothing left", () => {
    expect(availableCell(null)).toHaveClass("amount-none-left");
  });
});
