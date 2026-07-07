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
    getPaymentsBillingProfilesListQueryKey: () => ["billing-profiles"],
  }),
);

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
  listMock.mockReset().mockReturnValue({ data: [] });
  createMutateMock.mockReset().mockResolvedValue(undefined);
  patchMutateMock.mockReset().mockResolvedValue(undefined);
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
