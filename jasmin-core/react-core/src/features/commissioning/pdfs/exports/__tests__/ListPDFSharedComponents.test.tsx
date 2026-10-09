/**
 * ListPDFSharedComponents: the header, footer, tick box and variation-totals
 * card every list PDF is built from.
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

import { styleOf } from "../../__tests__/pdfDomPrimitives";
import {
  ListPDFFooter,
  ListPDFHeader,
  TickBox,
  VariationsTotalsCard,
} from "../ListPDFSharedComponents";

const LABELS: Record<string, string> = {
  "common.page": "Page",
  "common.of": "of",
  "commissioning.variations_totals": "Totals per size",
  "commissioning.S": "small",
  "commissioning.M": "medium",
  "commissioning.L": "large",
};
const t = ((key: string) => LABELS[key] ?? key) as unknown as TFunction;

describe("ListPDFFooter", () => {
  it("prints the page number on every page", () => {
    const { container } = render(<ListPDFFooter t={t} />);
    expect(screen.getByText("Page 2 of 5")).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute("data-fixed", "true");
  });
});

describe("ListPDFHeader", () => {
  it("prints just the title without a tenant or a pill", () => {
    const { container } = render(
      <ListPDFHeader>
        <span>KW 12 · Tuesday</span>
      </ListPDFHeader>,
    );
    expect(container.textContent).toBe("KW 12 · Tuesday");
    expect(container.querySelector("img")).toBeNull();
  });

  it("prints the category pill above the title", () => {
    const { container } = render(
      <ListPDFHeader pill="Washing list">
        <span>KW 12</span>
      </ListPDFHeader>,
    );
    expect(container.textContent).toBe("Washing listKW 12");
    expect(styleOf(screen.getByText("Washing list"))).toMatchObject({
      textTransform: "uppercase",
    });
  });

  it("puts the tenant's logo, name and contact beside the title", () => {
    const { container } = render(
      <ListPDFHeader
        pill="Packing list"
        tenant={{
          name: "Green Farm",
          logoUrl: "data:image/png;base64,AAA",
          email: "office@farm.test",
          phone: "+43 1 234",
        }}
      >
        <span>KW 12</span>
      </ListPDFHeader>,
    );
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "data:image/png;base64,AAA",
    );
    expect(screen.getByText("Green Farm")).toBeInTheDocument();
    expect(screen.getByText("office@farm.test")).toBeInTheDocument();
    expect(screen.getByText("+43 1 234")).toBeInTheDocument();
    // Title column first, tenant column second.
    expect(container.textContent).toBe(
      "Packing listKW 12Green Farmoffice@farm.test+43 1 234",
    );
  });

  it("prints a tenant without a logo or contact as just its name", () => {
    const { container } = render(
      <ListPDFHeader tenant={{ name: "Green Farm", logoUrl: null }}>
        <span>KW 12</span>
      </ListPDFHeader>,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("KW 12Green Farm");
  });

  it("prints a logo-only tenant without a name line", () => {
    const { container } = render(
      <ListPDFHeader tenant={{ logoUrl: "logo.png" }}>
        <span>KW 12</span>
      </ListPDFHeader>,
    );
    expect(container.querySelector("img")).toHaveAttribute("src", "logo.png");
    expect(container.textContent).toBe("KW 12");
  });

  it("keeps the plain layout for a tenant with neither logo nor name", () => {
    const { container } = render(
      <ListPDFHeader tenant={{ email: "office@farm.test" }}>
        <span>KW 12</span>
      </ListPDFHeader>,
    );
    expect(container.textContent).toBe("KW 12");
  });
});

describe("TickBox", () => {
  it("draws an empty bordered square", () => {
    const { container } = render(<TickBox />);
    const box = container.firstElementChild!;
    expect(box.textContent).toBe("");
    expect(styleOf(box)).toMatchObject({ width: 11, height: 11, borderWidth: 1 });
  });
});

describe("VariationsTotalsCard", () => {
  it("renders nothing without totals", () => {
    const { container: none } = render(
      <VariationsTotalsCard variationsTotals={undefined} t={t} />,
    );
    expect(none).toBeEmptyDOMElement();
    const { container: empty } = render(
      <VariationsTotalsCard variationsTotals={[]} t={t} />,
    );
    expect(empty).toBeEmptyDOMElement();
  });

  it("lists each size with its total, zero included", () => {
    const { container } = render(
      <VariationsTotalsCard
        variationsTotals={[
          { id: 1, size: "S", totalQuantity: 12 },
          { id: 2, size: "L", totalQuantity: 0 },
          { size: "M", totalQuantity: "7" },
        ]}
        t={t}
      />,
    );
    expect(container.textContent).toBe(
      "Totals per sizesmall:12large:0medium:7",
    );
  });

  it("translates every size of a multi-size row and keeps unknown sizes as they are", () => {
    render(
      <VariationsTotalsCard
        variationsTotals={[
          { id: "a", size: "S, M", totalQuantity: 3 },
          { id: "b", size: "JUMBO", totalQuantity: 1 },
        ]}
        t={t}
      />,
    );
    expect(screen.getByText("small, medium:")).toBeInTheDocument();
    expect(screen.getByText("JUMBO:")).toBeInTheDocument();
  });
});
