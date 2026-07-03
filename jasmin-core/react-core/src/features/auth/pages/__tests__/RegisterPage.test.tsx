/**
 * Tier-4 integration smoke for the public ``RegisterPage`` (membership
 * application form).
 *
 * What this test owns:
 *
 *   1. Mount + structure — the page renders the required fields, the
 *      "Submit application" button, and a link back to ``/login``.
 *   2. Validation seam — invalid email, password too short, password
 *      mismatch, and missing required fields all block the submit and
 *      prevent any /api/auth/register/ call.
 *   3. Happy-path submit — POSTs to ``/api/auth/register/`` with the
 *      first_name/last_name/email/password fields (and any optional
 *      values), strips ``password_confirm`` from the payload, surfaces
 *      the success alert, and navigates to ``/login`` after the 2.5s
 *      delay.
 *   4. Server error — a 4xx response surfaces the canonical Jasmin
 *      ``message`` via ``getErrorMessage`` and keeps the form mounted.
 *
 * Notes:
 * - We mock ``useNavigate`` so we can assert the post-success redirect
 *   without setting up a routed test tree.
 * - The 2.5s ``setTimeout`` is driven via ``vi.useFakeTimers`` to keep
 *   the test deterministic.
 * - AntD ``Form.Item`` with a ``name`` wires the label to the input, so
 *   ``getByLabelText`` works for these inputs.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { server } from "@/test/msw/server";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

// Resolve keys against the real de bundle so assertions verify the actual
// German UI (the page uses bare `t("auth.apply.*")` with no inline fallbacks).
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

import RegisterPage from "../RegisterPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>,
  );
}

async function fillRequiredFields(
  user: ReturnType<typeof userEvent.setup>,
  overrides: Partial<{
    first_name: string;
    last_name: string;
    email: string;
    password: string;
    password_confirm: string;
  }> = {},
) {
  const v = {
    first_name: "Alice",
    last_name: "Anderson",
    email: "alice@example.com",
    password: "supersecret-pw",
    password_confirm: "supersecret-pw",
    ...overrides,
  };
  await user.type(screen.getByLabelText("Vorname"), v.first_name);
  await user.type(screen.getByLabelText("Nachname"), v.last_name);
  await user.type(screen.getByLabelText("E-Mail"), v.email);
  await user.type(screen.getByLabelText("Passwort"), v.password);
  await user.type(
    screen.getByLabelText("Passwort bestätigen"),
    v.password_confirm,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Mount ───────────────────────────────────────────────────────────────────

describe("RegisterPage mount", () => {
  it("renders the heading, required fields, the submit button and a 'Sign in' link", () => {
    renderPage();
    expect(screen.getByText("Mitgliedschaft beantragen")).toBeInTheDocument();
    expect(screen.getByLabelText("Vorname")).toBeInTheDocument();
    expect(screen.getByLabelText("Nachname")).toBeInTheDocument();
    expect(screen.getByLabelText("E-Mail")).toBeInTheDocument();
    expect(screen.getByLabelText("Passwort")).toBeInTheDocument();
    expect(screen.getByLabelText("Passwort bestätigen")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Antrag absenden" }),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Anmelden" });
    expect(link).toHaveAttribute("href", "/login");
  });
});

// ── Client-side validation ──────────────────────────────────────────────────

describe("RegisterPage validation", () => {
  it("blocks submit when the email is invalid (no network call)", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/register/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();
    const user = userEvent.setup();
    await fillRequiredFields(user, { email: "not-an-email" });
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    expect(await screen.findByText("Ungültige E-Mail-Adresse")).toBeInTheDocument();
    expect(serverHit).toBe(false);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("blocks submit when the password is shorter than 10 chars", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/register/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();
    const user = userEvent.setup();
    await fillRequiredFields(user, {
      password: "short",
      password_confirm: "short",
    });
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    expect(
      await screen.findByText("Mindestens 10 Zeichen."),
    ).toBeInTheDocument();
    expect(serverHit).toBe(false);
  });

  it("blocks submit when password and password_confirm don't match", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/register/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();
    const user = userEvent.setup();
    await fillRequiredFields(user, {
      password: "supersecret-pw",
      password_confirm: "supersecret-different",
    });
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    expect(
      await screen.findByText("Passwörter stimmen nicht überein."),
    ).toBeInTheDocument();
    expect(serverHit).toBe(false);
  });

  it("blocks submit and surfaces 'Required' for empty required fields", async () => {
    let serverHit = false;
    server.use(
      http.post("/api/auth/register/", () => {
        serverHit = true;
        return HttpResponse.json({ detail: "ok" });
      }),
    );

    renderPage();
    const user = userEvent.setup();
    // Click submit with the whole form empty.
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    // First name + last name share the "Required" message — getAllByText
    // proves at least one inline error is shown, which means the AntD
    // form validator ran and short-circuited the submit.
    expect((await screen.findAllByText("Erforderlich")).length).toBeGreaterThan(0);
    expect(serverHit).toBe(false);
  });
});

// ── Happy path ──────────────────────────────────────────────────────────────

describe("RegisterPage submit", () => {
  it("POSTs to /api/auth/register/ without password_confirm, shows the success alert, then navigates to /login after the delay", async () => {
    let received:
      | (Record<string, unknown> & { password_confirm?: unknown })
      | null = null;
    server.use(
      http.post("/api/auth/register/", async ({ request }) => {
        received = (await request.json()) as typeof received;
        return HttpResponse.json({ id: "u-new" });
      }),
    );

    // Drive the 2.5s setTimeout deterministically.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage();

    const user = userEvent.setup({
      advanceTimers: vi.advanceTimersByTime.bind(vi),
    });
    await fillRequiredFields(user);
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    // Wait for the request to land.
    await waitFor(() => expect(received).not.toBeNull());

    expect(received).toMatchObject({
      first_name: "Alice",
      last_name: "Anderson",
      email: "alice@example.com",
      password: "supersecret-pw",
    });
    // password_confirm must NOT be in the payload — the page destructures
    // it out before calling authRegisterCreate.
    expect(received).not.toHaveProperty("password_confirm");

    // The success alert replaces the form.
    expect(
      await screen.findByText(
        "Danke! Dein Antrag ist eingegangen.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Antrag absenden" }),
    ).not.toBeInTheDocument();

    // navigate("/login") fires after a 2.5s setTimeout.
    expect(navigateMock).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2600);
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/login"),
    );
  });

  it("surfaces the server's error message on a 400 and keeps the form mounted", async () => {
    server.use(
      http.post("/api/auth/register/", () =>
        HttpResponse.json(
          {
            code: "register.email_taken",
            message: "An account with this email already exists.",
          },
          { status: 400 },
        ),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await fillRequiredFields(user, { email: "taken@example.com" });
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    expect(
      await screen.findByText(
        "An account with this email already exists.",
      ),
    ).toBeInTheDocument();
    // Form must stay mounted so the user can retry — success alert MUST NOT render.
    expect(
      screen.getByRole("button", { name: "Antrag absenden" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Danke! Dein Antrag ist eingegangen."),
    ).not.toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("surfaces an error alert and keeps the form mounted on a 500 with no payload", async () => {
    // ``getErrorMessage`` short-circuits on ``axiosErr.message`` BEFORE
    // hitting our caller-supplied fallback, so the canned
    // "Could not complete your registration. Please try again." string
    // is effectively dead code while axios's "Request failed with status
    // code 500" is non-empty. We verify the surfaced behaviour instead:
    // the AntD error alert shows axios's message, the form stays mounted
    // for retry, and no navigation happens.
    server.use(
      http.post("/api/auth/register/", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await fillRequiredFields(user);
    await user.click(
      screen.getByRole("button", { name: "Antrag absenden" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").toMatch(/500/);
    expect(
      screen.getByRole("button", { name: "Antrag absenden" }),
    ).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
