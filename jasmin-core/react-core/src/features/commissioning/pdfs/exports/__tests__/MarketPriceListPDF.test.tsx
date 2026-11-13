/**
 * MarketPriceListPDF: the week's market price list, one section per product
 * group, a price that changed since last week in bold.
 */
import { render, screen } from "@testing-library/react";
import type { TFunction } from "i18next";
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

vi.mock("@react-pdf/renderer", async (importOriginal) => {
  const { pdfDomPrimitives } = await import(
    "@features/commissioning/pdfs/__tests__/pdfDomPrimitives"
  );
  return {
    ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
    ...pdfDomPrimitives(),
  };
});

import { styleOf } from "@features/commissioning/pdfs/__tests__/pdfDomPrimitives";
import MarketPriceListPDF from "../MarketPriceListPDF";

const t = ((key: string) => key) as unknown as TFunction;

const GROUPS = [
  {
    label: "4 Apples",
    rows: [
      { id: "p-1", plu_number: 101, name: "Elstar apple DE", price_text: "3,49 €/kg", is_changed: true },
      { id: "p-2", plu_number: 102, name: "Topaz apple", price_text: "2,99 €/kg", is_changed: false },
    ],
  },
  { label: "9 Leafy greens", rows: [] },
  {
    label: "No product group",
    rows: [
      { id: "p-3", plu_number: 300, name: "Rye bread", price_text: "4,20 €/St.", is_changed: false },
    ],
  },
];

describe("MarketPriceListPDF", () => {
  it("prints the week and one section per product group that has prices", () => {
    render(<MarketPriceListPDF groups={GROUPS} year={2026} week={46} t={t} />);

    expect(screen.getByText("commissioning.market_price_list")).toBeInTheDocument();
    expect(screen.getByText(/46\/2026/)).toBeInTheDocument();
    expect(screen.getByText("4 Apples")).toBeInTheDocument();
    expect(screen.getByText("No product group")).toBeInTheDocument();
    expect(screen.queryByText("9 Leafy greens")).not.toBeInTheDocument();
  });

  it("prints what the list was narrowed to under its title", () => {
    render(
      <MarketPriceListPDF
        groups={GROUPS}
        year={2026}
        week={46}
        subtitle="Changed prices only · 4 Apples"
        t={t}
      />,
    );

    expect(screen.getByText("Changed prices only · 4 Apples")).toBeInTheDocument();
  });

  it("prints one column header, repeated on each page, above all groups", () => {
    render(<MarketPriceListPDF groups={GROUPS} year={2026} week={46} t={t} />);

    const headers = screen.getAllByText("commissioning.plu_number");
    expect(headers).toHaveLength(1);
    expect(headers[0].closest("[data-fixed='true']")).not.toBeNull();
  });

  it("prints a changed price in bold and the others plain", () => {
    render(<MarketPriceListPDF groups={GROUPS} year={2026} week={46} t={t} />);

    expect(styleOf(screen.getByText("Elstar apple DE")).fontWeight).toBe(700);
    expect(styleOf(screen.getByText("3,49 €/kg")).fontWeight).toBe(700);
    expect(styleOf(screen.getByText("Topaz apple")).fontWeight).toBe(400);
    expect(styleOf(screen.getByText("2,99 €/kg")).fontWeight).toBe(400);
  });
});
