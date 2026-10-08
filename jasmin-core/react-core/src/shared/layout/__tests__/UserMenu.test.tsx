/**
 * UserMenu: picking a language or a theme. LocaleContext shows a failed save
 * to the user and rethrows, so the menu must take up the rejection rather than
 * leave it unhandled, which Vitest reports as an error of the run. The locale
 * context is the mocking boundary.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Plain functions, not ``vi.fn``: a mock subscribes to the promise it
// returns, which would take up the very rejection under test.
const { saves } = vi.hoisted(() => ({ saves: [] as string[] }));
const refuse = (picked: string) => {
  saves.push(picked);
  return Promise.reject(new Error("Network Error"));
};

vi.mock("@shared/contexts/LocaleContext", () => ({
  useLocale: () => ({
    language: "de",
    saveLanguage: refuse,
    themePreference: "system",
    saveThemePreference: refuse,
  }),
}));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "u1", first_name: "Ada", email: "ada@example.com" },
    isAuthenticated: true,
    logout: vi.fn(),
  }),
}));
vi.mock("@shared/auth/useRoles", () => ({
  useRoles: () => ({ hasMemberRole: false, isStaff: true, isMemberOnly: false }),
}));
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningMembersRetrieve: () => ({ data: undefined }),
}));
vi.mock("@hooks/index", () => ({ useIsMobile: () => false }));
vi.mock("../UserProfileModal", () => ({ default: () => null }));

import UserMenu from "../UserMenu";

beforeEach(() => {
  saves.length = 0;
});

async function pick(submenu: string, item: string) {
  render(
    <MemoryRouter>
      <UserMenu />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "profile.menu_aria" }));
  fireEvent.mouseEnter(await screen.findByText(submenu));
  await userEvent.click(await screen.findByText(item));
}

describe("UserMenu preferences", () => {
  it("catches a language save the context refused", async () => {
    await pick("profile.menu_language", "English");

    await waitFor(() => expect(saves).toEqual(["en"]));
  });

  it("catches a theme save the context refused", async () => {
    await pick("profile.menu_theme", "profile.theme_dark");

    await waitFor(() => expect(saves).toEqual(["dark"]));
  });
});
