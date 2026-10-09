/**
 * ModalProvider: the edit mode is a device-local preference. It lives on the
 * signed-in user kept in the stored ``auth`` entry, so it survives a reload,
 * and it is never sent to the server. When the browser refuses to store it,
 * the mode still switches for this session and the user is told it was not
 * saved.
 */
import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

const { notify, profileUpdate, apiPost } = vi.hoisted(() => ({
  notify: { error: vi.fn(), success: vi.fn() },
  profileUpdate: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock("@shared/api/generated/auth/auth", () => ({
  authPartialUpdate: profileUpdate,
}));
vi.mock("@shared/services/api", () => ({
  default: { post: apiPost },
  performRefresh: () => Promise.resolve("token"),
}));
vi.mock("@shared/utils/notify", () => ({ default: notify }));

import { AuthProvider } from "../AuthContext";
import { ModalProvider, useModal } from "../ModalContext";

let probed: ReturnType<typeof useModal> | null = null;
function Probe() {
  probed = useModal();
  return null;
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ModalProvider>
          <Probe />
        </ModalProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

function storedUser() {
  return JSON.parse(localStorage.getItem("auth") ?? "{}").user;
}

beforeEach(() => {
  probed = null;
  localStorage.clear();
  localStorage.setItem("auth", JSON.stringify({ user: { id: "u1" } }));
  notify.error.mockReset();
  profileUpdate.mockReset();
  apiPost.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ModalProvider edit mode", () => {
  it("keeps the toggled mode on the stored user without asking the server", async () => {
    renderProvider();
    await waitFor(() => expect(probed?.editMode).toBe("inline"));

    act(() => probed!.toggleEditMode());

    expect(probed?.editMode).toBe("modal");
    expect(storedUser()).toEqual({ id: "u1", edit_mode: "modal" });
    expect(profileUpdate).not.toHaveBeenCalled();
    expect(apiPost).not.toHaveBeenCalled();
    expect(notify.error).not.toHaveBeenCalled();
  });

  it("opens in the stored mode after a reload", async () => {
    const first = renderProvider();
    await waitFor(() => expect(probed?.editMode).toBe("inline"));
    act(() => probed!.toggleEditMode());
    first.unmount();

    renderProvider();

    await waitFor(() => expect(probed?.isModalMode).toBe(true));
  });

  it("switches for the session and says so when the browser refuses to store it", async () => {
    renderProvider();
    await waitFor(() => expect(probed?.editMode).toBe("inline"));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });

    act(() => probed!.toggleEditMode());

    expect(probed?.editMode).toBe("modal");
    expect(notify.error).toHaveBeenCalledWith("profile.preferences_save_error");
    expect(profileUpdate).not.toHaveBeenCalled();
  });
});
