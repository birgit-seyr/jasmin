import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { axe } from "@/test/axe";
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
    // The About modal colours its check icons from the theme tokens.
    useTheme: () => ({ colorSuccess: "#52c41a" }),
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

// The captcha widget renders nothing without a sitekey; this stand-in also
// records when the page asks it for a fresh token.
const captchaReset = vi.hoisted(() => vi.fn());
vi.mock("@shared/auth/FriendlyCaptcha", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return {
    FriendlyCaptcha: forwardRef<{ reset: () => void }, object>(
      function FriendlyCaptcha(_props, ref) {
        useImperativeHandle(ref, () => ({ reset: captchaReset }));
        return null;
      },
    ),
  };
});

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

import { AuthProvider } from "@shared/contexts/AuthContext";
import { LocaleProvider, useLocale } from "@shared/contexts/LocaleContext";
import i18n from "@shared/i18n";
import { SUPPORTED_LANGUAGES } from "@shared/i18n/languages";
import LoginPage from "../LoginPage";
import { clearAccessToken, getAccessToken } from "@shared/services/tokenStore";

/** The backend's English text for a lock, which the page must not show. */
const LOCKED_SERVER_MESSAGE =
  "Too many failed attempts. Try again later or reset your password.";

/** The app's own lockout text in the language the page speaks; a key missing
 *  from the catalogue would come back as the key itself. */
function lockedMessage(): string {
  const message = i18n.t("errors.auth.account_locked");
  expect(message).not.toBe("errors.auth.account_locked");
  return message;
}

/** The language the app speaks, which JasminApp hands to i18next. */
let pageLanguage: string | null = null;
function LanguageProbe() {
  pageLanguage = useLocale().language;
  return null;
}

function renderLogin() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LocaleProvider>
          <LoginPage />
          <LanguageProbe />
        </LocaleProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  captchaReset.mockClear();
  clearAccessToken();
  localStorage.clear();
  pageLanguage = null;
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

  it("tells a device whose stored session expired to sign in again", async () => {
    // The default MSW handler answers the boot refresh with a 401.
    localStorage.setItem(
      "auth",
      JSON.stringify({ user: { id: "u-1", roles: ["office"] } }),
    );

    renderLogin();

    expect(
      await screen.findByText("auth.login_card.session_expired"),
    ).toBeInTheDocument();
  });

  it("shows no session notice on a first visit", async () => {
    let refreshAttempted = false;
    server.use(
      http.post(/\/auth\/refresh\/?$/, () => {
        refreshAttempted = true;
        return HttpResponse.json({ detail: "no cookie" }, { status: 401 });
      }),
    );

    renderLogin();

    // Only once the refresh has failed would a notice show.
    await waitFor(() => expect(refreshAttempted).toBe(true));
    await flushMicrotasks();
    expect(
      screen.queryByText("auth.login_card.session_expired"),
    ).not.toBeInTheDocument();
  });

  it("has no axe violations, including the session notice", async () => {
    localStorage.setItem(
      "auth",
      JSON.stringify({ user: { id: "u-1", roles: ["office"] } }),
    );

    const { container } = renderLogin();

    await screen.findByText("auth.login_card.session_expired");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("asks the captcha for a fresh token after a failed login", async () => {
    // Verification spends the token, so the retry needs a new one.
    server.use(
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
    expect(captchaReset).toHaveBeenCalledTimes(1);
  });

  it("surfaces a server error message and does NOT navigate on bad credentials", async () => {
    // A 401 on /auth/login/ must surface the real error — it must not chain
    // into the axios response interceptor's silent-refresh flow and show
    // "No refresh cookie" instead. The interceptor explicitly excludes
    // /auth/login/, /auth/register/ and /auth/logout/.
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

  it("shows the lockout in the app's own words on a 429 auth.account_locked", async () => {
    // 429, not 401: a 401 would send the client into a silent refresh.
    let refreshAttempts = 0;
    server.use(
      http.post(/\/auth\/refresh\/?$/, () => {
        refreshAttempts += 1;
        return HttpResponse.json({ detail: "no cookie" }, { status: 401 });
      }),
      http.post("/api/auth/login/", () =>
        HttpResponse.json(
          { code: "auth.account_locked", message: LOCKED_SERVER_MESSAGE },
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

    expect(await screen.findByText(lockedMessage())).toBeInTheDocument();
    expect(screen.queryByText(LOCKED_SERVER_MESSAGE)).not.toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
    // Boot fires one silent refresh; the refused login adds none.
    expect(refreshAttempts).toBe(1);
  });

  it("shows the lockout when the second step is refused", async () => {
    server.use(
      http.post("/api/auth/login/", () =>
        HttpResponse.json({ requires_2fa: true, challenge_token: "challenge" }),
      ),
      http.post("/api/auth/two-factor/verify/", () =>
        HttpResponse.json(
          { code: "auth.account_locked", message: LOCKED_SERVER_MESSAGE },
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
    await user.type(await screen.findByPlaceholderText("123456"), "123456");
    await user.click(
      screen.getByRole("button", { name: "auth.two_factor.verify" }),
    );

    expect(await screen.findByText(lockedMessage())).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
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

  it("starts in the browser's language and lets the visitor switch it", async () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["de-DE", "de"]);
    const { container } = renderLogin();

    const switcher = screen.getByRole("combobox", { name: "common.language" });
    const languageOf = (code: string) =>
      SUPPORTED_LANGUAGES.find((language) => language.code === code)!;
    const shownLanguage = () =>
      container.querySelector(".ant-select-selection-item")?.textContent;
    expect(pageLanguage).toBe("de");
    expect(shownLanguage()).toBe(languageOf("de").label);

    const user = userEvent.setup();
    await user.click(switcher);
    const list = await screen.findByRole("listbox");
    await user.click(
      within(list).getByRole("option", { name: languageOf("en").name }),
    );

    await waitFor(() => expect(pageLanguage).toBe("en"));
    expect(shownLanguage()).toBe(languageOf("en").label);
    // Kept in this browser for the next visit.
    expect(localStorage.getItem("language")).toBe("en");
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
        <AuthProvider>
          <LocaleProvider>{profiler.wrap(<LoginPage />, "login")}</LocaleProvider>
        </AuthProvider>
      </MemoryRouter>,
    );

    await screen.findByPlaceholderText("auth.login_card.email");
    await flushMicrotasks();

    // Healthy baseline: ~6 commits. Bound is loose so legitimate refactors
    // don't trip it — a real loop would be in the thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(50);
  });
});
