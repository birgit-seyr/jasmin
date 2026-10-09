// The CSV template button's upload: the import endpoint is mocked at the axios
// boundary, and the toasts are read off the shared `notify`.

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

const { notifyMock, postMock, messageForErrorCodeMock } = vi.hoisted(() => ({
  notifyMock: { success: vi.fn(), error: vi.fn() },
  postMock: vi.fn(),
  messageForErrorCodeMock: vi.fn(),
}));

vi.mock("@shared/utils", () => ({
  notify: notifyMock,
  downloadBlob: vi.fn(),
}));

vi.mock("@shared/services/api", () => ({
  default: { post: postMock },
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
  postMock.mockReset();
  messageForErrorCodeMock.mockReset();
});

describe("DownloadCsvTemplateButton upload", () => {
  it("confirms a fully successful import with a toast", async () => {
    postMock.mockResolvedValue({
      data: { successful: 3, failed: 0, errors: [] },
    });
    const { input, onImported } = renderButton();

    await userEvent.upload(input, csvFile());

    await waitFor(() =>
      expect(notifyMock.success).toHaveBeenCalledWith(
        "csv_upload.import_success",
      ),
    );
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(notifyMock.error).not.toHaveBeenCalled();
  });

  it("reports a refused upload with the server's message", async () => {
    postMock.mockRejectedValue({
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
    postMock.mockResolvedValue({ data: failedImport });
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

  it("shows the server's text for a row error without a code", async () => {
    postMock.mockResolvedValue({
      data: {
        ...failedImport,
        failed: 1,
        errors: [{ row: 4, error: "Something broke.", data: {} }],
      },
    });
    const { input } = renderButton();

    await userEvent.upload(input, csvFile());

    expect(await screen.findByText("Something broke.")).toBeInTheDocument();
    expect(messageForErrorCodeMock).not.toHaveBeenCalled();
  });
});
