import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { server } from "@/test/msw/server";
import { profileRenders, flushMicrotasks } from "@/test/profileRenders";

// useTenant is async + heavy (fetches tenant config). For an auth-page
// integration test we hand it a static stub so the MSW handlers below only
// have to model the auth endpoints we actually exercise.
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    tenant: { schema_name: "test", name: "Test Tenant" },
    logoUrl: "/logo.png",
  });
  return {
    useTenant: () => tenant,
    // LoginPage reads the trial duration for the trial card subtitle.
    useSubscriptionTerm: () => ({ trialDurationInDeliveries: 4 }),
  };
});

// react-i18next without an initialised instance returns each key as-is.
// We don't initialise the real i18n in this test — the assertions match
// keys directly, which keeps the test robust against translation churn.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

import { AuthProvider } from "@shared/contexts/AuthContext";
import LoginPage from "../LoginPage";
import { clearAccessToken, getAccessToken } from "@shared/services/tokenStore";

function renderLogin() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  clearAccessToken();
  localStorage.clear();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, hostname: "test.localhost" },
  });
});

describe("LoginPage (integration)", () => {
  it("submits credentials, stores the token and routes to /", async () => {
    let received: { email?: string; password?: string } | null = null;

    server.use(
      http.post("/api/auth/login/", async ({ request }) => {
        received = (await request.json()) as typeof received;
        return HttpResponse.json({
          access: "good-jwt",
          user: { id: "u-1", roles: ["office"], permissions: [] },
        });
      }),
    );

    renderLogin();

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText("auth.login_card.email"),
      "alice@example.com",
    );
    await user.type(
      screen.getByPlaceholderText("auth.login_card.password"),
      "supersecret",
    );
    await user.click(
      screen.getByRole("button", { name: "auth.login_card.sign_in" }),
    );

    await waitFor(() => expect(received).not.toBeNull());
    expect(received).toEqual({
      email: "alice@example.com",
      password: "supersecret",
      frc_captcha_solution: "",
    });
    await waitFor(() => expect(getAccessToken()).toBe("good-jwt"));
    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("surfaces a server error message and does NOT navigate on bad credentials", async () => {
    // Regression test: in the past, a 401 on /auth/login/ chained into the
    // axios response interceptor's silent-refresh flow and the user saw
    // "No refresh cookie" instead of the real error. The interceptor now
    // explicitly excludes /auth/login/, /auth/register/ and /auth/logout/.
    let refreshAttempts = 0;
    server.use(
      http.post(/\/auth\/refresh\/?$/, () => {
        refreshAttempts += 1;
        return HttpResponse.json({ detail: "no cookie" }, { status: 401 });
      }),
      http.post("/api/auth/login/", () =>
        HttpResponse.json(
          { code: "auth.invalid", message: "Wrong email or password" },
          { status: 401 },
        ),
      ),
    );

    renderLogin();

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText("auth.login_card.email"),
      "alice@example.com",
    );
    await user.type(
      screen.getByPlaceholderText("auth.login_card.password"),
      "nope",
    );
    await user.click(
      screen.getByRole("button", { name: "auth.login_card.sign_in" }),
    );

    expect(
      await screen.findByText("Wrong email or password"),
    ).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
    expect(navigateMock).not.toHaveBeenCalled();
    // Boot fires one silent-refresh; the failed login MUST NOT add a second.
    expect(refreshAttempts).toBe(1);
  });

  it("blocks submit + shows validation when email is invalid", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/login/", () => {
        serverHit = true;
        return HttpResponse.json({ access: "x" });
      }),
    );

    renderLogin();

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText("auth.login_card.email"),
      "not-an-email",
    );
    await user.type(
      screen.getByPlaceholderText("auth.login_card.password"),
      "pw",
    );
    await user.click(
      screen.getByRole("button", { name: "auth.login_card.sign_in" }),
    );

    expect(
      await screen.findByText("auth.login_card.please_enter_valid_email"),
    ).toBeInTheDocument();
    expect(serverHit).toBe(false);
    expect(getAccessToken()).toBeNull();
  });

  it("surfaces a friendly message on a 429 lockout (django-axes)", async () => {
    server.use(
      http.post("/api/auth/login/", () =>
        HttpResponse.json(
          {
            code: "auth.locked",
            message: "Too many failed attempts. Try again in 15 minutes.",
          },
          { status: 429 },
        ),
      ),
    );

    renderLogin();

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText("auth.login_card.email"),
      "alice@example.com",
    );
    await user.type(
      screen.getByPlaceholderText("auth.login_card.password"),
      "pw",
    );
    await user.click(
      screen.getByRole("button", { name: "auth.login_card.sign_in" }),
    );

    expect(
      await screen.findByText(
        "Too many failed attempts. Try again in 15 minutes.",
      ),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("routes a member-only login straight to their member detail page", async () => {
    server.use(
      http.post("/api/auth/login/", () =>
        HttpResponse.json({
          access: "tok",
          user: {
            id: "u-2",
            roles: ["member"],
            member_id: "m-42",
            permissions: [],
          },
        }),
      ),
    );

    renderLogin();

    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText("auth.login_card.email"),
      "m@example.com",
    );
    await user.type(
      screen.getByPlaceholderText("auth.login_card.password"),
      "pw",
    );
    await user.click(
      screen.getByRole("button", { name: "auth.login_card.sign_in" }),
    );

    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/members/members/m-42"),
    );
  });

  // Render-loop smoke test — if a context, hook or memo regression starts
  // re-rendering the page on every commit, this catches the runaway loop
  // long before it becomes a perf bug. The bound is intentionally LOOSE:
  // a healthy LoginPage commits ~3-6 times during mount + AuthContext init.
  // 50 = something is seriously wrong (setState-in-render, unmemoised
  // context value, etc.).
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();

    render(
      <MemoryRouter>
        <AuthProvider>{profiler.wrap(<LoginPage />, "login")}</AuthProvider>
      </MemoryRouter>,
    );

    await screen.findByPlaceholderText("auth.login_card.email");
    await flushMicrotasks();

    // Healthy baseline: ~6 commits. Bound is loose so legitimate refactors
    // don't trip it — a real loop would be in the thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(50);
  });
});
