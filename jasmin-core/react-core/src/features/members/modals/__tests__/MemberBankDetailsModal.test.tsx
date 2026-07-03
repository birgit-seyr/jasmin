/**
 * Seam test for ``MemberBankDetailsModal`` — the office edit surface for a
 * member's stored bank details (Member.iban / account_owner).
 *
 * Boundary mocked: the generated members partial-update hook,
 * ``ModalCancelSaveFooter`` (plain primary/cancel buttons), ``notify`` and
 * ``getErrorMessage``. The real AntD ``Form`` + the reused ``StoredOrEditField``
 * + the real IBAN rule run, so the "only send what was edited" + validation
 * behaviour is exercised for real.
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

const mutateMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningMembersPartialUpdate: (opts: {
    mutation?: { onSuccess?: () => void };
  }) => ({
    mutate: (vars: unknown) => {
      mutateMock(vars);
      opts?.mutation?.onSuccess?.();
    },
    isPending: false,
  }),
  getCommissioningMembersListQueryKey: () => ["members"],
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
vi.mock("@shared/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/utils")>();
  return {
    ...actual,
    notify: {
      success: (...args: unknown[]) => notifySuccessMock(...args),
      error: vi.fn(),
    },
  };
});

vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: () => "translated error message",
}));

import MemberBankDetailsModal from "../MemberBankDetailsModal";

const MEMBER_ID = "member-42";

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onClose = vi.fn();
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MemberBankDetailsModal
        open
        memberId={MEMBER_ID}
        ibanMasked="DE •••• 3000"
        accountOwnerMasked="A•• L•••••••"
        onClose={onClose}
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { onClose, onSaved };
}

beforeEach(() => {
  mutateMock.mockReset();
  notifySuccessMock.mockReset();
});

describe("MemberBankDetailsModal", () => {
  it("shows the masked current values and does not PATCH when nothing is edited", async () => {
    const { onClose } = renderModal();

    // Masked values are visible; the decrypted value is never present.
    expect(screen.getByText("DE •••• 3000")).toBeInTheDocument();
    expect(screen.getByText("A•• L•••••••")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("sends ONLY the edited iban (account_owner left untouched)", async () => {
    renderModal();

    // Two "change" buttons (account_owner first, iban second). Open the iban one.
    const changeButtons = screen.getAllByText("profile.change_value");
    fireEvent.click(changeButtons[1]);

    fireEvent.change(screen.getByLabelText("members.iban"), {
      target: { value: "DE89370400440532013000" },
    });
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(mutateMock).toHaveBeenCalledTimes(1));
    expect(mutateMock).toHaveBeenCalledWith({
      id: MEMBER_ID,
      data: { iban: "DE89370400440532013000" },
    });
    expect(notifySuccessMock).toHaveBeenCalledTimes(1);
  });

  it("blocks save on an invalid IBAN — no PATCH", async () => {
    renderModal();

    const changeButtons = screen.getAllByText("profile.change_value");
    fireEvent.click(changeButtons[1]);

    fireEvent.change(screen.getByLabelText("members.iban"), {
      target: { value: "not-an-iban" },
    });
    fireEvent.click(screen.getByTestId("primary"));

    // The real IBAN rule rejects → validateFields throws → no mutate.
    await waitFor(() =>
      expect(screen.getByLabelText("members.iban")).toBeInTheDocument(),
    );
    expect(mutateMock).not.toHaveBeenCalled();
  });
});
