import { render, screen } from "@testing-library/react";
import type { TFunction } from "i18next";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { CommissioningListResellersEntry } from "@shared/api/generated/models";

// The PDF primitives render as plain DOM so the document's text can be read.
vi.mock("@react-pdf/renderer", async (importOriginal) => {
  const passThrough = ({ children }: { children?: ReactNode }) => (
    <div>{children}</div>
  );
  return {
    ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
    Document: passThrough,
    Page: passThrough,
    View: passThrough,
    Text: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
    Image: () => null,
  };
});

vi.mock("@hooks/index", () => ({
  useUnitOptions: () => ({ getUnitLabel: (unit: string) => unit }),
  useVegetableSizeOptions: () => ({
    getVegetableSizeLabel: (size: string) =>
      ({ L: "large", S: "small" })[size] ?? size,
  }),
}));

import CommissioningListResellersPDF from "../CommissioningListResellersPDF";

const t = ((key: string) => key) as unknown as TFunction;

const content = (
  overrides: Partial<
    CommissioningListResellersEntry["order"]["contents"][number]
  >,
) => ({
  id: "content-1",
  share_article_id: "article-1",
  share_article_name: "Carrots",
  amount: 10,
  amount_per_pu: 2,
  size: "M",
  unit: "kg",
  sort: null,
  note: "",
  ...overrides,
});

const renderPdf = (
  contents: CommissioningListResellersEntry["order"]["contents"],
) =>
  render(
    <CommissioningListResellersPDF
      data={[
        {
          id: "reseller-1",
          name: "Green Grocer",
          order: { contents },
        } as unknown as CommissioningListResellersEntry,
      ]}
      year={2026}
      week={20}
      dayName="Tuesday"
      t={t}
    />,
  );

describe("CommissioningListResellersPDF article name", () => {
  it("prints the article's sort after its name, as the screen does", () => {
    renderPdf([content({ sort: "Nantaise" })]);
    expect(screen.getByText("Carrots Nantaise")).toBeInTheDocument();
  });

  it("prints the sort before the size", () => {
    renderPdf([content({ sort: "Nantaise", size: "L" })]);
    expect(screen.getByText("Carrots Nantaise, large")).toBeInTheDocument();
  });

  it("prints just the name without a sort or a non-default size", () => {
    renderPdf([content({ sort: null, size: "M" })]);
    expect(screen.getByText("Carrots")).toBeInTheDocument();
  });

  it("prints the size without a sort", () => {
    renderPdf([content({ sort: "", size: "L" })]);
    expect(screen.getByText("Carrots, large")).toBeInTheDocument();
  });
});
