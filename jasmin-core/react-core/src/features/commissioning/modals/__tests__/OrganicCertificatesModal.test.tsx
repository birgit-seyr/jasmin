/**
 * OrganicCertificatesModal: a seller's organic certificates over time, edited
 * inline. Rendered through the real PriceEditorModal, EditableTable and
 * time-bound column hooks; the generated organic-certificate client is the
 * mocking boundary, with the list hook a real TanStack query around a spy that
 * answers from an in-memory server.
 *
 * The clock is frozen on Monday 5 October 2026, which decides which
 * certificate is past, active or upcoming and which month the date pickers
 * open on.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrganicCertificate } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const listKey = (params?: unknown) => [
    "/api/commissioning/organic_certificates/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningOrganicCertificatesListQueryKey: listKey,
    useCommissioningOrganicCertificatesList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: listKey(params),
        queryFn: () => api.list(params),
        enabled: options?.query?.enabled,
      }),
    commissioningOrganicCertificatesCreate: (certificate: unknown) =>
      api.create(certificate),
    commissioningOrganicCertificatesPartialUpdate: (id: string, certificate: unknown) =>
      api.update(id, certificate),
    commissioningOrganicCertificatesDestroy: (id: string) => api.destroy(id),
  };
});

import OrganicCertificatesModal from "../OrganicCertificatesModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);
const SELLER = "res-hof";

// Last year's certificate, closed.
const PAST_CERTIFICATE: OrganicCertificate = {
  id: "cert-2025",
  reseller: SELLER,
  valid_from: "2025-01-06",
  valid_until: "2025-12-28",
  certificate_number: "AT-BIO-301-0001",
  link: "https://certs.example/2025.pdf",
};
// Today's certificate, open-ended.
const ACTIVE_CERTIFICATE: OrganicCertificate = {
  id: "cert-2026",
  reseller: SELLER,
  valid_from: "2025-12-29",
  valid_until: null,
  certificate_number: "AT-BIO-301-0002",
  link: null,
};

let serverCertificates: OrganicCertificate[] = [];

const dayBefore = (isoDate: string) => {
  const date = new Date(`${isoDate}T12:00:00`);
  date.setDate(date.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderModal({
  reseller = SELLER as string | null,
  visible = true,
}: { reseller?: string | null; visible?: boolean } = {}) {
  const onClose = vi.fn();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(
        <OrganicCertificatesModal
          visible={visible}
          onClose={onClose}
          reseller={reseller}
          reseller_name="Hof Sonnenschein"
        />,
      )}
    </QueryClientProvider>,
  );
  return { onClose, profiler };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

function bodyRows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"),
  );
}

/** The date picker dropdown open right now; a closed one stays in the DOM. */
function openCalendar(): HTMLElement {
  const open = Array.from(
    document.querySelectorAll<HTMLElement>(".ant-picker-dropdown"),
  ).filter((dropdown) => !dropdown.classList.contains("ant-picker-dropdown-hidden"));
  const calendar = open[open.length - 1];
  if (!calendar) throw new Error("No date picker is open");
  return calendar;
}

function calendarCell(isoDate: string): HTMLElement {
  const cell = openCalendar().querySelector<HTMLElement>(`td[title="${isoDate}"]`);
  if (!cell) throw new Error(`No calendar cell for ${isoDate}`);
  return cell;
}

async function pickDate(label: string, isoDate: string) {
  await userEvent.click(within(editingRow()).getByLabelText(label));
  await userEvent.click(calendarCell(isoDate));
}

const VALID_FROM = "configuration.valid_from";
const VALID_UNTIL = "configuration.valid_until";
const NUMBER = "resellers.organic_certificate_number";
const LINK = "resellers.organic_certificate_link";

async function startNewCertificate() {
  await userEvent.click(
    screen.getByRole("button", { name: /table\.add_record/ }),
  );
}

async function save() {
  await userEvent.click(screen.getByRole("button", { name: "table.save" }));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  serverCertificates = [ACTIVE_CERTIFICATE, PAST_CERTIFICATE];
  api.list.mockReset().mockImplementation(async () => [...serverCertificates]);
  api.create.mockReset().mockImplementation(async (certificate: OrganicCertificate) => {
    const saved = { ...certificate, id: "cert-new" };
    // The backend closes the open predecessor the day before the new certificate.
    serverCertificates = [
      saved,
      ...serverCertificates.map((row) =>
        row.valid_until === null && row.valid_from < certificate.valid_from
          ? { ...row, valid_until: dayBefore(certificate.valid_from) }
          : row,
      ),
    ];
    return saved;
  });
  api.update
    .mockReset()
    .mockImplementation(async (id: string, certificate: OrganicCertificate) => {
      const saved = { ...certificate, id };
      serverCertificates = serverCertificates.map((row) => (row.id === id ? saved : row));
      return saved;
    });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    serverCertificates = serverCertificates.filter((row) => row.id !== id);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Certificate history ─────────────────────────────────────────────────────

describe("OrganicCertificatesModal certificate history", () => {
  it("loads the certificates of the seller it was opened for", async () => {
    renderModal();

    expect(await screen.findByText("AT-BIO-301-0002")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledTimes(1);
    expect(api.list).toHaveBeenCalledWith({ reseller: SELLER });
    expect(
      within(screen.getByRole("dialog")).getByText(
        "resellers.organic_certificates_for Hof Sonnenschein",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("commissioning.prices_are_netto")).not.toBeInTheDocument();
  });

  it("names the validity, number and link columns", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    expect(screen.getByRole("columnheader", { name: /configuration\.valid_from/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /configuration\.valid_until/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: NUMBER })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: LINK })).toBeInTheDocument();
  });

  it("shows each certificate's validity in the tenant's date format, in the server's order", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    const rows = bodyRows();
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("AT-BIO-301-0002");
    expect(within(rows[0]).getByText("29.12.2025")).toBeInTheDocument();
    expect(within(rows[1]).getByText("06.01.2025")).toBeInTheDocument();
    expect(within(rows[1]).getByText("28.12.2025")).toBeInTheDocument();
  });

  it("links a certificate's document in a new tab, and shows nothing for one without", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    const link = within(rowOf("AT-BIO-301-0001")).getByRole("link", {
      name: "https://certs.example/2025.pdf",
    });
    expect(link).toHaveAttribute("href", "https://certs.example/2025.pdf");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
    expect(within(rowOf("AT-BIO-301-0002")).queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows an empty table for a seller without certificates", async () => {
    serverCertificates = [];
    renderModal();

    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1));
    await screen.findByRole("button", { name: /table\.add_record/ });
    expect(bodyRows()).toHaveLength(0);
  });

  it("asks nothing while it is closed or has no seller", async () => {
    renderModal({ visible: false });
    renderModal({ reseller: null });
    await flushMicrotasks();

    expect(api.list).not.toHaveBeenCalled();
  });

  it("closes from its footer", async () => {
    const { onClose } = renderModal();
    await screen.findByText("AT-BIO-301-0002");

    const buttons = within(screen.getByRole("dialog")).getAllByRole("button", {
      name: /common\.close/,
    });
    await userEvent.click(buttons[buttons.length - 1]);

    expect(onClose).toHaveBeenCalled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderModal();
    await screen.findByText("AT-BIO-301-0002");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── New certificate ─────────────────────────────────────────────────────────

describe("OrganicCertificatesModal new certificate", () => {
  it("only offers Mondays as the start of a certificate", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");
    await startNewCertificate();

    await userEvent.click(within(editingRow()).getByLabelText(VALID_FROM));

    expect(calendarCell("2026-10-12")).not.toHaveClass("ant-picker-cell-disabled");
    expect(calendarCell("2026-10-13")).toHaveClass("ant-picker-cell-disabled");
  });

  it("adds a certificate for the seller and shows the previous one closed the day before", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    await startNewCertificate();
    await pickDate(VALID_FROM, "2026-10-12");
    await userEvent.type(within(editingRow()).getByLabelText(NUMBER), "AT-BIO-301-0003");
    await userEvent.type(
      within(editingRow()).getByLabelText(LINK),
      "https://certs.example/2027.pdf",
    );
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        reseller: SELLER,
        valid_from: "2026-10-12",
        certificate_number: "AT-BIO-301-0003",
        link: "https://certs.example/2027.pdf",
      }),
    );
    const newRow = await screen.findByText("AT-BIO-301-0003").then((cell) => cell.closest("tr")!);
    expect(within(newRow).getByText("12.10.2026")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(rowOf("AT-BIO-301-0002")).getByText("11.10.2026")).toBeInTheDocument(),
    );
    expect(api.list).toHaveBeenCalledTimes(2);
  });

  it("saves a certificate with only its validity", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    await startNewCertificate();
    await pickDate(VALID_FROM, "2026-10-12");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const sent = api.create.mock.calls[0][0] as Record<string, unknown>;
    expect(sent).toEqual(expect.objectContaining({ reseller: SELLER, valid_from: "2026-10-12" }));
    expect(sent.certificate_number ?? null).toBeNull();
    expect(sent.link ?? null).toBeNull();
  });

  it("refuses to save a certificate without a start date", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    await startNewCertificate();
    await userEvent.type(within(editingRow()).getByLabelText(NUMBER), "AT-BIO-301-0003");
    await save();

    expect(await within(editingRow()).findByText("table.required")).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("refuses a new certificate that starts before the seller's open one", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    serverCertificates = [{ ...ACTIVE_CERTIFICATE, valid_from: "2026-10-19" }, PAST_CERTIFICATE];
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    await startNewCertificate();
    await pickDate(VALID_FROM, "2026-10-12");
    await save();

    await waitFor(() =>
      expect(within(editingRow()).getByLabelText(VALID_FROM)).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(api.create).not.toHaveBeenCalled();
  });

  it("shows the backend's reason when it refuses a certificate", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.create.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { message: "Enter a valid URL.", field: "link" } },
    });
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    await startNewCertificate();
    await pickDate(VALID_FROM, "2026-10-12");
    await userEvent.type(within(editingRow()).getByLabelText(LINK), "not a url");
    await save();

    expect(await screen.findByText(/Enter a valid URL\./)).toBeInTheDocument();
    expect(within(editingRow()).getByLabelText(LINK)).toHaveValue("not a url");
  });
});

// ── Existing certificates ───────────────────────────────────────────────────

describe("OrganicCertificatesModal existing certificates", () => {
  it("changes a certificate's number and keeps its validity and seller", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0001");

    await userEvent.click(
      within(rowOf("AT-BIO-301-0001")).getByRole("button", { name: "table.edit" }),
    );
    const number = within(editingRow()).getByLabelText(NUMBER);
    expect(number).toHaveValue("AT-BIO-301-0001");
    await userEvent.clear(number);
    await userEvent.type(number, "AT-BIO-301-0009");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "cert-2025",
      expect.objectContaining({
        reseller: SELLER,
        valid_from: "2025-01-06",
        valid_until: "2025-12-28",
        certificate_number: "AT-BIO-301-0009",
        link: "https://certs.example/2025.pdf",
      }),
    );
    expect(await screen.findByText("AT-BIO-301-0009")).toBeInTheDocument();
  });

  it("ends the open certificate on a Sunday", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0002");

    await userEvent.click(
      within(rowOf("AT-BIO-301-0002")).getByRole("button", { name: "table.edit" }),
    );
    await pickDate(VALID_UNTIL, "2026-10-25");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "cert-2026",
      expect.objectContaining({ reseller: SELLER, valid_until: "2026-10-25" }),
    );
    await waitFor(() =>
      expect(within(rowOf("AT-BIO-301-0002")).getByText("25.10.2026")).toBeInTheDocument(),
    );
  });

  it("deletes a certificate after confirmation", async () => {
    renderModal();
    await screen.findByText("AT-BIO-301-0001");

    await userEvent.click(
      within(rowOf("AT-BIO-301-0001")).getByRole("button", { name: "table.delete" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith("cert-2025"));
    await waitFor(() => expect(screen.queryByText("AT-BIO-301-0001")).not.toBeInTheDocument());
    expect(screen.getByText("AT-BIO-301-0002")).toBeInTheDocument();
  });

  it.each([{ roles: ["staff"] }, { roles: ["gardener"] }])(
    "shows the certificates read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      renderModal();
      await screen.findByText("AT-BIO-301-0002");

      expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.edit" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    },
  );
});
