/**
 * A reload with a live refresh cookie but no stored user metadata — another
 * tab dropped it — lands in the app. The refresh answer carries the user, so
 * JasminApp has roles to route on instead of rendering an empty redirect.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { LoginUser } from "@shared/api/generated/models";
import { setAccessToken } from "@shared/services/tokenStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The user the tenant realm's refresh answer carries; set per test.
const refreshed = vi.hoisted(() => ({ user: null as LoginUser | null }));
vi.mock("@shared/services/api", () => ({
  default: { post: vi.fn() },
  performRefresh: async () => {
    setAccessToken("fresh-access");
    return { access: "fresh-access", user: refreshed.user ?? undefined };
  },
}));

vi.mock("@shared/contexts/LocaleContext", () => ({
  useLocale: () => ({ language: "de", theme: "light" }),
}));
vi.mock("@hooks/index", () => ({
  useTheme: () => ({}),
  useErrorDateFormat: () => undefined,
}));
vi.mock("@shared/i18n", () => ({
  default: { t: (key: string) => key },
  activateLanguage: vi.fn(),
}));

vi.mock("@features/auth/pages/LoginPage", () => ({
  default: () => <p>login page</p>,
}));
vi.mock("@features/members/pages/MemberDetail", () => ({
  default: () => <p>member page</p>,
}));
vi.mock("@features/customer/pages/CustomerOrderPage", () => ({
  default: () => <p>customer order page</p>,
}));
vi.mock("@shared/layout/UserMenu", () => ({ default: () => null }));
// The office layout's shell.
vi.mock("@shared/layout/MainContent", () => ({
  default: () => <p>office pages</p>,
}));
vi.mock("@shared/layout/TopNavigation", () => ({ default: () => null }));
vi.mock("@shared/layout/DynamicSidebar", () => ({ default: () => null }));
vi.mock("@shared/layout/Footer", () => ({ default: () => null }));
vi.mock("@shared/layout/SkipToMainLink", () => ({ default: () => null }));
vi.mock("@shared/contexts/NavigationContext", () => ({
  NavigationProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));
vi.mock("@shared/contexts/ModalContext", () => ({
  ModalProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

import { AuthProvider } from "@shared/contexts/AuthContext";
import JasminApp from "../JasminApp";

function user(roles: string[], ids: Partial<LoginUser> = {}): LoginUser {
  return {
    id: "u-9",
    email: "someone@example.com",
    first_name: "Sam",
    last_name: "Someone",
    user_language: "de",
    theme: "light",
    roles,
    member_id: null,
    reseller_id: null,
    ...ids,
  };
}

function reload() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider>
        <JasminApp />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("JasminApp after a reload whose stored user is gone", () => {
  it.each([
    ["a member", user(["member"], { member_id: "m-9" }), "member page"],
    [
      "a customer",
      user(["customer"], { reseller_id: "r-9" }),
      "customer order page",
    ],
    ["an office user", user(["office"]), "office pages"],
  ])("lands %s in the app", async (_who, signedIn, page) => {
    refreshed.user = signedIn;
    expect(localStorage.getItem("auth")).toBeNull();

    reload();

    expect(await screen.findByText(page)).toBeInTheDocument();
    expect(screen.queryByText("login page")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("auth") ?? "{}").user).toEqual(
      signedIn,
    );
  });
});
