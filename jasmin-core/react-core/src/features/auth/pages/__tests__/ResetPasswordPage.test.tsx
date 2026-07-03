import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { server } from "@/test/msw/server";

// FriendlyCaptcha (mounted on the form) calls useTenant(); hand it a static
// stub so the page renders without a real TenantProvider. Empty sitekey ->
// the widget renders null and the form submits frc_captcha_solution="".
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import ResetPasswordPage from "../ResetPasswordPage";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/reset/abc-uid/abc-token"]}>
      <Routes>
        <Route path="/reset/:uid/:token" element={<ResetPasswordPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  vi.useRealTimers();
});

describe("ResetPasswordPage (integration)", () => {
  it("submits uid + token + password and navigates to /login on success", async () => {
    let received: { uid?: string; token?: string; password?: string } | null =
      null;
    server.use(
      http.post("/api/auth/password-reset/confirm/", async ({ request }) => {
        received = (await request.json()) as typeof received;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();

    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });
    await user.type(
      screen.getByLabelText("auth.reset_password.new_password"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("auth.reset_password.confirm_password"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", {
        name: "auth.reset_password.submit",
      }),
    );

    expect(
      await screen.findByText("auth.reset_password.success"),
    ).toBeInTheDocument();
    expect(received).toEqual({
      uid: "abc-uid",
      token: "abc-token",
      password: "S3cret-passphrase!",
      frc_captcha_solution: "",
    });

    // Navigates after the delay (1.8s in the page).
    vi.advanceTimersByTime(2000);
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/login"));
  });

  it("cancels the pending /login redirect if it unmounts before the delay elapses", async () => {
    server.use(
      http.post("/api/auth/password-reset/confirm/", () =>
        HttpResponse.json({ detail: "ok" }),
      ),
    );

    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = renderPage();

    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });
    await user.type(
      screen.getByLabelText("auth.reset_password.new_password"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("auth.reset_password.confirm_password"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", { name: "auth.reset_password.submit" }),
    );

    expect(
      await screen.findByText("auth.reset_password.success"),
    ).toBeInTheDocument();

    // Leave the page within the 1.8s window — the effect cleanup must clear
    // the timer so navigate() never fires after unmount.
    unmount();
    vi.advanceTimersByTime(5000);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("shows the 'invalid or expired link' error when the backend rejects the token (400)", async () => {
    server.use(
      http.post("/api/auth/password-reset/confirm/", () =>
        HttpResponse.json(
          { code: "invalid_token", message: "Token is invalid" },
          { status: 400 },
        ),
      ),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("auth.reset_password.new_password"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("auth.reset_password.confirm_password"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", {
        name: "auth.reset_password.submit",
      }),
    );

    // The page surfaces the canonical error message via getErrorMessage().
    expect(await screen.findByText("Token is invalid")).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("shows a friendly throttle message on 429 and stays on the form", async () => {
    server.use(
      http.post("/api/auth/password-reset/confirm/", () =>
        HttpResponse.json({ detail: "Too Many Requests" }, { status: 429 }),
      ),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("auth.reset_password.new_password"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("auth.reset_password.confirm_password"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", {
        name: "auth.reset_password.submit",
      }),
    );

    expect(
      await screen.findByText(
        "auth.forgot_password.too_many_requests",
      ),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "auth.reset_password.submit" }),
    ).toBeInTheDocument();
  });

  it("blocks submit when the two passwords don't match (no network call)", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/password-reset/confirm/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("auth.reset_password.new_password"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("auth.reset_password.confirm_password"),
      "different-passphrase!",
    );
    await user.click(
      screen.getByRole("button", {
        name: "auth.reset_password.submit",
      }),
    );

    expect(
      await screen.findByText("auth.reset_password.mismatch"),
    ).toBeInTheDocument();
    expect(serverHit).toBe(false);
  });

  it("enforces the 10-character minimum client-side", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/password-reset/confirm/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("auth.reset_password.new_password"), "short");
    await user.type(screen.getByLabelText("auth.reset_password.confirm_password"), "short");
    await user.click(
      screen.getByRole("button", {
        name: "auth.reset_password.submit",
      }),
    );

    expect(
      await screen.findByText("auth.reset_password.password_min"),
    ).toBeInTheDocument();
    expect(serverHit).toBe(false);
  });

  it("renders a 'Back to sign in' link to /login", () => {
    renderPage();
    const link = screen.getByRole("link", { name: "auth.forgot_password.back_to_login" });
    expect(link).toHaveAttribute("href", "/login");
  });
});
