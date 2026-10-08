/**
 * ModalProvider: saving the edit mode to the profile. A failed save is shown
 * through notify, with the server's reason or a translated fallback, and
 * rethrown to a caller that awaits it; the toggle takes the rejection up
 * itself, so it never surfaces as an unhandled one.
 */
import { act, render, waitFor } from "@testing-library/react";
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

const { notify, updateUser } = vi.hoisted(() => ({
  notify: { error: vi.fn(), success: vi.fn() },
  updateUser: vi.fn(),
}));

// A plain function, not ``vi.fn``: a mock subscribes to the promise it
// returns, which would take up the rejection the toggle has to handle.
let profileUpdate: () => Promise<unknown> = () => Promise.resolve({});
const profileUpdates: unknown[][] = [];
vi.mock("@shared/api/generated/auth/auth", () => ({
  authPartialUpdate: (...args: unknown[]) => {
    profileUpdates.push(args);
    return profileUpdate();
  },
}));
vi.mock("@shared/utils/notify", () => ({ default: notify }));

const auth: { user: { id: string; edit_mode?: string } | null } = {
  user: { id: "u1" },
};
vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user: auth.user, updateUser }),
}));

import { ModalProvider, useModal } from "../ModalContext";

let probed: ReturnType<typeof useModal> | null = null;
function Probe() {
  probed = useModal();
  return null;
}

function renderProvider() {
  return render(
    <ModalProvider>
      <Probe />
    </ModalProvider>,
  );
}

let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  auth.user = { id: "u1" };
  probed = null;
  profileUpdate = () => Promise.resolve({});
  profileUpdates.length = 0;
  notify.error.mockReset();
  updateUser.mockReset();
  consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

describe("ModalProvider edit mode", () => {
  it("saves the mode to the profile and the signed-in user", async () => {
    renderProvider();

    await act(() => probed!.saveEditMode("modal"));

    expect(profileUpdates).toEqual([["u1", { edit_mode: "modal" }]]);
    expect(updateUser).toHaveBeenCalledWith({ edit_mode: "modal" });
    expect(probed?.editMode).toBe("modal");
    expect(notify.error).not.toHaveBeenCalled();
  });

  it("shows the server's reason for a refused save and rethrows it", async () => {
    const refusal = {
      isAxiosError: true,
      response: { status: 400, data: { message: "Not allowed" } },
    };
    profileUpdate = () => Promise.reject(refusal);
    renderProvider();

    await act(() =>
      expect(probed!.saveEditMode("modal")).rejects.toBe(refusal),
    );

    expect(notify.error).toHaveBeenCalledWith("Not allowed");
    expect(probed?.error).toBe("Not allowed");
    expect(probed?.editMode).toBe("inline");
    expect(updateUser).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("falls back to the translated message when the server gives no reason", async () => {
    profileUpdate = () => Promise.reject(new Error("Network Error"));
    renderProvider();

    await act(() => probed!.saveEditMode("modal").catch(() => undefined));

    expect(notify.error).toHaveBeenCalledWith("profile.preferences_save_error");
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("lets the toggle's refused save end in the message alone", async () => {
    profileUpdate = () => Promise.reject(new Error("Network Error"));
    renderProvider();

    act(() => probed!.toggleEditMode());

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("profile.preferences_save_error"),
    );
    await waitFor(() => expect(probed?.loading).toBe(false));
    expect(probed?.editMode).toBe("inline");
  });
});
