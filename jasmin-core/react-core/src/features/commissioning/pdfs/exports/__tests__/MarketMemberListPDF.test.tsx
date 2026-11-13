/**
 * MarketMemberListPDF: the current members for the market stand, one row each
 * with a box to tick.
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

import MarketMemberListPDF from "../MarketMemberListPDF";

const t = ((key: string, values?: Record<string, unknown>) =>
  values ? `${key} ${JSON.stringify(values)}` : key) as unknown as TFunction;

const MEMBERS = [
  { id: "m-1", last_name: "Abel", first_name: "Jana", member_number: 12 },
  { id: "m-2", last_name: "Bauer", first_name: "Lisa", member_number: 45 },
];

describe("MarketMemberListPDF", () => {
  it("prints the day it is as of and each member in the given order", () => {
    render(<MarketMemberListPDF members={MEMBERS} asOf="12.11.2026" t={t} />);

    expect(screen.getByText("commissioning.market_member_list")).toBeInTheDocument();
    expect(
      screen.getByText('commissioning.market_member_list_as_of {"date":"12.11.2026"}'),
    ).toBeInTheDocument();
    const rows = screen
      .getAllByText(/^(Abel|Bauer)$/)
      .map((name) => name.closest("[data-wrap='false']")?.textContent);
    expect(rows).toEqual(["AbelJana12", "BauerLisa45"]);
  });

  it("gives each member a box to tick", () => {
    render(<MarketMemberListPDF members={MEMBERS} asOf="12.11.2026" t={t} />);

    for (const name of ["Abel", "Bauer"]) {
      const row = screen.getByText(name).closest("[data-wrap='false']");
      const cells = [...(row?.children ?? [])];
      expect(cells).toHaveLength(4);
      expect(cells[3].querySelector("[data-pdf='view']")).not.toBeNull();
    }
  });
});
