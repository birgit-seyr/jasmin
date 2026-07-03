import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { server } from "@/test/msw/server";

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

// Resolve keys against the real de bundle so assertions verify the actual
// German UI (the page uses bare `t("auth.set_password.*")` with no inline
// fallbacks). Interpolation (`{{tenant}}`) is applied from the opts arg.
vi.mock("react-i18next", async () => {
  const deAuth = (await import("@shared/i18n/locales/de/auth.json")).default;
  const bundles: Record<string, unknown> = { auth: deAuth };
  const t = (key: string, opts?: unknown) => {
    let cur: unknown = bundles;
    for (const part of key.split(".")) {
      cur = (cur as Record<string, unknown> | undefined)?.[part];
    }
    let str = typeof cur === "string" ? cur : key;
    if (opts && typeof opts === "object") {
      for (const [k, v] of Object.entries(opts as Record<string, unknown>)) {
        str = str.replace(new RegExp(`{{\\s*${k}\\s*}}`, "g"), String(v));
      }
    }
    return str;
  };
  return {
    useTranslation: () => ({
      t,
      i18n: { language: "de", changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    initReactI18next: { type: "3rdParty", init: () => {} },
  };
});

import SetPasswordPage from "../SetPasswordPage";

const TOKEN = "invite-token-123";

const validInvitation = {
  email: "newhire@example.com",
  first_name: "Alice",
  tenant_name: "Marillen Acres",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/invite/${TOKEN}`]}>
      <Routes>
        <Route path="/invite/:token" element={<SetPasswordPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  vi.useRealTimers();
});

describe("SetPasswordPage (integration)", () => {
  it("loads the invitation, prefills email + greets by first name, then submits and navigates to /login", async () => {
    let acceptBody: { token?: string; password?: string } | null = null;
    server.use(
      http.get(`/api/auth/invitations/${TOKEN}/`, () =>
        HttpResponse.json(validInvitation),
      ),
      http.post("/api/auth/invitations/accept/", async ({ request }) => {
        acceptBody = (await request.json()) as typeof acceptBody;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();

    expect(await screen.findByText("Willkommen, Alice!")).toBeInTheDocument();
    expect(
      screen.getByText("Du wurdest zu Marillen Acres eingeladen"),
    ).toBeInTheDocument();
    // Email is prefilled and disabled. The Form.Item has no `name`, so we
    // identify the input by its display value rather than label association.
    const emailInput = screen.getByDisplayValue(
      "newhire@example.com",
    ) as HTMLInputElement;
    expect(emailInput).toBeDisabled();

    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });
    await user.type(
      screen.getByLabelText("Passwort wählen"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("Passwort bestätigen"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", { name: "Passwort setzen und fortfahren" }),
    );

    expect(
      await screen.findByText("Passwort gesetzt! Du wirst zur Anmeldung weitergeleitet…"),
    ).toBeInTheDocument();
    expect(acceptBody).toEqual({
      token: TOKEN,
      password: "S3cret-passphrase!",
    });

    vi.advanceTimersByTime(2000);
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/login"));
  });

  it("cancels the pending /login redirect if it unmounts before the delay elapses", async () => {
    server.use(
      http.get(`/api/auth/invitations/${TOKEN}/`, () =>
        HttpResponse.json(validInvitation),
      ),
      http.post("/api/auth/invitations/accept/", () =>
        HttpResponse.json({ detail: "ok" }),
      ),
    );

    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = renderPage();

    await screen.findByText("Willkommen, Alice!");

    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });
    await user.type(
      screen.getByLabelText("Passwort wählen"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("Passwort bestätigen"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", { name: "Passwort setzen und fortfahren" }),
    );

    expect(
      await screen.findByText(
        "Passwort gesetzt! Du wirst zur Anmeldung weitergeleitet…",
      ),
    ).toBeInTheDocument();

    // Leave the page within the 1.8s window — the effect cleanup must clear
    // the timer so navigate() never fires after unmount.
    unmount();
    vi.advanceTimersByTime(5000);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("shows the invalid-link error and HIDES the form when the preflight invitation lookup fails", async () => {
    server.use(
      http.get(`/api/auth/invitations/${TOKEN}/`, () =>
        HttpResponse.json({ detail: "not found" }, { status: 404 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(
        "Dieser Einladungslink ist ungültig oder abgelaufen. Bitte fordere bei einem Administrator einen neuen an.",
      ),
    ).toBeInTheDocument();
    // No password form rendered when info is null.
    expect(
      screen.queryByLabelText("Passwort wählen"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Passwort setzen und fortfahren" }),
    ).not.toBeInTheDocument();
  });

  it("surfaces the canonical server error when accept fails (e.g. weak password)", async () => {
    server.use(
      http.get(`/api/auth/invitations/${TOKEN}/`, () =>
        HttpResponse.json(validInvitation),
      ),
      http.post("/api/auth/invitations/accept/", () =>
        HttpResponse.json(
          {
            code: "weak_password",
            message: "Password is too common.",
            field: "password",
          },
          { status: 400 },
        ),
      ),
    );

    renderPage();
    await screen.findByText("Willkommen, Alice!");

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Passwort wählen"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("Passwort bestätigen"),
      "S3cret-passphrase!",
    );
    await user.click(
      screen.getByRole("button", { name: "Passwort setzen und fortfahren" }),
    );

    expect(
      await screen.findByText("Password is too common."),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
    // Form remains so the user can fix and retry.
    expect(
      screen.getByRole("button", { name: "Passwort setzen und fortfahren" }),
    ).toBeInTheDocument();
  });

  it("blocks submit when the two passwords don't match (no accept call)", async () => {
    let acceptHit = false;
    server.use(
      http.get(`/api/auth/invitations/${TOKEN}/`, () =>
        HttpResponse.json(validInvitation),
      ),
      http.post("/api/auth/invitations/accept/", () => {
        acceptHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();
    await screen.findByText("Willkommen, Alice!");

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Passwort wählen"),
      "S3cret-passphrase!",
    );
    await user.type(
      screen.getByLabelText("Passwort bestätigen"),
      "different-passphrase!",
    );
    await user.click(
      screen.getByRole("button", { name: "Passwort setzen und fortfahren" }),
    );

    expect(
      await screen.findByText("Passwörter stimmen nicht überein."),
    ).toBeInTheDocument();
    expect(acceptHit).toBe(false);
  });

  it("renders a 'Back to sign in' link to /login even on the error branch", async () => {
    server.use(
      http.get(`/api/auth/invitations/${TOKEN}/`, () =>
        HttpResponse.json({ detail: "gone" }, { status: 410 }),
      ),
    );
    renderPage();
    await screen.findByText(
      "Dieser Einladungslink ist ungültig oder abgelaufen. Bitte fordere bei einem Administrator einen neuen an.",
    );
    const link = screen.getByRole("link", { name: "Zurück zur Anmeldung" });
    expect(link).toHaveAttribute("href", "/login");
  });
});
