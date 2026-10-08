import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { authPartialUpdate } = vi.hoisted(() => ({
  authPartialUpdate: vi.fn(() => Promise.resolve({})),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const auth: { user: { id: string; theme?: string } | null } = { user: null };
const updateUser = vi.fn();
vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user: auth.user, updateUser }),
}));
vi.mock("../TenantContext", async () => {
  const { createContext } = await import("react");
  return { TenantContext: createContext(undefined) };
});
vi.mock("@shared/api/generated/auth/auth", () => ({ authPartialUpdate }));

import { LocaleProvider, useLocale } from "../LocaleContext";

let probed: ReturnType<typeof useLocale> | null = null;
function Probe() {
  probed = useLocale();
  return null;
}

const realMatchMedia = window.matchMedia;

/** A device set to dark or light that can be switched while the app runs. */
function fakeDevice(dark: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const media = {
    matches: dark,
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_type: string, listener: (e: MediaQueryListEvent) => void) =>
      listeners.add(listener),
    removeEventListener: (
      _type: string,
      listener: (e: MediaQueryListEvent) => void,
    ) => listeners.delete(listener),
  };
  window.matchMedia = vi.fn(() => media as unknown as MediaQueryList);
  return {
    switchTo(darkNow: boolean) {
      media.matches = darkNow;
      listeners.forEach((listener) =>
        listener({ matches: darkNow } as MediaQueryListEvent),
      );
    },
  };
}

function renderProvider() {
  return render(
    <LocaleProvider>
      <Probe />
    </LocaleProvider>,
  );
}

const isDarkClassSet = () =>
  document.documentElement.classList.contains("dark");

describe("LocaleProvider theme", () => {
  beforeEach(() => {
    localStorage.clear();
    auth.user = null;
    probed = null;
    authPartialUpdate.mockClear();
    updateUser.mockClear();
  });

  afterEach(() => {
    window.matchMedia = realMatchMedia;
    document.documentElement.classList.remove("dark");
  });

  it("follows the device while nothing is chosen, also when it changes", async () => {
    const device = fakeDevice(true);
    renderProvider();

    await waitFor(() => expect(probed?.theme).toBe("dark"));
    expect(probed?.themePreference).toBe("system");
    expect(isDarkClassSet()).toBe(true);

    act(() => device.switchTo(false));

    await waitFor(() => expect(probed?.theme).toBe("light"));
    expect(isDarkClassSet()).toBe(false);
  });

  it("takes the signed-in user's choice over the device", async () => {
    fakeDevice(true);
    auth.user = { id: "u1", theme: "light" };
    renderProvider();

    await waitFor(() => expect(probed?.themePreference).toBe("light"));
    expect(probed?.theme).toBe("light");
    expect(isDarkClassSet()).toBe(false);
  });

  it("signed out, keeps the last choice made in this browser", async () => {
    fakeDevice(false);
    localStorage.setItem("theme", "dark");
    renderProvider();

    await waitFor(() => expect(probed?.theme).toBe("dark"));
  });

  it("saves a choice to the profile, the signed-in user and this browser", async () => {
    fakeDevice(false);
    auth.user = { id: "u1", theme: "system" };
    renderProvider();
    await waitFor(() => expect(probed?.themePreference).toBe("system"));

    await act(() => probed!.saveThemePreference("dark"));

    expect(authPartialUpdate).toHaveBeenCalledWith("u1", { theme: "dark" });
    expect(probed?.theme).toBe("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    // Through AuthContext, which also keeps the stored ``auth`` entry: a later
    // profile save writes the signed-in user back whole.
    expect(updateUser).toHaveBeenCalledWith({ theme: "dark" });
  });
});
