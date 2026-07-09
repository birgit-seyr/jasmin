/**
 * Unit test for ``useOtherArticleColumns`` — the read-only columns for the
 * customer order page's "other articles" table (offer-less order lines).
 *
 * Pins the user-facing requirements: amount shown in the UNIT (not PU), the
 * per-unit price, the rabatt, and a net line total with the rabatt factored in.
 */

import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));
vi.mock("@hooks/configuration/useCurrency", () => ({
  useCurrency: () => ({
    currencySymbol: "€",
    formatCurrency: (n: number) => `${n.toFixed(2)} €`,
  }),
}));
vi.mock("@hooks/useNumberFormat", () => ({
  useNumberFormat: () => ({ format: (n: number, d: number) => n.toFixed(d) }),
}));
vi.mock("@hooks/useUnitOptions", () => ({
  useUnitOptions: () => ({ getUnitLabel: (u: string) => u }),
}));
vi.mock("@hooks/useSizeOptions", () => ({
  useSizeOptions: () => ({ getSizeLabel: (s: string) => s }),
}));

import { useOtherArticleColumns } from "../useOtherArticleColumns";

// Mirrors the user's example: 2 KG @ 23 €/KG with a 2% rabatt.
const ROW = {
  share_article_name: "Hühner",
  size: "S",
  sort: "braun.geschekt",
  amount: 2,
  unit: "KG",
  price_per_unit: 23,
  rabatt: 2,
};

function renderCol(
  cols: unknown[],
  key: string,
  value: unknown,
  record: unknown,
) {
  const col = (cols as { key?: string; render?: unknown }[]).find(
    (c) => c.key === key,
  )!;
  return (col.render as (v: unknown, r: unknown) => unknown)(value, record);
}

describe("useOtherArticleColumns", () => {
  it("renders amount in unit, per-unit price, rabatt, and rabatt-factored total", () => {
    const { result } = renderHook(() => useOtherArticleColumns());
    const cols = result.current;

    // amount in the unit (KG), not PU
    expect(renderCol(cols, "amount", null, ROW)).toBe("2.00 KG");
    // per-unit price
    expect(renderCol(cols, "price_per_unit", ROW.price_per_unit, ROW)).toBe(
      "23.00 €/KG",
    );
    // rabatt as a percentage
    expect(renderCol(cols, "rabatt", ROW.rabatt, ROW)).toBe("2 %");
    // net total = 2 * 23 * (1 - 2/100) = 45.08 — the rabatt IS factored in
    expect(renderCol(cols, "total", null, ROW)).toBe("45.08 €");
  });

  it("shows a dash for a missing rabatt", () => {
    const { result } = renderHook(() => useOtherArticleColumns());
    expect(renderCol(result.current, "rabatt", null, { ...ROW, rabatt: null })).toBe(
      "-",
    );
  });
});
