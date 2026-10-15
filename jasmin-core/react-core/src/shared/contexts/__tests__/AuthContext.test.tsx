import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ---- Module mocks --------------------------------------------------------
// We mock the api layer but use the REAL tokenStore so we exercise the
// subscribe/notify wiring AuthContext relies on.

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

const performRefreshMock = vi.fn<() => Promise<RefreshedSession>>();
const axiosPostMock = vi.fn();

vi.mock("@shared/services/api", () => ({
  default: { post: (...args: unknown[]) => axiosPostMock(...args) },
  performRefresh: () => performRefreshMock(),
}));

import { AuthProvider, useAuth } from "../AuthContext";
import type { RefreshedSession } from "@shared/services/api";
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@shared/services/tokenStore";

// ---- Probe component -----------------------------------------------------
let probedAuth: ReturnType<typeof useAuth> | null = null;
function Probe() {
  probedAuth = useAuth();
  return (
    <div>
      <span data-testid="auth-loading">{String(probedAuth.loading)}</span>
      <span data-testid="auth-isauth">
        {String(probedAuth.isAuthenticated)}
      </span>
      <span data-testid="auth-user">
        {probedAuth.user ? probedAuth.user.id : "anon"}
      </span>
      <span data-testid="auth-token">{probedAuth.accessToken ?? "none"}</span>
      <span data-testid="auth-notice">{probedAuth.sessionNotice ?? "none"}</span>
    </div>
  );
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  probedAuth = null;
  navigateMock.mockReset();
  performRefreshMock.mockReset();
  axiosPostMock.mockReset();
  clearAccessToken();
  localStorage.clear();
  // Default: hostname → tenant subdomain (so /api/auth/* endpoints are used).
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, hostname: "test.localhost" },
  });
});

describe("AuthContext boot", () => {
  it("attempts a silent refresh on mount and clears loading on success", async () => {
    performRefreshMock.mockImplementation(async () => {
      setAccessToken("fresh-access");
      return { access: "fresh-access" };
    });

    renderProvider();

    expect(performRefreshMock).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    expect(screen.getByTestId("auth-isauth").textContent).toBe("true");
    expect(screen.getByTestId("auth-token").textContent).toBe("fresh-access");
  });

  it("clears loading even when silent refresh fails (no cookie)", async () => {
    performRefreshMock.mockRejectedValue(new Error("no cookie"));

    renderProvider();

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    expect(screen.getByTestId("auth-isauth").textContent).toBe("false");
  });

  it("hydrates the cached user from localStorage before the refresh resolves", async () => {
    localStorage.setItem(
      "auth",
      JSON.stringify({ user: { id: "u-7", roles: ["office"] } }),
    );
    performRefreshMock.mockResolvedValue({ access: "tok" });

    renderProvider();

    // Hydration happens synchronously inside the boot effect.
    await waitFor(() =>
      expect(screen.getByTestId("auth-user").textContent).toBe("u-7"),
    );
  });
});

describe("AuthContext boot without stored metadata", () => {
  // The user as the tenant realm's refresh answer carries it.
  const refreshedMember = {
    id: "u-9",
    email: "member@example.com",
    first_name: "Mia",
    last_name: "Muster",
    user_language: "de",
    theme: "light" as const,
    roles: ["member"],
    member_id: "m-9",
    reseller_id: null,
  };

  it("takes the user from the refresh answer when the stored metadata is gone", async () => {
    // Another tab dropped the metadata; the refresh cookie lives on.
    performRefreshMock.mockImplementation(async () => {
      setAccessToken("fresh-access");
      return { access: "fresh-access", user: refreshedMember };
    });

    renderProvider();

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    expect(probedAuth?.isAuthenticated).toBe(true);
    expect(probedAuth?.user).toMatchObject({
      id: "u-9",
      roles: ["member"],
      member_id: "m-9",
    });
    expect(JSON.parse(localStorage.getItem("auth") ?? "{}").user).toEqual(
      refreshedMember,
    );
    // The access token stays in memory only.
    expect(localStorage.getItem("auth")).not.toContain("fresh-access");
  });

  it("keeps a stored user, with what only this device knows about them", async () => {
    localStorage.setItem(
      "auth",
      JSON.stringify({
        user: { id: "u-9", roles: ["member"], edit_mode: "modal" },
      }),
    );
    performRefreshMock.mockImplementation(async () => {
      setAccessToken("fresh-access");
      return { access: "fresh-access", user: refreshedMember };
    });

    renderProvider();

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    expect(probedAuth?.user?.edit_mode).toBe("modal");
    expect(JSON.parse(localStorage.getItem("auth") ?? "{}").user.edit_mode).toBe(
      "modal",
    );
  });

  it("stays without a user when the refresh answer has none (super-admin realm)", async () => {
    performRefreshMock.mockImplementation(async () => {
      setAccessToken("admin-access");
      return { access: "admin-access" };
    });

    renderProvider();

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    expect(probedAuth?.isAuthenticated).toBe(true);
    expect(probedAuth?.user).toBeNull();
    expect(localStorage.getItem("auth")).toBeNull();
  });
});

describe("AuthContext session notice", () => {
  const storeSession = () =>
    localStorage.setItem(
      "auth",
      JSON.stringify({ user: { id: "u-7", roles: ["office"] } }),
    );
  // axios's ``isAxiosError`` only looks at this flag.
  const refused = { isAxiosError: true, response: { status: 401 } };
  const offline = { isAxiosError: true, code: "ERR_NETWORK" };

  async function noticeAfterBoot() {
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    return screen.getByTestId("auth-notice").textContent;
  }

  it("says the session expired when the server refuses a stored one", async () => {
    storeSession();
    performRefreshMock.mockRejectedValue(refused);

    expect(await noticeAfterBoot()).toBe("expired");
  });

  it("says the server is unreachable when the refresh never gets an answer", async () => {
    storeSession();
    performRefreshMock.mockRejectedValue(offline);

    expect(await noticeAfterBoot()).toBe("unreachable");
  });

  it("says nothing to a device that was never signed in", async () => {
    performRefreshMock.mockRejectedValue(refused);

    expect(await noticeAfterBoot()).toBe("none");
  });

  it("clears the notice once a new access token arrives", async () => {
    storeSession();
    performRefreshMock.mockRejectedValue(refused);
    expect(await noticeAfterBoot()).toBe("expired");

    act(() => setAccessToken("signed-in-again"));

    expect(screen.getByTestId("auth-notice").textContent).toBe("none");
  });
});

describe("AuthContext.login", () => {
  beforeEach(() => {
    performRefreshMock.mockRejectedValue(new Error("anon"));
  });

  it("sets the token + user and routes to / on a successful office login", async () => {
    axiosPostMock.mockResolvedValue({
      data: {
        access: "new-jwt",
        user: { id: "u-1", roles: ["office"] },
      },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );

    await act(async () => {
      await probedAuth!.login({ email: "a@b.c", password: "pw" });
    });

    expect(axiosPostMock).toHaveBeenCalledWith("/api/auth/login/", {
      email: "a@b.c",
      password: "pw",
    });
    expect(getAccessToken()).toBe("new-jwt");
    expect(probedAuth?.isAuthenticated).toBe(true);
    expect(probedAuth?.user?.id).toBe("u-1");
    expect(navigateMock).toHaveBeenLastCalledWith("/");
  });

  it("routes a member-only user straight to their member page", async () => {
    axiosPostMock.mockResolvedValue({
      data: {
        access: "tok",
        user: { id: "u-2", roles: ["member"], member_id: "m-99" },
      },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );

    await act(async () => {
      await probedAuth!.login({ email: "user@example.com", password: "pw" });
    });

    expect(navigateMock).toHaveBeenLastCalledWith("/members/members/m-99");
  });

  it("uses super-admin endpoints on the platform host", async () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, hostname: "marillen.example.com" },
    });
    axiosPostMock.mockResolvedValue({
      data: { access: "admin-jwt", user: { id: "sa-1" } },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );

    await act(async () => {
      await probedAuth!.login({ email: "user@example.com", password: "pw" });
    });

    expect(axiosPostMock).toHaveBeenCalledWith(
      "/api/super-admin/auth/login/",
      { email: "user@example.com", password: "pw" },
    );
    expect(navigateMock).toHaveBeenLastCalledWith("/admin");
    expect(probedAuth?.isSuperAdmin).toBe(true);
  });

  it("propagates the error and surfaces a message when login fails", async () => {
    const failure = Object.assign(new Error("Invalid credentials"), {
      isAxiosError: true,
      response: {
        data: { code: "auth.invalid", message: "Invalid credentials" },
      },
    });
    axiosPostMock.mockRejectedValue(failure);

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );

    await act(async () => {
      await probedAuth!.login({ email: "x", password: "y" }).catch(() => {});
    });

    await waitFor(() => expect(probedAuth?.error).toBe("Invalid credentials"));
    expect(probedAuth?.isAuthenticated).toBe(false);
    expect(navigateMock).not.toHaveBeenCalled();
  });
});

describe("AuthContext.logout", () => {
  beforeEach(() => {
    performRefreshMock.mockImplementation(async () => {
      setAccessToken("tok");
      return { access: "tok" };
    });
  });

  it("never writes the access token to localStorage", async () => {
    // The access token is deliberately in-memory ONLY (see
    // shared/services/tokenStore.ts) so an XSS payload cannot exfiltrate it;
    // the refresh token is HttpOnly and never reaches JS at all. localStorage
    // holds user METADATA only. AuthMetadata has an open index signature
    // (`[key: string]: unknown`), so nothing in the type system stops a token
    // being spread into the persisted blob — this is the guard that does.
    const SECRET = "super-secret-access-token-value";

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-isauth").textContent).toBe("true"),
    );

    act(() =>
      probedAuth!.setSession(SECRET, { id: "u-1", email: "a@example.org" }),
    );

    // It IS live in the in-memory store...
    expect(getAccessToken()).toBe(SECRET);

    // ...and absent from every persisted value.
    const raw = localStorage.getItem("auth");
    expect(raw).not.toBeNull();
    expect(raw).not.toContain(SECRET);
    for (const key of Object.keys(localStorage)) {
      expect(localStorage.getItem(key) ?? "").not.toContain(SECRET);
    }
    expect(sessionStorage.getItem("auth")).toBeNull();

    // The metadata that SHOULD persist still does.
    expect(JSON.parse(raw!).user.id).toBe("u-1");
  });

  it("clears the token, wipes localStorage and navigates to /login", async () => {
    axiosPostMock.mockResolvedValue({ data: {} });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-isauth").textContent).toBe("true"),
    );
    // Seed user so we can prove it's wiped.
    act(() => probedAuth!.setSession("tok", { id: "u-1" }));
    expect(localStorage.getItem("auth")).not.toBeNull();

    await act(async () => {
      await probedAuth!.logout();
    });

    expect(axiosPostMock).toHaveBeenCalledWith("/api/auth/logout/", {});
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("auth")).toBeNull();
    expect(navigateMock).toHaveBeenLastCalledWith("/login");
    expect(probedAuth?.isAuthenticated).toBe(false);
    expect(probedAuth?.user).toBeNull();
  });

  it("still cleans up locally when the logout API call errors", async () => {
    axiosPostMock.mockRejectedValue(new Error("server down"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-isauth").textContent).toBe("true"),
    );
    act(() => probedAuth!.setSession("tok", { id: "u-1" }));

    await act(async () => {
      await probedAuth!.logout();
    });

    expect(getAccessToken()).toBeNull();
    expect(probedAuth?.isAuthenticated).toBe(false);
    expect(navigateMock).toHaveBeenLastCalledWith("/login");
    errorSpy.mockRestore();
  });
});

describe("AuthContext token sync + helpers", () => {
  it("flips to logged-out when the tokenStore is cleared externally, leaving the shared metadata", async () => {
    performRefreshMock.mockImplementation(async () => {
      setAccessToken("tok");
      return { access: "tok" };
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-isauth").textContent).toBe("true"),
    );
    act(() => probedAuth!.setSession("tok", { id: "u-1" }));
    expect(localStorage.getItem("auth")).not.toBeNull();

    // Simulate api.ts clearing the token after a failed silent refresh.
    act(() => clearAccessToken());

    await waitFor(() =>
      expect(screen.getByTestId("auth-isauth").textContent).toBe("false"),
    );
    expect(probedAuth?.user).toBeNull();
    // Other tabs share the stored metadata; whether the session is over for
    // them too is api.ts's call, from the server's answer.
    expect(JSON.parse(localStorage.getItem("auth") ?? "{}").user.id).toBe(
      "u-1",
    );
  });

  it("hasRole consults the live user", async () => {
    performRefreshMock.mockRejectedValue(new Error("anon"));
    axiosPostMock.mockResolvedValue({
      data: {
        access: "tok",
        user: {
          id: "u-1",
          roles: ["office", "member"],
        },
      },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );
    await act(async () => {
      await probedAuth!.login({ email: "user@example.com", password: "pw" });
    });

    expect(probedAuth!.hasRole("office")).toBe(true);
    expect(probedAuth!.hasRole(["admin", "member"])).toBe(true);
    expect(probedAuth!.hasRole("admin")).toBe(false);
    // userRole prefers "admin" then first role.
    expect(probedAuth!.userRole).toBe("office");
  });

  it("updateUser merges new fields and persists to localStorage", async () => {
    performRefreshMock.mockRejectedValue(new Error("anon"));
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );

    act(() =>
      probedAuth!.setSession("tok", { id: "u-1", user_language: "de" }),
    );
    act(() => probedAuth!.updateUser({ user_language: "en", theme: "dark" }));

    expect(probedAuth!.user).toMatchObject({
      id: "u-1",
      user_language: "en",
      theme: "dark",
    });
    const stored = JSON.parse(localStorage.getItem("auth") ?? "{}");
    expect(stored.user.user_language).toBe("en");
    expect(stored.user.theme).toBe("dark");
  });

  it("refreshAccessToken delegates to performRefresh and rethrows on failure", async () => {
    performRefreshMock.mockRejectedValueOnce(new Error("boot"));
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("false"),
    );

    performRefreshMock.mockResolvedValueOnce({ access: "rotated" });
    await expect(probedAuth!.refreshAccessToken()).resolves.toBe("rotated");

    performRefreshMock.mockRejectedValueOnce(new Error("rotation failed"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setAccessToken("stale");
    await expect(probedAuth!.refreshAccessToken()).rejects.toThrow(
      "rotation failed",
    );
    expect(getAccessToken()).toBeNull();
    errorSpy.mockRestore();
  });
});

// Touch userEvent so the import is exercised even when individual cases
// drive state via the probed context. This keeps the dep installed and lets
// future tests grab it without re-wiring imports.
void userEvent;
