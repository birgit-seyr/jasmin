/**
 * ListPDFGenerator: the Download button of the list PDFs, which loads the PDF
 * library and the document on click, renders the document and hands the file
 * to the browser.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const { notifyMock, downloadBlobMock, toBlobMock, pdfMock } = vi.hoisted(() => ({
  notifyMock: { error: vi.fn() },
  downloadBlobMock: vi.fn(),
  toBlobMock: vi.fn(),
  pdfMock: vi.fn(),
}));

vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  downloadBlob: downloadBlobMock,
}));

vi.mock("@react-pdf/renderer", () => ({
  pdf: (element: unknown) => {
    pdfMock(element);
    return { toBlob: toBlobMock };
  },
}));

import ListPDFGenerator from "../ListPDFGenerator";

const ListDocument = (_props: { rows?: string[] }) => null;

function renderButton(
  documentProps:
    | { rows?: string[] }
    | (() => Promise<{ rows?: string[] }>) = {},
) {
  render(
    <ListPDFGenerator
      data={[{ id: 1 }]}
      filename="washing-list"
      buttonText="Download"
      documentLoader={async () => ({ default: ListDocument })}
      documentProps={documentProps}
    />,
  );
}

beforeEach(() => {
  notifyMock.error.mockReset();
  downloadBlobMock.mockReset();
  toBlobMock.mockReset();
  pdfMock.mockReset();
});

describe("ListPDFGenerator", () => {
  it("downloads the rendered list", async () => {
    const blob = new Blob(["%PDF"]);
    toBlobMock.mockResolvedValue(blob);
    renderButton();

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    await waitFor(() =>
      expect(downloadBlobMock).toHaveBeenCalledWith(blob, "washing-list.pdf"),
    );
    expect(notifyMock.error).not.toHaveBeenCalled();
  });

  it("tells the user when the PDF could not be generated", async () => {
    toBlobMock.mockRejectedValue(new Error("layout failed"));
    renderButton();

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith("common.error_exporting"),
    );
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });

  it("fetches the document's props on click when given a loader", async () => {
    toBlobMock.mockResolvedValue(new Blob(["%PDF"]));
    const loadProps = vi.fn(async () => ({ rows: ["Abel"] }));
    renderButton(loadProps);

    expect(loadProps).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    await waitFor(() => expect(downloadBlobMock).toHaveBeenCalled());
    expect(pdfMock.mock.calls[0][0].props).toEqual({ rows: ["Abel"] });
  });

  it("tells the user when the props could not be fetched", async () => {
    renderButton(async () => {
      throw new Error("403");
    });

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith("common.error_exporting"),
    );
    expect(pdfMock).not.toHaveBeenCalled();
    expect(downloadBlobMock).not.toHaveBeenCalled();
  });
});
