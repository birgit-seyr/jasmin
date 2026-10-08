/**
 * UserProfileModal: the signed-in user's own name, edited on the profile tab.
 * The profile PATCH is the mocking boundary; the 2FA and my-data tabs are
 * stubbed, since only the profile tab is under test.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { authPartialUpdate, notify, updateUser } = vi.hoisted(() => ({
  authPartialUpdate: vi.fn(),
  notify: { error: vi.fn(), success: vi.fn() },
  updateUser: vi.fn(),
}));

vi.mock("@shared/api/generated/auth/auth", () => ({ authPartialUpdate }));
vi.mock("@shared/api/generated/gdpr/gdpr", () => ({
  gdprRequestDeletionCreate: vi.fn(),
}));
vi.mock("@shared/utils/notify", () => ({ default: notify }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      email: "ada@example.com",
      first_name: "Ada",
      last_name: "Lovelace",
      roles: ["member"],
    },
    logout: vi.fn(),
    updateUser,
  }),
}));
vi.mock("@shared/profile/TwoFactorPanel", () => ({
  default: () => <div data-testid="two-factor-panel" />,
}));
vi.mock("../MyDataTab", () => ({
  default: () => <div data-testid="my-data-tab" />,
}));

import UserProfileModal from "../UserProfileModal";

async function editAndSave() {
  render(<UserProfileModal open onClose={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "common.edit" }));
  for (const [label, value] of [
    ["profile.first_name", "Ada"],
    ["profile.last_name", "Byron"],
  ]) {
    const input = screen.getByLabelText(label);
    await userEvent.clear(input);
    await userEvent.type(input, value);
  }
  await userEvent.click(screen.getByRole("button", { name: "common.save" }));
}

let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  authPartialUpdate.mockReset();
  notify.error.mockReset();
  notify.success.mockReset();
  updateUser.mockReset();
  consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

describe("UserProfileModal profile save", () => {
  it("saves the name to the profile and the signed-in user", async () => {
    authPartialUpdate.mockResolvedValue({});

    await editAndSave();

    await waitFor(() => expect(notify.success).toHaveBeenCalledWith("profile.saved"));
    expect(authPartialUpdate).toHaveBeenCalledWith("u1", {
      first_name: "Ada",
      last_name: "Byron",
    });
    expect(updateUser).toHaveBeenCalledWith({
      first_name: "Ada",
      last_name: "Byron",
    });
  });

  it("tells the user a refused save failed and logs nothing to the console", async () => {
    authPartialUpdate.mockRejectedValue(new Error("Network Error"));

    await editAndSave();

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("profile.save_error"),
    );
    expect(updateUser).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
  });
});
