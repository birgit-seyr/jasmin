/**
 * Seam test for ``CoopShareTransferModal``.
 *
 * Boundary mocked: the generated transfer mutation hook, ``MemberSelector``
 * (a plain select that applies ``filterMember``), ``ModalCancelSaveFooter``
 * (plain buttons), ``notify``, the api error helpers, ``useDateFormat``,
 * ``useMembers`` and ``useOnboardingMode``. The real AntD ``Form`` runs, so
 * validation, the payload (including both transfer notes), the cancel /
 * below-minimum hints and the onboarding-mode note are exercised for real. The ``t`` mock appends its interpolation values so the
 * notes' member labels can be asserted.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dayjs from "dayjs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: unknown) =>
      typeof options === "string"
        ? options
        : options && typeof options === "object"
          ? `${key} ${JSON.stringify(options)}`
          : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const mutateMock = vi.fn();
let nextError: unknown = null;
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningCoopSharesTransferCreate: (opts: {
    mutation?: {
      onSuccess?: (result: unknown) => void;
      onError?: (err: unknown) => void;
    };
  }) => ({
    mutate: (vars: { data: { amount_of_coop_shares: number } }) => {
      mutateMock(vars);
      if (nextError) {
        opts?.mutation?.onError?.(nextError);
        return;
      }
      opts?.mutation?.onSuccess?.({
        id: "transfer-1",
        amount_of_coop_shares: vars.data.amount_of_coop_shares,
        from_member_cancelled: false,
      });
    },
    isPending: false,
  }),
  getCommissioningCoopSharesListQueryKey: () => ["coop_shares"],
  getCommissioningMembersListQueryKey: () => ["members"],
}));

const SELECTOR_MEMBERS = [
  { value: "member-giver", admin_confirmed: true },
  { value: "member-receiver", admin_confirmed: true },
  { value: "member-cancelled", admin_confirmed: true, cancelled_at: "2026-01-01T00:00:00Z" },
  { value: "member-pending", admin_confirmed: false },
  { value: "member-rejected", admin_confirmed: false, admin_rejected_at: "2026-01-01T00:00:00Z" },
];

vi.mock("@shared/selectors/MemberSelector", () => ({
  default: ({
    selectedMember,
    setSelectedMember,
    filterMember,
  }: {
    selectedMember: string | null;
    setSelectedMember: (value: string | null) => void;
    filterMember?: (member: (typeof SELECTOR_MEMBERS)[number]) => boolean;
  }) => (
    <select
      data-testid="receiver"
      value={selectedMember ?? ""}
      onChange={(event) => setSelectedMember(event.target.value || null)}
    >
      <option value="" />
      {SELECTOR_MEMBERS.filter((member) => !filterMember || filterMember(member)).map(
        (member) => (
          <option key={member.value} value={member.value}>
            {member.value}
          </option>
        ),
      )}
    </select>
  ),
}));

vi.mock("@shared/modals/shared", () => ({
  ModalCancelSaveFooter: ({
    onPrimary,
    onCancel,
    primaryDisabled,
  }: {
    onPrimary: () => void;
    onCancel: () => void;
    primaryDisabled?: boolean;
  }) => (
    <div>
      <button data-testid="primary" onClick={onPrimary} disabled={primaryDisabled}>
        primary
      </button>
      <button data-testid="footer-cancel" onClick={onCancel}>
        cancel
      </button>
    </div>
  ),
}));

const notifyErrorMock = vi.fn();
vi.mock("@shared/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/utils")>();
  return {
    ...actual,
    notify: {
      success: vi.fn(),
      error: (...args: unknown[]) => notifyErrorMock(...args),
    },
  };
});

vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: () => "translated error message",
  getErrorCode: (err: unknown) => (err as { code?: string })?.code,
}));

const onboardingState = vi.hoisted(() => ({ onboardingMode: false }));

vi.mock("@hooks/index", () => ({
  useOnboardingMode: () => onboardingState.onboardingMode,
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    formatDate: (value: unknown) => dayjs(value as string).format("DD.MM.YYYY"),
    formatDateForAPI: (value: unknown) =>
      dayjs(value as string).format("YYYY-MM-DD"),
  }),
  useMembers: () => ({
    members: [
      {
        value: "member-giver",
        label: "7 - Gina Giver",
        member_number: 7,
        first_name: "Gina",
        last_name: "Giver",
      },
      {
        value: "member-receiver",
        label: "9 - Rico Receiver",
        member_number: 9,
        first_name: "Rico",
        last_name: "Receiver",
      },
    ],
  }),
}));

import CoopShareTransferModal from "../CoopShareTransferModal";

function renderModal({
  minShares = 3,
  confirmedTotal = 5,
}: { minShares?: number | null; confirmedTotal?: number } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onClose = vi.fn();
  const onTransferred = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <CoopShareTransferModal
        open
        onClose={onClose}
        memberId="member-giver"
        memberName="Gina Giver"
        availableShares={5}
        confirmedTotal={confirmedTotal}
        minShares={minShares}
        onTransferred={onTransferred}
      />
    </QueryClientProvider>,
  );
  return { onClose, onTransferred };
}

function enterAmount(value: string) {
  fireEvent.change(screen.getByLabelText("members.transfer_amount"), {
    target: { value },
  });
}

function chooseReceiver() {
  fireEvent.change(screen.getByTestId("receiver"), {
    target: { value: "member-receiver" },
  });
}

beforeEach(() => {
  mutateMock.mockReset();
  notifyErrorMock.mockReset();
  nextError = null;
  onboardingState.onboardingMode = false;
});

describe("CoopShareTransferModal", () => {
  it("offers only admitted, uncancelled members other than the giving one", () => {
    renderModal();

    const options = Array.from(
      screen.getByTestId("receiver").querySelectorAll("option"),
    ).map((option) => option.getAttribute("value"));
    expect(options).toEqual(["", "member-receiver"]);
  });

  it("sends the transfer with a note naming the other member on each side", async () => {
    const { onClose, onTransferred } = renderModal();

    chooseReceiver();
    enterAmount("2");
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(mutateMock).toHaveBeenCalledTimes(1));
    const today = dayjs();
    const date = today.format("DD.MM.YYYY");
    expect(mutateMock.mock.calls[0][0]).toEqual({
      data: {
        from_member: "member-giver",
        to_member: "member-receiver",
        amount_of_coop_shares: 2,
        transfer_date: today.format("YYYY-MM-DD"),
        confirm_member_cancellation: false,
        note: null,
        from_member_note: `members.transfer_note_given ${JSON.stringify({ count: 2, member: "#9 Rico Receiver", date })}`,
        to_member_note: `members.transfer_note_received ${JSON.stringify({ count: 2, member: "#7 Gina Giver", date })}`,
      },
    });
    expect(onTransferred).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("adds the free note to both transfer notes", async () => {
    renderModal();

    chooseReceiver();
    enterAmount("1");
    fireEvent.change(screen.getByLabelText("members.transfer_note"), {
      target: { value: "  sold to a neighbour " },
    });
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() => expect(mutateMock).toHaveBeenCalledTimes(1));
    const { data } = mutateMock.mock.calls[0][0];
    expect(data.note).toBe("sold to a neighbour");
    expect(data.from_member_note).toMatch(/ – sold to a neighbour$/);
    expect(data.to_member_note).toMatch(/ – sold to a neighbour$/);
  });

  it("does not submit without a receiving member", async () => {
    renderModal();

    enterAmount("2");
    fireEvent.click(screen.getByTestId("primary"));

    expect(
      await screen.findByText("members.transfer_field_required"),
    ).toBeInTheDocument();
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("refuses an amount above the transferable shares instead of lowering it", async () => {
    renderModal();

    chooseReceiver();
    enterAmount("6");
    fireEvent.click(screen.getByTestId("primary"));

    expect(
      await screen.findByText(/members\.transfer_amount_above_available/),
    ).toBeInTheDocument();
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("requires confirming the cancellation when every share is given", async () => {
    renderModal();

    chooseReceiver();
    enterAmount("5");
    expect(
      await screen.findByText("members.transfer_cancels_member"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("primary"));
    expect(
      await screen.findByText("members.transfer_confirm_cancellation_required"),
    ).toBeInTheDocument();
    expect(mutateMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("primary"));
    await waitFor(() => expect(mutateMock).toHaveBeenCalledTimes(1));
    expect(mutateMock.mock.calls[0][0].data.confirm_member_cancellation).toBe(true);
  });

  it("explains the refusal for a member with active subscriptions", async () => {
    nextError = { code: "member.has_active_subscriptions" };
    renderModal();

    chooseReceiver();
    enterAmount("2");
    fireEvent.click(screen.getByTestId("primary"));

    await waitFor(() =>
      expect(notifyErrorMock).toHaveBeenCalledWith(
        "members.transfer_active_subscriptions_error",
      ),
    );
  });

  it("blocks leaving the member between zero and the minimum", async () => {
    renderModal({ minShares: 3 });

    enterAmount("3");

    expect(
      await screen.findByText(/members\.transfer_below_minimum/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("primary")).toBeDisabled();
  });

  it("counts every confirmed share, paid or not, towards what stays", async () => {
    renderModal({ confirmedTotal: 7, minShares: 3 });

    enterAmount("5");

    expect(
      await screen.findByText(/members\.transfer_below_minimum/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("members.transfer_cancels_member"),
    ).not.toBeInTheDocument();
  });

  it("does not block when no minimum applies to the member", async () => {
    renderModal({ minShares: null });

    enterAmount("3");

    await waitFor(() =>
      expect(screen.getByTestId("primary")).not.toBeDisabled(),
    );
    expect(
      screen.queryByText(/members\.transfer_below_minimum/),
    ).not.toBeInTheDocument();
  });

  it("shows no onboarding note while onboarding mode is off", () => {
    renderModal();

    expect(
      screen.queryByText("onboarding.mode.no_email_hint"),
    ).not.toBeInTheDocument();
  });

  it("notes that no email is sent while onboarding mode is on", () => {
    onboardingState.onboardingMode = true;
    renderModal();

    expect(
      screen.getByText("onboarding.mode.no_email_hint"),
    ).toBeInTheDocument();
  });
});
