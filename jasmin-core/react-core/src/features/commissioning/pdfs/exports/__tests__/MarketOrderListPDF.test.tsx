/**
 * MarketOrderListPDF: the market's order form for a week, every PLU by product
 * group with the week's price and blank columns for the stock and the order.
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

import MarketOrderListPDF from "../MarketOrderListPDF";

const t = ((key: string) => key) as unknown as TFunction;

const GROUPS = [
  {
    label: "4 Apples",
    rows: [
      { id: "plu-101", plu_number: 101, name: "Elstar apple DE", unit_label: "kg", price_text: "3,49 €" },
      { id: "plu-110", plu_number: 110, name: "Boskoop apple", unit_label: "kg", price_text: "" },
    ],
  },
  { label: "15 Bread", rows: [] },
];

describe("MarketOrderListPDF", () => {
  it("prints the week, the groups that have PLUs and each PLU's price", () => {
    render(
      <MarketOrderListPDF groups={GROUPS} year={2026} week={47} subtitle="Picked groups" t={t} />,
    );

    expect(screen.getByText("commissioning.market_order_list")).toBeInTheDocument();
    expect(screen.getByText(/47\/2026/)).toBeInTheDocument();
    expect(screen.getByText("Picked groups")).toBeInTheDocument();
    expect(screen.getByText("4 Apples")).toBeInTheDocument();
    expect(screen.queryByText("15 Bread")).not.toBeInTheDocument();
    expect(screen.getByText("Elstar apple DE")).toBeInTheDocument();
    expect(screen.getByText("3,49 €")).toBeInTheDocument();
    expect(screen.getByText("Boskoop apple")).toBeInTheDocument();
  });

  it("leaves a column for the stock and one for the order on every row", () => {
    const { container } = render(
      <MarketOrderListPDF groups={GROUPS} year={2026} week={47} t={t} />,
    );

    expect(screen.getByText("commissioning.in_stock")).toBeInTheDocument();
    expect(screen.getByText("commissioning.order_amount")).toBeInTheDocument();
    const row = screen.getByText("Boskoop apple").closest("[data-wrap='false']");
    const cells = [...(row?.children ?? [])];
    expect(cells).toHaveLength(6);
    expect(cells.slice(4).map((cell) => cell.textContent)).toEqual(["", ""]);
    expect(container.querySelectorAll("[data-fixed='true']").length).toBeGreaterThan(0);
  });
});
