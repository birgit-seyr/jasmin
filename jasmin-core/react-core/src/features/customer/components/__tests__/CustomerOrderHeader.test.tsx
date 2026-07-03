/**
 * Tier-4 seam test for ``CustomerOrderHeader``.
 *
 * The header is pure-presentational and the source has a few small
 * branching shapes worth pinning:
 *   - title falls back to first/last name when ``company_name`` is empty
 *   - email / phone lines only render when present
 *   - logo shape (``circle`` vs ``rectangle-wide`` vs ``rectangle-tall``)
 *     drives a different DOM tree + dimensions
 *   - the two buttons fire their callbacks
 *
 * We control ``useLogoShape`` per test by tweaking the hook mock at call
 * time so each test can pick its own shape.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Reseller } from "@shared/api/generated/models";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// useLogoShape is reassigned per-test via this mutable cell so each
// case can pick its own shape + aspect ratio.
const logoShapeState: {
  logoShape: "circle" | "square" | "rectangle-wide" | "rectangle-tall";
  logoAspectRatio: number;
} = { logoShape: "circle", logoAspectRatio: 1 };

vi.mock("@hooks/index", () => ({
  useLogoShape: () => logoShapeState,
  // CustomerOrderHeader reads tenantName for the logo's alt text (a11y).
  useTenant: () => ({ tenantName: "Test Tenant" }),
}));

// CustomerOrderHeader pulls JasminUser fields off ``useAuth`` as a fallback
// when the linked ContactEntity is empty. The stub returns a deterministic
// user so the title/email fallback branches are exercised explicitly per
// test rather than relying on real auth state.
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: {
      first_name: "Userfn",
      last_name: "Userln",
      email: "user@example.test",
    },
  }),
}));

import CustomerOrderHeader from "../CustomerOrderHeader";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeReseller(overrides: Partial<Reseller> = {}): Reseller {
  return {
    id: "reseller-1",
    company_name: "Acme Co",
    first_name: "Alice",
    last_name: "Acres",
    email: "alice@acme.test",
    phone: "+49 555 1234",
    ...overrides,
  } as Reseller;
}

function makeProps(
  overrides: Partial<Parameters<typeof CustomerOrderHeader>[0]> = {},
) {
  return {
    reseller: makeReseller(),
    logoUrl: "https://example.test/logo.png",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // reset shape state to a sane default
  logoShapeState.logoShape = "circle";
  logoShapeState.logoAspectRatio = 1;
});

// ── Title fallback ──────────────────────────────────────────────────────────

describe("title", () => {
  it("uses company_name when present", () => {
    render(<CustomerOrderHeader {...makeProps()} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Acme Co" }),
    ).toBeInTheDocument();
  });

  it("falls back to 'first_name last_name' when company_name is empty", () => {
    const props = makeProps({
      reseller: makeReseller({ company_name: "" }),
    });
    render(<CustomerOrderHeader {...props} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Alice Acres" }),
    ).toBeInTheDocument();
  });

  it("falls back to JasminUser first/last name when reseller name parts are empty", () => {
    // No reseller-side name info at all — the header reaches into
    // ``useAuth`` and renders the user's display name instead.
    const props = makeProps({
      reseller: makeReseller({
        company_name: "",
        first_name: "",
        last_name: "",
      }),
    });
    render(<CustomerOrderHeader {...props} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Userfn Userln" }),
    ).toBeInTheDocument();
  });
});

// ── Contact line ────────────────────────────────────────────────────────────

describe("contact line", () => {
  it("shows email when reseller.email is set", () => {
    render(<CustomerOrderHeader {...makeProps()} />);
    expect(screen.getByText("alice@acme.test")).toBeInTheDocument();
  });

  it("shows phone when reseller.phone is set", () => {
    render(<CustomerOrderHeader {...makeProps()} />);
    expect(screen.getByText("+49 555 1234")).toBeInTheDocument();
  });

  it("falls back to the JasminUser email when reseller.email is empty", () => {
    const props = makeProps({ reseller: makeReseller({ email: "" }) });
    render(<CustomerOrderHeader {...props} />);
    expect(screen.queryByText("alice@acme.test")).not.toBeInTheDocument();
    expect(screen.getByText("user@example.test")).toBeInTheDocument();
  });

  it("hides the phone line when reseller.phone is empty", () => {
    const props = makeProps({ reseller: makeReseller({ phone: "" }) });
    render(<CustomerOrderHeader {...props} />);
    expect(screen.queryByText("+49 555 1234")).not.toBeInTheDocument();
  });
});

// ── Removed affordances ─────────────────────────────────────────────────────
//
// Both the inline "Edit profile" button and the inline "Logout" button used
// to live on this header. They have since been consolidated into the
// top-right ``UserMenu`` (apps/react-core/src/components/layout/UserMenu.tsx)
// so account-level affordances are consistent with the rest of the app.

describe("no inline account affordances", () => {
  it("does NOT render an inline Edit button", () => {
    render(<CustomerOrderHeader {...makeProps()} />);
    expect(
      screen.queryByRole("button", { name: /customer\.edit_profile/ }),
    ).not.toBeInTheDocument();
  });

  it("does NOT render an inline Logout button", () => {
    render(<CustomerOrderHeader {...makeProps()} />);
    expect(
      screen.queryByRole("button", { name: /common\.logout/ }),
    ).not.toBeInTheDocument();
  });
});

// ── Logo shape branches ─────────────────────────────────────────────────────

describe("logo rendering by shape", () => {
  it("renders an AntD Avatar (circle) when logoShape is circle", () => {
    logoShapeState.logoShape = "circle";
    render(<CustomerOrderHeader {...makeProps()} />);
    // AntD Avatar has a stable .ant-avatar class
    const logo = screen.getByAltText("Test Tenant");
    expect(logo.closest(".ant-avatar")).not.toBeNull();
  });

  it("renders a constrained rectangle when logoShape is rectangle-wide (width = SIZE * ratio)", () => {
    logoShapeState.logoShape = "rectangle-wide";
    logoShapeState.logoAspectRatio = 2;
    render(<CustomerOrderHeader {...makeProps()} />);

    const img = screen.getByAltText("Test Tenant");
    expect(img.tagName).toBe("IMG");
    // LOGO_SIZE = 120 in the source; ratio 2 → width 240px, height 120px.
    const box = img.parentElement!;
    expect(box.style.width).toBe("240px");
    expect(box.style.height).toBe("120px");
  });

  it("renders a constrained rectangle when logoShape is rectangle-tall (height = SIZE / ratio)", () => {
    logoShapeState.logoShape = "rectangle-tall";
    logoShapeState.logoAspectRatio = 0.5;
    render(<CustomerOrderHeader {...makeProps()} />);

    const img = screen.getByAltText("Test Tenant");
    expect(img.tagName).toBe("IMG");
    // height = 120 / 0.5 = 240, width = 120.
    const box = img.parentElement!;
    expect(box.style.width).toBe("120px");
    expect(box.style.height).toBe("240px");
  });
});
