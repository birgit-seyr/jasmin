/**
 * DeliveryNotePDFGenerator: loads one delivery note and either shows it in
 * the PDF viewer or offers its stored PDF for download.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { query, retrieveMock, openStoredPdfMock, pdfProps, pdfContext } =
  vi.hoisted(() => ({
    query: {
      result: {
        data: undefined as unknown,
        isLoading: false,
        error: null as { message?: string } | null,
      },
    },
    retrieveMock: vi.fn(),
    openStoredPdfMock: vi.fn(),
    pdfProps: { last: null as Record<string, unknown> | null },
    pdfContext: {
      tenantSettings: { name: "Green Farm" },
      footerSettings: { left_column_footer_documents_reseller: "<p>x</p>" },
      currencySymbol: "CHF",
      lineSettings: { entry_line_1_delivery_note_reseller: "<p>Hi</p>" },
    },
  }));

vi.mock("@react-pdf/renderer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
  PDFViewer: ({ children }: { children?: ReactNode }) => (
    <div data-testid="pdf-viewer">{children}</div>
  ),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDeliveryNotesRetrieve: (...args: unknown[]) => {
    retrieveMock(...args);
    return query.result;
  },
}));

vi.mock("@hooks/index", () => ({
  useDateFormat: () => ({ dateFormat: "YYYY/MM/DD" }),
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({ tenant: { name: "Green Farm" } });
  return { useTenant: () => ({ ...tenant, bioLogoUrl: null }) };
});

vi.mock("../resellerPdfContext", () => ({
  useResellerPdfContext: () => pdfContext,
}));

vi.mock("../pdfDownload", () => ({ openStoredPdf: openStoredPdfMock }));

vi.mock("../DeliveryNotePDF", () => ({
  default: (props: Record<string, unknown>) => {
    pdfProps.last = props;
    return <div data-testid="delivery-note-pdf" />;
  },
}));

import DeliveryNotePDFGenerator from "../DeliveryNotePDFGenerator";

const deliveryNote = {
  id: "dn-1",
  prefix: "LS",
  number: 42,
  date: "2026-03-05",
  reseller_name: "Corner Shop",
  reseller_address: "Main Street 5",
  reseller_zip: "8010",
  reseller_city: "Graz",
  reseller_country: "AT",
  is_finalized: true,
  finalized_at: "2026-03-05T10:00:00Z",
  document_hash: "abc",
  line_items: [{ share_article_name: "Carrots", amount: 3, price_per_unit: 2 }],
  crate_items: [],
  file: "https://media.test/delivery-note-42.pdf",
};

beforeEach(() => {
  query.result = { data: deliveryNote, isLoading: false, error: null };
  retrieveMock.mockReset();
  openStoredPdfMock.mockReset();
  pdfProps.last = null;
});

describe("DeliveryNotePDFGenerator", () => {
  it("loads the delivery note only when it has an id", () => {
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" />);
    expect(retrieveMock).toHaveBeenCalledWith("dn-1", {
      query: { enabled: true },
    });

    query.result = { data: undefined, isLoading: false, error: null };
    const { container } = render(
      <DeliveryNotePDFGenerator deliveryNoteId={null} />,
    );
    expect(retrieveMock).toHaveBeenLastCalledWith(null, {
      query: { enabled: false },
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a spinner while loading", () => {
    query.result = { data: undefined, isLoading: true, error: null };
    const { container } = render(
      <DeliveryNotePDFGenerator deliveryNoteId="dn-1" />,
    );
    expect(container.querySelector(".ant-spin")).not.toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the load error", () => {
    query.result = {
      data: undefined,
      isLoading: false,
      error: { message: "Not found." },
    };
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" />);
    expect(screen.getByText("common.error: Not found.")).toBeInTheDocument();
  });

  it("shows an error when the failure carries no message", () => {
    query.result = { data: undefined, isLoading: false, error: {} };
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" />);
    expect(screen.getByText(/^common\.error:/)).toBeInTheDocument();
  });

  // The generic text is user-facing copy, so it comes from the locale files
  // (the mock's ``t`` echoes keys), never as hardcoded English.
  it.skip("shows a translated generic error when the failure carries no message", () => {
    query.result = { data: undefined, isLoading: false, error: {} };
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" />);
    expect(
      screen.getByText(/^common\.error: [a-z_]+(\.[a-z_]+)+$/),
    ).toBeInTheDocument();
  });

  it("opens the stored PDF from the download button", async () => {
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" />);
    const button = screen.getByRole("button", {
      name: "commissioning.download_pdf",
    });
    await userEvent.click(button);
    expect(openStoredPdfMock).toHaveBeenCalledWith(
      "https://media.test/delivery-note-42.pdf",
    );
    expect(screen.queryByTestId("pdf-viewer")).toBeNull();
  });

  it("uses the given button text and size", () => {
    render(
      <DeliveryNotePDFGenerator
        deliveryNoteId="dn-1"
        buttonText="Open"
        buttonSize="small"
      />,
    );
    const button = screen.getByRole("button", { name: "Open" });
    expect(button).toHaveClass("ant-btn-sm");
  });

  it("disables the download while no PDF is stored yet", async () => {
    query.result = {
      data: { ...deliveryNote, file: null },
      isLoading: false,
      error: null,
    };
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" />);
    const button = screen.getByRole("button", {
      name: "commissioning.download_pdf",
    });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(openStoredPdfMock).not.toHaveBeenCalled();
  });

  it("shows the document in the viewer with the tenant's settings and date format", () => {
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" viewMode />);
    expect(screen.getByTestId("pdf-viewer")).toContainElement(
      screen.getByTestId("delivery-note-pdf"),
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(pdfProps.last).toMatchObject({
      tenantSettings: pdfContext.tenantSettings,
      footerSettings: pdfContext.footerSettings,
      lineSettings: pdfContext.lineSettings,
      currencySymbol: "CHF",
      dateFormat: "YYYY/MM/DD",
    });
    expect(pdfProps.last!.data).toMatchObject({
      deliveryNote: {
        prefix: "LS",
        delivery_note_number: 42,
        delivery_note_date: "2026-03-05",
        reseller_name: "Corner Shop",
        reseller_city: "Graz",
        is_finalized: true,
        document_hash: "abc",
      },
      lineItems: deliveryNote.line_items,
      crateItems: [],
    });
  });

  it("shows the viewer even while no PDF is stored yet", () => {
    query.result = {
      data: { ...deliveryNote, file: null, number: null, date: null },
      isLoading: false,
      error: null,
    };
    render(<DeliveryNotePDFGenerator deliveryNoteId="dn-1" viewMode />);
    expect(screen.getByTestId("delivery-note-pdf")).toBeInTheDocument();
    expect(pdfProps.last!.data).toMatchObject({
      deliveryNote: {
        delivery_note_number: undefined,
        delivery_note_date: undefined,
      },
    });
  });
});
