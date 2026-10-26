// The CSV template button's upload: the generated import client is the mocking
// boundary, and the toasts are read off the shared `notify`.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// German copy for the type-hint keys, so the template can be read as a German
// office would get it; every other key comes back as itself.
const germanTypeHints: Record<string, string> = {
  "csv_upload.type_hint.text": "Text",
  "csv_upload.type_hint.decimal_2dp": "Dezimalzahl (2 Nachkommastellen)",
  "csv_upload.type_hint.week_number": "Kalenderwoche",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      germanTypeHints[key] ??
      (typeof fallback === "string" ? fallback : key),
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { notifyMock, importMock, messageForErrorCodeMock, downloadCsvBlobMock } =
  vi.hoisted(() => ({
    notifyMock: { success: vi.fn(), error: vi.fn() },
    importMock: vi.fn(),
    messageForErrorCodeMock: vi.fn(),
    downloadCsvBlobMock: vi.fn(),
  }));

vi.mock("@shared/utils", async () => {
  const csv =
    await vi.importActual<typeof import("@shared/utils/csv")>(
      "@shared/utils/csv",
    );
  return {
    notify: notifyMock,
    buildCsvString: csv.buildCsvString,
    resolveCsvDialect: csv.resolveCsvDialect,
    downloadCsvBlob: downloadCsvBlobMock,
  };
});

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningDataImportCreate: (body: unknown) => importMock(body),
}));

vi.mock("@shared/utils/apiError", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils/apiError")>()),
  messageForErrorCode: messageForErrorCodeMock,
}));

import DownloadCsvTemplateButton from "../DownloadCsvTemplateButton";

const csvFile = () =>
  new File(["name\nCarrots\n"], "articles.csv", { type: "text/csv" });

function renderButton(onImported = vi.fn()) {
  const { container } = render(
    <DownloadCsvTemplateButton
      columns={[{ dataIndex: "name", title: "Name" }]}
      filename="articles"
      modelName="ShareArticle"
      onImported={onImported}
    />,
  );
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No upload input rendered");
  return { input, onImported };
}

beforeEach(() => {
  notifyMock.success.mockReset();
  notifyMock.error.mockReset();
  importMock.mockReset();
  messageForErrorCodeMock.mockReset();
  downloadCsvBlobMock.mockReset();
});


describe("DownloadCsvTemplateButton template", () => {
  it("writes the type-hint row in the office's language", async () => {
    render(
      <DownloadCsvTemplateButton
        columns={[
          { dataIndex: "name", title: "Name", inputType: "text" },
          { dataIndex: "price", title: "Preis", inputType: "decimal2" },
          { dataIndex: "week", title: "KW", inputType: "kw" },
        ]}
        filename="articles"
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /download.csv_template/ }),
    );

    expect(downloadCsvBlobMock).toHaveBeenCalledTimes(1);
    const [csv, filename] = downloadCsvBlobMock.mock.calls[0] as [string, string];
    expect(filename).toBe("articles");
    const rows = csv.split("\n");
    expect(rows).toEqual([
      "Name,Preis,KW",
      "name,price,week",
      "Text,Dezimalzahl (2 Nachkommastellen),Kalenderwoche",
    ]);
  });

  it("renders no empty dry-run wrapper when the dry run is off", () => {
    const { container } = render(
      <DownloadCsvTemplateButton
        columns={[{ dataIndex: "name", title: "Name" }]}
        filename="articles"
        modelName="ShareArticle"
      />,
    );

    const emptyDivs = Array.from(container.querySelectorAll("div")).filter(
      (div) => div.childElementCount === 0 && div.textContent === "",
    );
    expect(emptyDivs).toEqual([]);
    expect(
      screen.queryByRole("button", { name: /csv_upload.validate/ }),
    ).not.toBeInTheDocument();
  });

  it("offers the dry run when it is on", () => {
    render(
      <DownloadCsvTemplateButton
        columns={[{ dataIndex: "name", title: "Name" }]}
        filename="articles"
        modelName="ShareArticle"
        allowDryRun
      />,
    );

    expect(
      screen.getByRole("button", { name: /csv_upload.validate/ }),
    ).toBeInTheDocument();
  });
});

describe("DownloadCsvTemplateButton upload", () => {
  it("confirms a fully successful import with a toast", async () => {
    importMock.mockResolvedValue({ successful: 3, failed: 0, errors: [] });
    const { input, onImported } = renderButton();
    const file = csvFile();

    await userEvent.upload(input, file);

    await waitFor(() =>
      expect(notifyMock.success).toHaveBeenCalledWith(
        "csv_upload.import_success",
      ),
    );
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(notifyMock.error).not.toHaveBeenCalled();
    expect(importMock).toHaveBeenCalledWith({
      model_name: "ShareArticle",
      file: expect.objectContaining({ name: file.name }),
    });
  });

  it("reports a refused upload with the server's message", async () => {
    importMock.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { message: "The file is empty." } },
    });
    const { input, onImported } = renderButton();

    await userEvent.upload(input, csvFile());

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith("The file is empty."),
    );
    expect(onImported).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("DownloadCsvTemplateButton row errors", () => {
  const failedImport = {
    model_name: "subscription",
    total_rows: 2,
    successful: 0,
    failed: 2,
    results: [],
    errors: [
      {
        row: 4,
        error: "MemberNumberUnknown: No member with number 9999.",
        data: {},
        code: "member.number_unknown",
        field: "member_number",
        details: { member_number: 9999 },
      },
      {
        row: 5,
        error: "quantity: A valid integer is required.",
        data: {},
        code: "data_import.row_invalid",
        field: "quantity",
      },
    ],
  };

  it("shows a coded row error in its translation, else the server's text", async () => {
    messageForErrorCodeMock.mockImplementation(
      (code: string, details?: Record<string, unknown>) =>
        code === "member.number_unknown"
          ? `Kein Mitglied hat die Mitgliedsnummer ${String(details?.member_number)}.`
          : undefined,
    );
    importMock.mockResolvedValue(failedImport);
    const { input } = renderButton();

    await userEvent.upload(input, csvFile());

    expect(
      await screen.findByText("Kein Mitglied hat die Mitgliedsnummer 9999."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("quantity: A valid integer is required."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("MemberNumberUnknown: No member with number 9999."),
    ).not.toBeInTheDocument();
    expect(messageForErrorCodeMock).toHaveBeenCalledWith(
      "member.number_unknown",
      { member_number: 9999 },
    );
  });

  it("lists each failed row in a table with its row number and message", async () => {
    messageForErrorCodeMock.mockImplementation((code: string) =>
      code === "member.number_unknown" ? "Unknown member number." : undefined,
    );
    importMock.mockResolvedValue(failedImport);
    const { input } = renderButton();

    await userEvent.upload(input, csvFile());

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("csv_upload.errors_heading"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("columnheader", { name: "csv_upload.col_row" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("columnheader", { name: "csv_upload.col_error" }),
    ).toBeInTheDocument();
    const rows = within(dialog)
      .getAllByRole("row")
      .filter((row) => row.getAttribute("data-row-key") !== null);
    expect(rows.map((row) => row.getAttribute("data-row-key"))).toEqual([
      "4",
      "5",
    ]);
    expect(within(rows[0]).getByText("4")).toBeInTheDocument();
    expect(
      within(rows[0]).getByText("Unknown member number."),
    ).toBeInTheDocument();
    expect(within(rows[1]).getByText("5")).toBeInTheDocument();
    expect(
      within(rows[1]).getByText("quantity: A valid integer is required."),
    ).toBeInTheDocument();
  });

  it("shows the server's text for a row error without a code", async () => {
    importMock.mockResolvedValue({
      ...failedImport,
      failed: 1,
      errors: [{ row: 4, error: "Something broke.", data: {} }],
    });
    const { input } = renderButton();

    await userEvent.upload(input, csvFile());

    expect(await screen.findByText("Something broke.")).toBeInTheDocument();
    expect(messageForErrorCodeMock).not.toHaveBeenCalled();
  });
});
