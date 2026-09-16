// Configuration > Users: while onboarding mode is on, a member's portal
// invitation can't be re-sent (the server refuses it), so that row's resend
// button is disabled with the reason on hover and as its accessible
// description. Staff and customer invitations stay available, and a refused
// resend shows the server's reason.

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const hookState = vi.hoisted(() => ({ onboardingMode: false }));
const api = vi.hoisted(() => ({
  users: [] as Record<string, unknown>[],
  resend: vi.fn(),
}));
const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const apiError = vi.hoisted(() => ({ getErrorMessage: vi.fn() }));

vi.mock("@hooks/index", () => ({
  useDateFormat: () => ({ formatDate: (value: string) => value }),
  useOnboardingMode: () => hookState.onboardingMode,
}));

vi.mock("@shared/api/generated/auth/auth", () => ({
  authAdminUsersPartialUpdate: vi.fn(),
  authAdminUsersResendInvitationCreate: (id: string) => api.resend(id),
  getAuthAdminUsersListQueryKey: () => ["/api/auth/admin/users/"],
  useAuthAdminUsersList: () => ({ data: api.users, isFetching: false }),
}));

vi.mock("@shared/api/generated/tenants/tenants", () => ({
  useTenantsEmailConfigList: () => ({
    data: { smtp_host: "smtp.example.org" },
  }),
}));

// Renders every column's cell for every row, one test id per row.
vi.mock("@shared/tables", () => ({
  READ_ONLY_PERMISSION: {},
  EditableTable: ({
    columns,
    initialData,
  }: {
    columns: {
      key: string;
      dataIndex: string;
      render?: (value: unknown, record: Record<string, unknown>) => unknown;
    }[];
    initialData: Record<string, unknown>[];
  }) => (
    <div>
      {initialData.map((row) => (
        <div key={String(row.id)} data-testid={`user-row-${row.id}`}>
          {columns.map((column) => (
            <div key={column.key}>
              {(column.render
                ? column.render(row[column.dataIndex], row)
                : String(row[column.dataIndex] ?? "")) as React.ReactNode}
            </div>
          ))}
        </div>
      ))}
    </div>
  ),
}));

vi.mock("@shared/ui", async () => {
  const tooltip = await vi.importActual<
    typeof import("@shared/ui/DisabledReasonTooltip")
  >("@shared/ui/DisabledReasonTooltip");
  return {
    DisabledReasonTooltip: tooltip.default,
    ExplainerText: ({ children }: { children?: React.ReactNode }) => (
      <div>{children}</div>
    ),
    PastWarningMessage: ({ children }: { children?: React.ReactNode }) => (
      <div>{children}</div>
    ),
  };
});

vi.mock("@shared/auth", () => ({ RoleTags: () => null }));
vi.mock("@shared/modals", () => ({ InviteUserModal: () => null }));
vi.mock("@features/configuration/modals", () => ({
  EditUserRolesModal: () => null,
}));
vi.mock("@shared/utils", () => ({ notify }));
vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: (error: unknown, fallback: string) =>
    apiError.getErrorMessage(error, fallback),
}));

import ConfigurationUsers from "../ConfigurationUsers";

function pendingLogin(id: string, roles: string[]) {
  return {
    id,
    key: id,
    first_name: "Pat",
    last_name: id,
    email: `${id}@example.org`,
    roles,
    account_status: "pending_invitation",
    invitation_expires_at: new Date(
      Date.now() + 7 * 24 * 60 * 60 * 1000,
    ).toISOString(),
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ConfigurationUsers />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The button's accessible name also carries its mail icon's label.
function resendButton(userId: string) {
  return within(screen.getByTestId(`user-row-${userId}`)).getByRole("button", {
    name: /users\.resend_invitation/,
  });
}

beforeEach(() => {
  hookState.onboardingMode = false;
  api.users = [
    pendingLogin("office-login", ["office"]),
    pendingLogin("customer-login", ["customer", "member"]),
    pendingLogin("member-login", ["member"]),
  ];
  api.resend.mockReset();
  notify.success.mockReset();
  notify.error.mockReset();
  apiError.getErrorMessage.mockReset();
});

describe("ConfigurationUsers resend invitation", () => {
  it("disables a member's resend with the reason while onboarding mode is on", async () => {
    hookState.onboardingMode = true;
    renderPage();

    const memberResend = resendButton("member-login");
    expect(memberResend).toBeDisabled();
    expect(memberResend).toHaveAccessibleDescription(
      "onboarding.mode.invitation_disabled",
    );

    await userEvent.hover(memberResend.parentElement!);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("onboarding.mode.invitation_disabled");
    expect(tooltip.closest(".custom-tooltip")).not.toBeNull();

    for (const userId of ["office-login", "customer-login"]) {
      const button = resendButton(userId);
      expect(button).toBeEnabled();
      expect(button).not.toHaveAttribute("aria-describedby");
    }
    expect(api.resend).not.toHaveBeenCalled();
  });

  it("re-sends a member's invitation while onboarding mode is off", async () => {
    api.resend.mockResolvedValue({});
    renderPage();

    const memberResend = resendButton("member-login");
    expect(memberResend).toBeEnabled();
    expect(memberResend).not.toHaveAttribute("aria-describedby");

    await userEvent.click(memberResend);

    expect(api.resend).toHaveBeenCalledWith("member-login");
    expect(notify.success).toHaveBeenCalledWith("users.invitation_resent");
  });

  it("shows the server's reason when a resend is refused", async () => {
    const refusal = {
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          code: "onboarding_mode.email_action_blocked",
          message: "Turn off onboarding mode first.",
        },
      },
    };
    api.resend.mockRejectedValue(refusal);
    apiError.getErrorMessage.mockReturnValue("Turn off onboarding mode first.");
    renderPage();

    await userEvent.click(resendButton("member-login"));

    expect(apiError.getErrorMessage).toHaveBeenCalledWith(
      refusal,
      "users.resend_failed",
    );
    expect(notify.error).toHaveBeenCalledWith("Turn off onboarding mode first.");
    expect(notify.success).not.toHaveBeenCalled();
  });
});
