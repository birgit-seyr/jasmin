/**
 * Seam test for ``SepaSetupModal`` — a financial flow that upserts a
 * BillingProfile (SEPA mandate) and records the matching ConsentRecord.
 *
 * Boundary mocked: the generated billing-profile + consent API hooks/fns,
 * ``ConsentBlock`` (stubbed to a checkbox-button that reports an accepted
 * doc id), ``ModalCancelSaveFooter`` (plain primary button), ``notify`` and
 * ``getErrorMessage``. The real AntD ``Form`` runs so ``validateFields`` and
 * the IBAN rule are exercised for real.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const listMock = vi.fn((..._args: unknown[]) => ({ data: [] as unknown[] }));
const createMutateMock = vi.fn();
const patchMutateMock = vi.fn();
const replaceMutateMock = vi.fn();
vi.mock(
  "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles",
  () => ({
    usePaymentsBillingProfilesList: (...args: unknown[]) => listMock(...args),
    usePaymentsBillingProfilesCreate: () => ({
      mutateAsync: createMutateMock,
    }),
    usePaymentsBillingProfilesPartialUpdate: () => ({
      mutateAsync: patchMutateMock,
    }),
    usePaymentsBillingProfilesReplaceMandateCreate: () => ({
      mutateAsync: replaceMutateMock,
    }),
    getPaymentsBillingProfilesListQueryKey: () => ["billing-profiles"],
  }),
);

// Office fields depend on the tenant + date-format hooks. ``getSetting`` hands
// back the caller's fallback by default, which leaves the paper-signature
// requirement off; the paper-signature case swaps in its own implementation.
const getSettingMock = vi.hoisted(() =>
  vi.fn((_key: string, fallback?: unknown) => fallback),
);
vi.mock("@hooks/configuration/useTenant", () => ({
  useTenant: () => ({ getSetting: getSettingMock }),
}));
vi.mock("@hooks/configuration/useDateFormat", () => ({
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    formatDate: (value: string) => value,
  }),
}));

const consentCreateMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningConsentsCreate: (...args: unknown[]) =>
    consentCreateMock(...args),
  getCommissioningConsentsListQueryKey: () => ["consents"],
}));

// ConsentBlock → a button that reports acceptance of a fixed document id.
vi.mock("@shared/consent/ConsentBlock", () => ({
  default: ({
    onChange,
  }: {
    onChange: (checked: boolean, docId: string) => void;
  }) => (
    <button
      data-testid="accept-consent"
      onClick={() => onChange(true, "sepa-doc-1")}
    >
      accept
    </button>
  ),
  ConsentDocumentKind: { sepa: "sepa" },
}));

vi.mock("@shared/modals/shared", () => ({
  ModalCancelSaveFooter: ({
    onPrimary,
    onCancel,
  }: {
    onPrimary: () => void;
    onCancel: () => void;
  }) => (
    <div>
      <button data-testid="primary" onClick={onPrimary}>
        primary
      </button>
      <button data-testid="footer-cancel" onClick={onCancel}>
        cancel
      </button>
    </div>
  ),
}));

const notifySuccessMock = vi.fn();
const notifyErrorMock = vi.fn();
vi.mock("@shared/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/utils")>();
  return {
    ...actual,
    notify: {
      success: (...args: unknown[]) => notifySuccessMock(...args),
      error: (...args: unknown[]) => notifyErrorMock(...args),
    },
  };
});

vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: () => "translated error message",
}));

import SepaSetupModal from "../SepaSetupModal";

const MEMBER_ID = "member-77";

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SepaSetupModal open memberId={MEMBER_ID} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("IBAN"), {
    target: { value: "DE89370400440532013000" },
  });
  fireEvent.change(screen.getByLabelText("sepa.account_holder"), {
    target: { value: "Mara Beispiel" },
  });
}

beforeEach(() => {
  getSettingMock
    .mockReset()
    .mockImplementation((_key: string, fallback?: unknown) => fallback);
  listMock.mockReset().mockReturnValue({ data: [] });
  createMutateMock.mockReset().mockResolvedValue(undefined);
  patchMutateMock.mockReset().mockResolvedValue(undefined);
  replaceMutateMock.mockReset().mockResolvedValue(undefined);
  consentCreateMock.mockReset().mockResolvedValue(undefined);
  notifySuccessMock.mockReset();
  notifyErrorMock.mockReset();
});

describe("SepaSetupModal", () => {
  it("creates a BillingProfile + ConsentRecord and closes on success (no existing profile)", async () => {
    const { onClose } = renderModal();

    fillForm();
    fireEvent.click(screen.getByTestId("accept-consent"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(createMutateMock).toHaveBeenCalledTimes(1));
    expect(patchMutateMock).not.toHaveBeenCalled();
    expect(createMutateMock).toHaveBeenCalledWith({
      data: expect.objectContaining({
        member: MEMBER_ID,
        iban: "DE89370400440532013000",
        account_holder: "Mara Beispiel",
        is_active: true,
        // The mandate signature date is load-bearing for SEPA compliance —
        // pin its presence + YYYY-MM-DD shape so a regression dropping it
        // (or sending a full ISO timestamp) is caught.
        sepa_mandate_signed_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      }),
    });
    // The consent is pinned to the exact document the member accepted.
    expect(consentCreateMock).toHaveBeenCalledWith({
      document_id: "sepa-doc-1",
      member: MEMBER_ID,
    });
    expect(notifySuccessMock).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("PATCHes the existing profile instead of creating a new one", async () => {
    listMock.mockReturnValue({
      data: [
        {
          id: "bp-1",
          member: MEMBER_ID,
          iban: "DE00000000000000000000",
          account_holder: "Old Name",
        },
      ],
    });
    renderModal();

    fillForm();
    fireEvent.click(screen.getByTestId("accept-consent"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(patchMutateMock).toHaveBeenCalledTimes(1));
    expect(createMutateMock).not.toHaveBeenCalled();
    expect(patchMutateMock).toHaveBeenCalledWith({
      id: "bp-1",
      data: expect.objectContaining({
        // Re-arm SEPA on re-setup: a prior consent-revoke switches the profile
        // to BANK_TRANSFER, so the PATCH must reset payment_method + is_active
        // or the "new" mandate never activates (is_sepa_ready stays false).
        payment_method: "SEPA_DD",
        is_active: true,
        iban: "DE89370400440532013000",
        account_holder: "Mara Beispiel",
        // Re-signing a mandate re-stamps the signature date — same
        // compliance requirement as the create branch.
        sepa_mandate_signed_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      }),
    });
    expect(consentCreateMock).toHaveBeenCalledTimes(1);
  });

  it("rejects an invalid IBAN via the form rule — no API call", async () => {
    renderModal();

    // Too short / wrong shape for /^[A-Z0-9 ]{15,34}$/i.
    fireEvent.change(screen.getByLabelText("IBAN"), {
      target: { value: "nope" },
    });
    fireEvent.change(screen.getByLabelText("sepa.account_holder"), {
      target: { value: "Mara Beispiel" },
    });
    fireEvent.click(screen.getByTestId("accept-consent"));
    fireEvent.click(screen.getByTestId("primary"));

    expect(await screen.findByText("sepa.iban_invalid")).toBeInTheDocument();
    expect(createMutateMock).not.toHaveBeenCalled();
    expect(consentCreateMock).not.toHaveBeenCalled();
  });

  it("requires IBAN and account holder before any API call", async () => {
    renderModal();

    // Submit the empty form (mandate accepted to isolate the field rules).
    fireEvent.click(screen.getByTestId("accept-consent"));
    fireEvent.click(screen.getByTestId("primary"));

    expect(await screen.findByText("sepa.iban_required")).toBeInTheDocument();
    expect(
      screen.getByText("sepa.account_holder_required"),
    ).toBeInTheDocument();
    expect(createMutateMock).not.toHaveBeenCalled();
    expect(consentCreateMock).not.toHaveBeenCalled();
  });

  it("refuses to submit until the mandate is accepted", async () => {
    renderModal();

    fillForm();
    // Skip the consent click.
    fireEvent.click(screen.getByTestId("primary"));

    expect(
      await screen.findByText("sepa.must_accept_mandate"),
    ).toBeInTheDocument();
    expect(createMutateMock).not.toHaveBeenCalled();
    expect(consentCreateMock).not.toHaveBeenCalled();
  });

  it("office mode: attestation checkbox creates the mandate with a manual reference and records NO consent", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={client}>
        <SepaSetupModal open memberId={MEMBER_ID} onClose={vi.fn()} officeMode />
      </QueryClientProvider>,
    );

    fillForm();
    fireEvent.change(screen.getByLabelText("sepa.mandate_reference"), {
      target: { value: "MND-2026-001" },
    });
    // The office attestation checkbox REPLACES the member ConsentBlock.
    fireEvent.click(
      screen.getByRole("checkbox", { name: "sepa.office_mandate_confirm" }),
    );
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(createMutateMock).toHaveBeenCalledTimes(1));
    expect(createMutateMock).toHaveBeenCalledWith({
      data: expect.objectContaining({
        member: MEMBER_ID,
        iban: "DE89370400440532013000",
        // The office's manually-entered reference overrides auto-generation.
        sepa_mandate_reference: "MND-2026-001",
      }),
    });
    // A paper mandate is its own consent artifact — no digital ConsentRecord.
    expect(consentCreateMock).not.toHaveBeenCalled();
  });

  it("office mode: refuses to submit until the attestation checkbox is ticked", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={client}>
        <SepaSetupModal open memberId={MEMBER_ID} onClose={vi.fn()} officeMode />
      </QueryClientProvider>,
    );

    fillForm();
    // Skip the attestation checkbox.
    fireEvent.click(screen.getByTestId("primary"));

    expect(
      await screen.findByText("sepa.must_accept_mandate"),
    ).toBeInTheDocument();
    expect(createMutateMock).not.toHaveBeenCalled();
  });

  it("surfaces the API failure as an inline error and does not close", async () => {
    createMutateMock.mockRejectedValueOnce(new Error("boom"));
    const { onClose } = renderModal();

    fillForm();
    fireEvent.click(screen.getByTestId("accept-consent"));
    fireEvent.click(screen.getByTestId("primary"));

    expect(
      await screen.findByText("translated error message"),
    ).toBeInTheDocument();
    expect(consentCreateMock).not.toHaveBeenCalled();
    expect(notifySuccessMock).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

/**
 * A mandate the bank has already collected against (``sepa_mandate_first_use_at``
 * set) is pinned to the account the member authorised: the backend refuses an
 * ``iban`` change on it. The client can't tell whether a submitted IBAN differs
 * from the stored one (the API only returns it masked), so the account is held
 * still until the office explicitly opts into issuing a new mandate.
 */
describe("SepaSetupModal — mandate already in use", () => {
  const PROFILE_IN_USE = {
    id: "bp-1",
    member: MEMBER_ID,
    iban_masked: "DE89 **** **** **** 3000",
    account_holder_masked: "M*** B*******",
    sepa_mandate_first_use_at: "2026-02-03",
    // The reference the bank matches collections against, and a paper
    // signature already filed against this mandate.
    sepa_mandate_reference: "MND-2025-014",
    sepa_mandate_paper_received_at: "2026-01-20",
  };

  function renderOfficeModal() {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <SepaSetupModal open memberId={MEMBER_ID} onClose={onClose} officeMode />
      </QueryClientProvider>,
    );
    return { onClose };
  }

  function attestAndSubmit() {
    fireEvent.click(
      screen.getByRole("checkbox", { name: "sepa.office_mandate_confirm" }),
    );
    fireEvent.click(screen.getByTestId("primary"));
  }

  it("leaves the iban out of the PATCH and never replaces while the opt-in is unticked", async () => {
    listMock.mockReturnValue({ data: [PROFILE_IN_USE] });
    renderOfficeModal();

    // The account is held still, but everything else still saves.
    expect(screen.getByLabelText("IBAN")).toBeDisabled();
    // The reference is locked with the account it belongs to: the backend
    // refuses any value other than the stored one while the mandate is in use.
    expect(screen.getByLabelText("sepa.mandate_reference")).toBeDisabled();
    // Office gets the opt-in, not the member-facing dead-end notice.
    expect(
      screen.queryByText("sepa.mandate_in_use_member_notice"),
    ).toBeNull();
    fireEvent.change(screen.getByLabelText("sepa.account_holder"), {
      target: { value: "Mara Beispiel" },
    });
    attestAndSubmit();

    await waitFor(() => expect(patchMutateMock).toHaveBeenCalledTimes(1));
    expect(replaceMutateMock).not.toHaveBeenCalled();
    const patched = patchMutateMock.mock.calls[0][0] as {
      id: string;
      data: Record<string, unknown>;
    };
    expect(patched.id).toBe("bp-1");
    // Sending it would trip the backend lock and fail a save that is only
    // fixing the account holder.
    expect(patched.data).not.toHaveProperty("iban");
    expect(patched.data).toMatchObject({
      account_holder: "Mara Beispiel",
      payment_method: "SEPA_DD",
      // Seeded from the profile and resent verbatim — the backend compares it
      // against the stored value and refuses anything that differs.
      sepa_mandate_reference: "MND-2025-014",
    });
  });

  it("routes the new account to replace_mandate once the office ticks the opt-in", async () => {
    listMock.mockReturnValue({ data: [PROFILE_IN_USE] });
    renderOfficeModal();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "sepa.replace_mandate_confirm" }),
    );
    // Opting in unlocks the account field.
    expect(screen.getByLabelText("IBAN")).toBeEnabled();
    fireEvent.change(screen.getByLabelText("IBAN"), {
      target: { value: "DE89370400440532013000" },
    });
    fireEvent.change(screen.getByLabelText("sepa.account_holder"), {
      target: { value: "Mara Beispiel" },
    });
    attestAndSubmit();

    await waitFor(() => expect(replaceMutateMock).toHaveBeenCalledTimes(1));
    expect(patchMutateMock).not.toHaveBeenCalled();
    expect(replaceMutateMock).toHaveBeenCalledWith({
      id: "bp-1",
      data: {
        iban: "DE89370400440532013000",
        account_holder: "Mara Beispiel",
        sepa_mandate_signed_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      },
    });
    // The reference the bank matches collections against is minted server-side.
    const replaced = replaceMutateMock.mock.calls[0][0] as {
      data: Record<string, unknown>;
    };
    expect(replaced.data).not.toHaveProperty("sepa_mandate_reference");
  });

  it("keeps the plain PATCH path for a mandate that has never been used", async () => {
    listMock.mockReturnValue({
      data: [{ id: "bp-2", member: MEMBER_ID, sepa_mandate_first_use_at: null }],
    });
    renderOfficeModal();

    expect(
      screen.queryByRole("checkbox", { name: "sepa.replace_mandate_confirm" }),
    ).toBeNull();
    expect(screen.getByLabelText("IBAN")).toBeEnabled();
    fillForm();
    attestAndSubmit();

    await waitFor(() => expect(patchMutateMock).toHaveBeenCalledTimes(1));
    expect(replaceMutateMock).not.toHaveBeenCalled();
    expect(patchMutateMock).toHaveBeenCalledWith({
      id: "bp-2",
      data: expect.objectContaining({ iban: "DE89370400440532013000" }),
    });
  });

  it("member self-service is unaffected — no opt-in offered, iban still PATCHed", async () => {
    listMock.mockReturnValue({ data: [PROFILE_IN_USE] });
    renderModal();

    // Replacement is office-only; the member flow keeps today's behaviour.
    expect(
      screen.queryByRole("checkbox", { name: "sepa.replace_mandate_confirm" }),
    ).toBeNull();
    expect(screen.getByLabelText("IBAN")).toBeEnabled();
    fillForm();
    fireEvent.click(screen.getByTestId("accept-consent"));
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(patchMutateMock).toHaveBeenCalledTimes(1));
    expect(replaceMutateMock).not.toHaveBeenCalled();
    expect(patchMutateMock).toHaveBeenCalledWith({
      id: "bp-1",
      data: expect.objectContaining({ iban: "DE89370400440532013000" }),
    });
  });

  it("tells the member to contact the office instead of offering a replacement", () => {
    listMock.mockReturnValue({ data: [PROFILE_IN_USE] });
    renderModal();

    // Issuing a new mandate is office-only, so the member flow names the way
    // out rather than leaving the backend lock as the only feedback.
    expect(
      screen.getByText("sepa.mandate_in_use_member_notice"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: "sepa.replace_mandate_confirm" }),
    ).toBeNull();
  });

  it("paper-signature tenant: replacing retires the filed signature and the reference stays locked", () => {
    getSettingMock.mockImplementation((key: string, fallback?: unknown) =>
      key === "requires_paper_signature_for_sepa_mandate" ? true : fallback,
    );
    listMock.mockReturnValue({ data: [PROFILE_IN_USE] });
    renderOfficeModal();

    const paperCheckbox = () =>
      screen.getByRole("checkbox", { name: "sepa.paper_signature_received" });
    // Seeded from the signature filed against the current mandate.
    expect(paperCheckbox()).toBeChecked();
    expect(paperCheckbox()).toBeEnabled();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "sepa.replace_mandate_confirm" }),
    );

    // The replacement clears the paper stamp server-side, so the new mandate
    // starts with its signature outstanding whatever the box said.
    expect(paperCheckbox()).not.toBeChecked();
    expect(paperCheckbox()).toBeDisabled();
    // The reference is minted server-side for the new mandate and pinned to the
    // old one until then — never editable from here on a mandate in use.
    expect(screen.getByLabelText("sepa.mandate_reference")).toBeDisabled();
  });
});
