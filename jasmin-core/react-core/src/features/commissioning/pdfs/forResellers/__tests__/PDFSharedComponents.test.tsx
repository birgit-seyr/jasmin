/**
 * PDFSharedComponents: the blocks every reseller document (invoice, delivery
 * note, offer) shares — logo, address blocks, entry and greeting lines, the
 * hash bar of a finalized document, the organic disclosure and the footer.
 */
import { render, screen } from "@testing-library/react";
import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";

vi.mock("@react-pdf/renderer", async (importOriginal) => {
  const { pdfDomPrimitives } = await import(
    "@features/commissioning/pdfs/__tests__/pdfDomPrimitives"
  );
  return {
    ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
    ...pdfDomPrimitives(),
  };
});

import type { LineItemBase, TenantPDFSettings } from "../pdfBase";
import {
  PDFEntryLines,
  PDFFooter,
  PDFGreetingLines,
  PDFHashBar,
  PDFLogo,
  PDFOrganicFooter,
  PDFResellerInfo,
  PDFTenantInfo,
} from "../PDFSharedComponents";

const LABELS: Record<string, string> = {
  "common.page": "Page",
  "commissioning.organic.organic_footer": "Organic, control body",
  "commissioning.organic.in_conversion_footer": "In conversion, control body",
};
const t = ((key: string) => LABELS[key] ?? key) as unknown as TFunction;

const tenantSettings: TenantPDFSettings = {
  name: "Green Farm",
  address: "Field Road 1",
  zip_code: "1010",
  city: "Vienna",
  email: "office@farm.test",
  phone_number: "+43 1 234",
};

describe("PDFLogo", () => {
  it("prints the tenant's logo", () => {
    const { container } = render(
      <PDFLogo tenantSettings={{ logo: "data:image/png;base64,AAA" }} />,
    );
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "data:image/png;base64,AAA",
    );
  });

  it("prints nothing without a logo", () => {
    const { container } = render(<PDFLogo tenantSettings={{ logo: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("prints a LOGO placeholder box for a preview without a logo", () => {
    const { container } = render(<PDFLogo tenantSettings={{}} placeholder />);
    expect(screen.getByText("LOGO")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("prefers the real logo over the placeholder", () => {
    const { container } = render(
      <PDFLogo tenantSettings={{ logo: "logo.png" }} placeholder />,
    );
    expect(container.querySelector("img")).toHaveAttribute("src", "logo.png");
    expect(screen.queryByText("LOGO")).toBeNull();
  });
});

describe("PDFResellerInfo", () => {
  it("prints the sender line and the reseller's full address", () => {
    const { container } = render(
      <PDFResellerInfo
        tenantSettings={tenantSettings}
        resellerInfo={{
          reseller_name: "Corner Shop",
          reseller_address: "Main Street 5",
          reseller_zip: "8010",
          reseller_city: "Graz",
          reseller_uid: "ATU12345678",
        }}
      />,
    );
    expect(
      screen.getByText("Green Farm - Field Road 1 - 1010 Vienna"),
    ).toBeInTheDocument();
    const lines = Array.from(
      container.querySelectorAll("[data-pdf='text']"),
    ).map((line) => line.textContent);
    expect(lines).toEqual([
      "Green Farm - Field Road 1 - 1010 Vienna",
      "Corner Shop",
      "Main Street 5",
      "8010 Graz",
      "UID: ATU12345678",
    ]);
  });

  it("leaves out the street and the UID line when the reseller has none", () => {
    const { container } = render(
      <PDFResellerInfo
        tenantSettings={tenantSettings}
        resellerInfo={{
          reseller_name: "Corner Shop",
          reseller_address: null,
          reseller_zip: "8010",
          reseller_city: "Graz",
          reseller_uid: null,
        }}
      />,
    );
    expect(screen.queryByText(/UID/)).toBeNull();
    expect(container.querySelectorAll("[data-pdf='text']")).toHaveLength(3);
  });
});

describe("PDFTenantInfo", () => {
  it("prints the tenant's address block with the general email", () => {
    const { container } = render(
      <PDFTenantInfo tenantSettings={tenantSettings} />,
    );
    expect(
      Array.from(container.querySelectorAll("[data-pdf='text']")).map(
        (line) => line.textContent,
      ),
    ).toEqual([
      "Green Farm",
      "Field Road 1",
      "1010 Vienna",
      "office@farm.test",
      "+43 1 234",
    ]);
  });

  it("prints the orders email instead when there is one, and the extra lines below", () => {
    render(
      <PDFTenantInfo
        tenantSettings={{ ...tenantSettings, email_for_orders: "orders@farm.test" }}
      >
        <span>Invoice no. 7</span>
      </PDFTenantInfo>,
    );
    expect(screen.getByText("orders@farm.test")).toBeInTheDocument();
    expect(screen.queryByText("office@farm.test")).toBeNull();
    expect(screen.getByText("Invoice no. 7")).toBeInTheDocument();
  });
});

describe("PDFEntryLines", () => {
  it("prints nothing when every line is empty", () => {
    const { container } = render(
      <PDFEntryLines lines={[undefined, null, ""]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("prints the set lines as rich text and skips the empty ones", () => {
    const { container } = render(
      <PDFEntryLines
        lines={["<p>Dear <strong>customer</strong>,</p>", null, "<p>thanks.</p>"]}
      />,
    );
    expect(container.textContent).toBe("Dear customer,thanks.");
    expect(screen.getByText("customer").getAttribute("data-style")).toContain(
      "bold",
    );
  });
});

describe("PDFGreetingLines", () => {
  it("keeps the greeting and the signature together on one page", () => {
    const { container } = render(
      <PDFGreetingLines lines={["<p>Kind regards</p>", undefined, ""]}>
        <span>Signature</span>
      </PDFGreetingLines>,
    );
    expect(container.firstElementChild).toHaveAttribute("data-wrap", "false");
    expect(container.textContent).toBe("Kind regardsSignature");
  });

  it("still renders its block when there are no greeting lines", () => {
    const { container } = render(<PDFGreetingLines lines={[null]} />);
    expect(container.firstElementChild).not.toBeNull();
    expect(container.textContent).toBe("");
  });
});

describe("PDFHashBar", () => {
  it("prints nothing for a document that has no hash", () => {
    const { container } = render(
      <PDFHashBar finalizedAt="2026-03-05T14:30:00" t={t} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("prints the hash, the finalization time in the tenant's format and the page on every page", () => {
    const { container } = render(
      <PDFHashBar
        documentHash="ab12cd34"
        finalizedAt="2026-03-05T14:30:00"
        dateFormat="YYYY-MM-DD"
        t={t}
      />,
    );
    expect(container.firstElementChild).toHaveAttribute("data-fixed", "true");
    expect(screen.getByText("ab12cd34 | 2026-03-05 14:30")).toBeInTheDocument();
    expect(screen.getByText("Page 2 / 5")).toBeInTheDocument();
  });

  it("uses DD.MM.YYYY when no format is given", () => {
    render(
      <PDFHashBar
        documentHash="ab12cd34"
        finalizedAt="2026-03-05T09:05:00"
        t={t}
      />,
    );
    expect(screen.getByText("ab12cd34 | 05.03.2026 09:05")).toBeInTheDocument();
  });

  it("prints the hash alone when the finalization time is missing", () => {
    render(<PDFHashBar documentHash="ab12cd34" finalizedAt={null} t={t} />);
    expect(screen.getByText("ab12cd34 |")).toBeInTheDocument();
  });
});

describe("PDFOrganicFooter", () => {
  const certified: TenantPDFSettings = {
    organic_control_number: "AT-BIO-301",
    bio_logo: "data:image/png;base64,BIO",
  };
  const line = (organic_status?: LineItemBase["organic_status"]) => ({
    amount: 1,
    price_per_unit: 1,
    organic_status,
  });

  it("prints nothing for a tenant without a control number", () => {
    const { container } = render(
      <PDFOrganicFooter
        tenantSettings={{ organic_control_number: null }}
        lineItems={[line("organic")]}
        t={t}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("prints nothing when no line carries an organic mark", () => {
    const { container } = render(
      <PDFOrganicFooter
        tenantSettings={certified}
        lineItems={[line("conventional"), line(undefined)]}
        t={t}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("prints the organic disclosure with the mark when organic lines are present", () => {
    const { container } = render(
      <PDFOrganicFooter
        tenantSettings={certified}
        lineItems={[line("conventional"), line("organic")]}
        t={t}
      />,
    );
    expect(container.firstElementChild).toHaveAttribute("data-wrap", "false");
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "data:image/png;base64,BIO",
    );
    expect(
      screen.getByText("* Organic, control body: AT-BIO-301"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^\*\* /)).toBeNull();
  });

  it("prints only the in-conversion disclosure for in-conversion lines", () => {
    render(
      <PDFOrganicFooter
        tenantSettings={certified}
        lineItems={[line("in_conversion")]}
        t={t}
      />,
    );
    expect(
      screen.getByText("** In conversion, control body: AT-BIO-301"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^\* Organic/)).toBeNull();
  });

  it("prints both disclosures, text-only without a mark image", () => {
    const { container } = render(
      <PDFOrganicFooter
        tenantSettings={{ organic_control_number: "AT-BIO-301" }}
        lineItems={[line("in_conversion"), line("organic")]}
        t={t}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe(
      "* Organic, control body: AT-BIO-301** In conversion, control body: AT-BIO-301",
    );
  });
});

describe("PDFFooter", () => {
  it("prints nothing without footer settings", () => {
    const { container } = render(<PDFFooter />);
    expect(container).toBeEmptyDOMElement();
  });

  it("prints the three columns as rich text on every page", () => {
    const { container } = render(
      <PDFFooter
        footerSettings={{
          left_column_footer_documents_reseller: "<p>Green Farm</p><p>Field Road 1</p>",
          middle_column_footer_documents_reseller: "<p>IBAN AT00 1234</p>",
          right_column_footer_documents_reseller: "<p><em>Thank you</em></p>",
        }}
      />,
    );
    const footer = container.firstElementChild!;
    expect(footer).toHaveAttribute("data-fixed", "true");
    const columns = Array.from(footer.children).map((col) => col.textContent);
    expect(columns).toEqual([
      "Green FarmField Road 1",
      "IBAN AT00 1234",
      "Thank you",
    ]);
  });

  it("leaves an unset column empty", () => {
    const { container } = render(
      <PDFFooter
        footerSettings={{ middle_column_footer_documents_reseller: "<p>Bank</p>" }}
      />,
    );
    const columns = Array.from(container.firstElementChild!.children).map(
      (col) => col.textContent,
    );
    expect(columns).toEqual(["", "Bank", ""]);
  });
});
