/**
 * The list pages' CSV import affordance.
 *
 * What matters here: the button is gated on the tenant setting and on the
 * office, the only role the import endpoint takes, and the modal offers a DRY
 * RUN, so an office user learns about a bad file before importing it.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@shared/services/api";
import { CsvImportButton } from "../CsvImportModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.entity ? `${key}:${String(opts.entity)}` : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@shared/services/api", () => ({ default: { post: vi.fn() } }));

// ``useRoles`` is real; it reads the signed-in user's roles from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

beforeEach(() => {
  auth.roles = ["office"];
});

const COLUMNS = [
  { dataIndex: "name", title: "Name", required: true },
  { dataIndex: "number", title: "Number", inputType: "integer" },
  // Read-only display column — must not be documented or templated.
  { dataIndex: "iban_masked", title: "IBAN", readOnly: true },
];

function renderButton(
  props: Partial<React.ComponentProps<typeof CsvImportButton>> = {},
) {
  return render(
    <CsvImportButton
      uploadAllowed
      columns={COLUMNS}
      filename="things.csv"
      modelName="share_article"
      {...props}
    />,
  );
}

const open = async () =>
  userEvent.click(screen.getByRole("button", { name: "csv_upload.open" }));

describe("CsvImportButton", () => {
  it("renders nothing when the tenant disallows uploads", () => {
    const { container } = renderButton({ uploadAllowed: false });
    expect(container).toBeEmptyDOMElement();
  });

  it.each(["gardener", "staff", "management", "member"])(
    "renders nothing for the %s, whom the import endpoint refuses",
    (role) => {
      auth.roles = [role];
      const { container } = renderButton();
      expect(container).toBeEmptyDOMElement();
    },
  );

  it.each(["office", "admin"])("offers the import to the %s", (role) => {
    auth.roles = [role];
    renderButton();
    expect(
      screen.getByRole("button", { name: "csv_upload.open" }),
    ).toBeInTheDocument();
  });

  it("opens a modal offering template, dry run AND import", async () => {
    renderButton();
    await open();
    // The dry run is the whole point of the change.
    expect(screen.getByText("csv_upload.validate")).toBeInTheDocument();
    expect(screen.getByText("download.csv_template")).toBeInTheDocument();
    expect(screen.getByText("csv_upload.button")).toBeInTheDocument();
  });

  it("titles the modal with the model's translated entity name", async () => {
    renderButton();
    await open();
    expect(
      screen.getByText("csv_upload.import_title:csv_upload.model.share_article"),
    ).toBeInTheDocument();
  });

  it("documents only columns the template will emit", async () => {
    renderButton({ help: { name: "the name", number: "the number" } });
    await open();
    expect(screen.getByText("name")).toBeInTheDocument();
    expect(screen.getByText("number")).toBeInTheDocument();
    // readOnly columns are not importable serializer inputs — documenting one
    // would send the office chasing a column the backend rejects.
    expect(screen.queryByText("iban_masked")).not.toBeInTheDocument();
  });

  describe("upload", () => {
    const post = vi.mocked(api.post);
    const sentForm = () => post.mock.calls[0][1] as FormData;

    async function importFile() {
      post.mockResolvedValue({
        data: { model_name: "share_article", successful: 1, failed: 0, results: [], errors: [] },
      });
      await open();
      const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]');
      await userEvent.upload(
        inputs[inputs.length - 1],
        new File(["name\nTractor hire\n"], "things.csv", { type: "text/csv" }),
      );
      await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    }

    it("sends the page's fixed values with the file", async () => {
      post.mockClear();
      renderButton({ fixedValues: { is_extra: true, default_movement_unit: "PCS" } });

      await importFile();

      expect(sentForm().get("model_name")).toBe("share_article");
      expect(JSON.parse(String(sentForm().get("fixed_values")))).toEqual({
        is_extra: true,
        default_movement_unit: "PCS",
      });
    });

    it("lists a dry run's failed rows with their row number and message", async () => {
      post.mockClear();
      post.mockResolvedValue({
        data: {
          model_name: "share_article",
          total_rows: 3,
          successful: 1,
          failed: 2,
          results: [],
          errors: [
            { row: 3, error: "name: This field is required.", data: {} },
            { row: 4, error: "number: A valid integer is required.", data: {} },
          ],
        },
      });
      renderButton();
      await open();

      await userEvent.upload(
        screen.getByText("csv_upload.validate").closest("span.ant-upload")!
          .querySelector<HTMLInputElement>('input[type="file"]')!,
        new File(["name\n\n"], "things.csv", { type: "text/csv" }),
      );

      expect(
        await screen.findByText("csv_upload.dry_run_notice"),
      ).toBeInTheDocument();
      expect(sentForm().get("dry_run")).toBe("true");
      const row3 = document.querySelector('tr[data-row-key="3"]');
      const row4 = document.querySelector('tr[data-row-key="4"]');
      expect(row3).toHaveTextContent("3");
      expect(row3).toHaveTextContent("name: This field is required.");
      expect(row4).toHaveTextContent("number: A valid integer is required.");
    });

    it("sends no fixed values when the page has none", async () => {
      post.mockClear();
      renderButton();

      await importFile();

      expect(sentForm().has("fixed_values")).toBe(false);
    });
  });
});
