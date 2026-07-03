import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { server } from "@/test/msw/server";

// FriendlyCaptcha (mounted on the form) calls useTenant(); hand it a static
// stub so the page renders without a real TenantProvider. Empty sitekey ->
// the widget renders null and the form submits frc_captcha_solution="".
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
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

import ForgotPasswordPage from "../ForgotPasswordPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe("ForgotPasswordPage (integration)", () => {
  it("submits the email and shows the generic 'check your inbox' confirmation", async () => {
    let received: { email?: string } | null = null;
    server.use(
      http.post("/api/auth/password-reset/request/", async ({ request }) => {
        received = (await request.json()) as typeof received;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox", { name: /email/i }),
      "alice@example.com",
    );
    await user.click(
      screen.getByRole("button", {
        name: "auth.forgot_password.submit",
      }),
    );

    expect(await screen.findByText("auth.forgot_password.sent_title")).toBeInTheDocument();
    expect(received).toEqual({
      email: "alice@example.com",
      frc_captcha_solution: "",
    });
    // Form is replaced by the success alert — no submit button on the page.
    expect(
      screen.queryByRole("button", { name: "auth.forgot_password.submit" }),
    ).not.toBeInTheDocument();
  });

  it("ALWAYS shows the same generic confirmation regardless of whether the email is registered (anti-enumeration contract)", async () => {
    // Backend returns 200 for both hits and misses; the page must therefore
    // never differentiate. We just verify the same UI as the happy path.
    server.use(
      http.post("/api/auth/password-reset/request/", () =>
        HttpResponse.json({ detail: "ok" }),
      ),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox", { name: /email/i }),
      "ghost@example.com",
    );
    await user.click(screen.getByRole("button", { name: "auth.forgot_password.submit" }));

    expect(await screen.findByText("auth.forgot_password.sent_title")).toBeInTheDocument();
  });

  it("shows a friendly throttle message on 429 and KEEPS the form mounted", async () => {
    server.use(
      http.post("/api/auth/password-reset/request/", () =>
        HttpResponse.json({ detail: "Too Many Requests" }, { status: 429 }),
      ),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox", { name: /email/i }),
      "alice@example.com",
    );
    await user.click(screen.getByRole("button", { name: "auth.forgot_password.submit" }));

    expect(
      await screen.findByText(
        "auth.forgot_password.too_many_requests",
      ),
    ).toBeInTheDocument();
    // Form must still be present so the user can retry — success alert MUST NOT
    // render on a throttled attempt.
    expect(
      screen.getByRole("button", { name: "auth.forgot_password.submit" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("auth.forgot_password.sent_title")).not.toBeInTheDocument();
  });

  it("shows a generic error on a 500 and keeps the form mounted", async () => {
    server.use(
      http.post("/api/auth/password-reset/request/", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox", { name: /email/i }),
      "alice@example.com",
    );
    await user.click(screen.getByRole("button", { name: "auth.forgot_password.submit" }));

    expect(
      await screen.findByText("auth.forgot_password.generic_error"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "auth.forgot_password.submit" }),
    ).toBeInTheDocument();
  });

  it("blocks submit when the email is invalid (no network call)", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/password-reset/request/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();

    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox", { name: /email/i }),
      "not-an-email",
    );
    await user.click(screen.getByRole("button", { name: "auth.forgot_password.submit" }));

    expect(
      await screen.findByText("auth.login_card.please_enter_valid_email"),
    ).toBeInTheDocument();
    expect(serverHit).toBe(false);
  });

  it("renders a 'Back to sign in' link pointing at /login", () => {
    renderPage();
    const link = screen.getByRole("link", { name: "auth.forgot_password.back_to_login" });
    expect(link).toHaveAttribute("href", "/login");
  });
});
