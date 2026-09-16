// UserInfoModal offers the invitation actions for the account status, and a
// caller-supplied reason disables them with a hover tooltip and an accessible
// description.

import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/index", () => ({
  useDateFormat: () => ({
    formatDateWithFallback: (value: unknown) => String(value ?? "-"),
  }),
}));

import UserInfoModal from "../UserInfoModal";

const MEMBER_WITHOUT_USER = {
  first_name: "Ada",
  last_name: "Lovelace",
  email: "ada@example.test",
  linked_user_info: null,
};

const MEMBER_WITH_OPEN_INVITATION = {
  ...MEMBER_WITHOUT_USER,
  linked_user_info: {
    account_status: "pending_invitation" as const,
    is_invitation_expired: false,
    invitation_expires_at: "2026-10-01T00:00:00Z",
  },
};

const MEMBER_WITH_EXPIRED_INVITATION = {
  ...MEMBER_WITHOUT_USER,
  linked_user_info: {
    account_status: "pending_invitation" as const,
    is_invitation_expired: true,
    invitation_expires_at: "2026-09-01T00:00:00Z",
  },
};

const REASON = "onboarding.mode.invitation_disabled";

describe("UserInfoModal invitation actions", () => {
  it("sends an invitation for a member without a user", async () => {
    const onSendInvitation = vi.fn();
    render(
      <UserInfoModal
        isOpen
        onClose={vi.fn()}
        record={MEMBER_WITHOUT_USER}
        onSendInvitation={onSendInvitation}
      />,
    );

    const button = screen.getByRole("button", { name: "users.send_invitation" });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-describedby");
    await userEvent.click(button);
    expect(onSendInvitation).toHaveBeenCalledWith(MEMBER_WITHOUT_USER);
  });

  it("disables sending with the reason as description and tooltip", async () => {
    const onSendInvitation = vi.fn();
    render(
      <UserInfoModal
        isOpen
        onClose={vi.fn()}
        record={MEMBER_WITHOUT_USER}
        onSendInvitation={onSendInvitation}
        invitationDisabledReason={REASON}
      />,
    );

    const button = screen.getByRole("button", { name: "users.send_invitation" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(REASON);

    await userEvent.hover(button.parentElement!);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(REASON);
    expect(tooltip.closest(".custom-tooltip")).not.toBeNull();
    expect(onSendInvitation).not.toHaveBeenCalled();
  });

  it("disables resending an open invitation with the reason", () => {
    render(
      <UserInfoModal
        isOpen
        onClose={vi.fn()}
        record={MEMBER_WITH_OPEN_INVITATION}
        onResendInvitation={vi.fn()}
        invitationDisabledReason={REASON}
      />,
    );

    const button = screen.getByRole("button", {
      name: "users.resend_invitation",
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(REASON);
  });

  it("disables a new invitation for an expired one with the reason", () => {
    render(
      <UserInfoModal
        isOpen
        onClose={vi.fn()}
        record={MEMBER_WITH_EXPIRED_INVITATION}
        onSendInvitation={vi.fn()}
        onResendInvitation={vi.fn()}
        invitationDisabledReason={REASON}
      />,
    );

    const button = screen.getByRole("button", {
      name: "users.send_new_invitation",
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(REASON);
  });

  it("keeps resending enabled without a reason", () => {
    render(
      <UserInfoModal
        isOpen
        onClose={vi.fn()}
        record={MEMBER_WITH_OPEN_INVITATION}
        onResendInvitation={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "users.resend_invitation" }),
    ).toBeEnabled();
  });
});
