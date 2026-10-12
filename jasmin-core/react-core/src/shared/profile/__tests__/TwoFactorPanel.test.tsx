/**
 * TwoFactorPanel: enrolling, disabling and regenerating recovery codes, with
 * the toasts each outcome shows. The generated two-factor client is the
 * mocking boundary; the QR renderer is stubbed so enrolment needs no canvas.
 */
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

const { api, notify, status } = vi.hoisted(() => ({
  api: {
    enrollStart: vi.fn(),
    enrollConfirm: vi.fn(),
    disable: vi.fn(),
    regenerate: vi.fn(),
  },
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  status: { current: { enrolled: false, recovery_codes_remaining: 0 } },
}));

vi.mock("@shared/api/generated/auth-—-two-factor/auth-—-two-factor", () => ({
  authTwoFactorEnrollStartCreate: () => api.enrollStart(),
  authTwoFactorEnrollConfirmCreate: (body: unknown) => api.enrollConfirm(body),
  authTwoFactorDisableCreate: (body: unknown) => api.disable(body),
  authTwoFactorRecoveryCodesRegenerateCreate: (body: unknown) => api.regenerate(body),
  useAuthTwoFactorStatusRetrieve: () => ({
    data: status.current,
    isFetching: false,
    refetch: vi.fn().mockResolvedValue({}),
  }),
}));
vi.mock("@shared/utils", () => ({ notify }));
vi.mock("qrcode", () => ({
  default: { toDataURL: () => Promise.resolve("data:image/png;base64,") },
}));

import TwoFactorPanel from "../TwoFactorPanel";

beforeEach(() => {
  vi.clearAllMocks();
  status.current = { enrolled: false, recovery_codes_remaining: 0 };
});

describe("TwoFactorPanel while off", () => {
  it("reports an enrolment that could not start", async () => {
    api.enrollStart.mockRejectedValue(new Error("boom"));
    render(<TwoFactorPanel />);

    await userEvent.click(screen.getByRole("button", { name: /profile.two_factor.enable/ }));

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("profile.two_factor.error_enroll_start"),
    );
  });

  it("confirms the copied setup key", async () => {
    api.enrollStart.mockResolvedValue({ provisioning_uri: "otpauth://x", secret: "ABC123" });
    const user = userEvent.setup();
    render(<TwoFactorPanel />);

    await user.click(screen.getByRole("button", { name: /profile.two_factor.enable/ }));
    await user.click(await screen.findByRole("button", { name: "common.copy" }));

    await waitFor(() => expect(notify.success).toHaveBeenCalledWith("common.copied"));
    await expect(navigator.clipboard.readText()).resolves.toBe("ABC123");
  });

  it("says so when the clipboard refuses the setup key", async () => {
    api.enrollStart.mockResolvedValue({ provisioning_uri: "otpauth://x", secret: "ABC123" });
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
      new DOMException("Write permission denied.", "NotAllowedError"),
    );
    render(<TwoFactorPanel />);

    await user.click(screen.getByRole("button", { name: /profile.two_factor.enable/ }));
    await user.click(await screen.findByRole("button", { name: "common.copy" }));

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("common.copy_failed"));
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("shows the server's reason when an enrolment could not start", async () => {
    api.enrollStart.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { message: "Two-factor is already being set up." } },
    });
    render(<TwoFactorPanel />);

    await userEvent.click(screen.getByRole("button", { name: /profile.two_factor.enable/ }));

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("Two-factor is already being set up."),
    );
  });
});

describe("TwoFactorPanel while on", () => {
  beforeEach(() => {
    status.current = { enrolled: true, recovery_codes_remaining: 8 };
  });

  async function enterCodeAndClick(button: RegExp) {
    render(<TwoFactorPanel />);
    await userEvent.type(
      screen.getByLabelText("profile.two_factor.current_code_label"),
      "123456",
    );
    await userEvent.click(screen.getByRole("button", { name: button }));
  }

  it("says two-factor is disabled", async () => {
    api.disable.mockResolvedValue({});
    await enterCodeAndClick(/profile.two_factor.disable/);

    await waitFor(() =>
      expect(notify.success).toHaveBeenCalledWith("profile.two_factor.disabled"),
    );
    expect(api.disable).toHaveBeenCalledWith({ code: "123456" });
  });

  it.each([
    [/profile.two_factor.disable/, "disable", "profile.two_factor.error_disable"],
    [/profile.two_factor.regenerate_codes/, "regenerate", "profile.two_factor.error_regenerate"],
  ] as const)("reports a refused %s", async (button, call, shown) => {
    api[call].mockRejectedValue(new Error("boom"));
    await enterCodeAndClick(button);

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith(shown));
    expect(notify.success).not.toHaveBeenCalled();
  });
});
