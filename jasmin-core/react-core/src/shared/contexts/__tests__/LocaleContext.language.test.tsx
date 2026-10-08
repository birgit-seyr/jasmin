/**
 * Which language the app speaks: the signed-in user's saved language, else
 * the one picked with a switcher in this browser, else the browser's own when
 * the app offers it, else the farm's, else German. dayjs dates in the language
 * decided last.
 */
import { act, render } from "@testing-library/react";
import dayjs from "dayjs";
import type { Context } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { flushMicrotasks } from "@/test/profileRenders";

const { authPartialUpdate, notify } = vi.hoisted(() => ({
  authPartialUpdate: vi.fn(() => Promise.resolve({})),
  notify: { error: vi.fn(), success: vi.fn() },
}));

/** Holds dayjs's German locale back until a test lets it arrive, the way its
 * chunk lands only after a network fetch. */
const germanDayjsLocale = vi.hoisted(() => {
  let arrive = () => {};
  const arrived = new Promise<void>((resolve) => {
    arrive = resolve;
  });
  return { arrived, arrive: () => arrive() };
});
vi.mock("dayjs/locale/de", async () => {
  await germanDayjsLocale.arrived;
  return vi.importActual("dayjs/locale/de");
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const auth: { user: { id: string; user_language?: string } | null } = {
  user: null,
};
const updateUser = vi.fn();
vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user: auth.user, updateUser }),
}));
vi.mock("../TenantContext", async () => {
  const { createContext } = await import("react");
  return { TenantContext: createContext(undefined) };
});
vi.mock("@shared/api/generated/auth/auth", () => ({ authPartialUpdate }));
vi.mock("@shared/utils/notify", () => ({ default: notify }));

import { TenantContext } from "../TenantContext";
import { LocaleProvider, useLocale } from "../LocaleContext";

/** The one tenant field LocaleProvider reads. */
const TenantLanguageContext = TenantContext as unknown as Context<
  { tenant: { tenant_language: string | null } } | undefined
>;

let probed: ReturnType<typeof useLocale> | null = null;
function Probe() {
  probed = useLocale();
  return null;
}

/** A browser whose preferred languages are ``tags``, most preferred first. */
function browserPrefers(...tags: string[]) {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(tags);
  vi.spyOn(navigator, "language", "get").mockReturnValue(tags[0] ?? "");
}

/**
 * Mount the provider under a farm whose ``tenant_language`` is given, or
 * before the tenant has loaded when it is left out. ``tenantLoads`` delivers
 * the farm's language later, as the anonymous tenant fetch does;
 * ``userLoads`` delivers the signed-in user later, as AuthProvider does when
 * it reads the stored session after the first render.
 */
function renderProvider(tenantLanguage?: string) {
  const tree = (language?: string) => (
    <TenantLanguageContext.Provider
      value={
        language === undefined
          ? undefined
          : { tenant: { tenant_language: language } }
      }
    >
      <LocaleProvider>
        <Probe />
      </LocaleProvider>
    </TenantLanguageContext.Provider>
  );
  const view = render(tree(tenantLanguage));
  return {
    ...view,
    tenantLoads: (language: string) => view.rerender(tree(language)),
    userLoads: (user: NonNullable<typeof auth.user>) => {
      auth.user = user;
      view.rerender(tree(tenantLanguage));
    },
  };
}

const storedPick = () => localStorage.getItem("language");

describe("LocaleProvider language", () => {
  beforeEach(() => {
    localStorage.clear();
    auth.user = null;
    probed = null;
    authPartialUpdate.mockClear();
    updateUser.mockClear();
    notify.error.mockClear();
  });

  describe("signed out", () => {
    it("speaks the browser's language over the farm's", () => {
      browserPrefers("en-US", "en");
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });

    it("counts a regional browser tag as its base language", () => {
      browserPrefers("de-AT");
      renderProvider("en");

      expect(probed?.language).toBe("de");
    });

    it("takes the first of the browser's languages that the app offers", () => {
      browserPrefers("fr-FR", "en-GB", "de-DE");
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });

    it("falls back to navigator.language when the browser lists none", () => {
      vi.spyOn(navigator, "languages", "get").mockReturnValue([]);
      vi.spyOn(navigator, "language", "get").mockReturnValue("en-GB");
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });

    it("speaks German until the farm's language arrives for a browser in a language the app doesn't offer", () => {
      browserPrefers("fr-FR", "fr");
      const { tenantLoads } = renderProvider();

      expect(probed?.language).toBe("de");

      tenantLoads("en");

      expect(probed?.language).toBe("en");
    });

    it("keeps a language picked in this browser over the browser's, also once the farm's arrives", () => {
      localStorage.setItem("language", "de");
      browserPrefers("en-US", "en");
      const { tenantLoads } = renderProvider();

      expect(probed?.language).toBe("de");

      tenantLoads("en");

      expect(probed?.language).toBe("de");
    });

    it.each(["fr", "xx", "de-DE"])(
      "ignores a stored pick of %s, which the app doesn't offer",
      (stored) => {
        localStorage.setItem("language", stored);
        browserPrefers("en-US");
        renderProvider("de");

        expect(probed?.language).toBe("en");
      },
    );

    it("keeps only a pick in this browser, never the language it worked out", () => {
      browserPrefers("en-US");
      renderProvider("de");

      expect(probed?.language).toBe("en");
      expect(storedPick()).toBeNull();
    });

    it("switches on a pick and keeps it for the next visit", async () => {
      browserPrefers("de-DE");
      const { unmount } = renderProvider("de");
      expect(probed?.language).toBe("de");

      await act(() => probed!.saveLanguage("en"));

      expect(probed?.language).toBe("en");
      expect(storedPick()).toBe("en");
      expect(authPartialUpdate).not.toHaveBeenCalled();

      unmount();
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });
  });

  describe("signed in", () => {
    it("speaks the user's saved language over a pick, the browser's and the farm's", () => {
      auth.user = { id: "u1", user_language: "en" };
      localStorage.setItem("language", "de");
      browserPrefers("de-DE");
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });

    it("follows the pick in this browser for a user without a saved language", () => {
      auth.user = { id: "u1" };
      localStorage.setItem("language", "en");
      browserPrefers("de-DE");
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });

    it("follows the browser for a user with neither a saved language nor a pick", () => {
      auth.user = { id: "u1" };
      browserPrefers("en-US");
      renderProvider("de");

      expect(probed?.language).toBe("en");
    });

    it("keeps dayjs on the user's language when the locale worked out before sign-in loads after it", async () => {
      // Signed out, a browser in a language the app doesn't offer lands on
      // German, whose dayjs locale has to be fetched; the stored session's
      // user, read a moment later, speaks English, which dayjs has built in.
      browserPrefers("nl-NL", "nl");
      const { userLoads } = renderProvider();
      expect(probed?.language).toBe("de");

      userLoads({ id: "u1", user_language: "en" });
      expect(probed?.language).toBe("en");

      await act(async () => {
        germanDayjsLocale.arrive();
        await flushMicrotasks();
      });

      expect(dayjs.locale()).toBe("en");
    });

    it("saves a pick to the profile, the signed-in user and this browser", async () => {
      auth.user = { id: "u1", user_language: "de" };
      renderProvider("de");
      expect(probed?.language).toBe("de");

      await act(() => probed!.saveLanguage("en"));

      expect(authPartialUpdate).toHaveBeenCalledWith("u1", {
        user_language: "en",
      });
      expect(probed?.language).toBe("en");
      expect(storedPick()).toBe("en");
      // A later profile save writes the signed-in user back whole, so it must
      // carry the pick, or the language flips back.
      expect(updateUser).toHaveBeenCalledWith({ user_language: "en" });
    });

    it("keeps a language the profile can't store off the signed-in user", async () => {
      auth.user = { id: "u1", user_language: "de" };
      renderProvider("de");

      await act(() => probed!.saveLanguage("xx"));

      expect(authPartialUpdate).not.toHaveBeenCalled();
      expect(updateUser).not.toHaveBeenCalled();
      expect(probed?.language).toBe("xx");
    });

    it("tells the user the server's reason when a pick can't be saved and keeps the language", async () => {
      auth.user = { id: "u1", user_language: "de" };
      renderProvider("de");
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      const refusal = {
        isAxiosError: true,
        response: { status: 400, data: { message: "Language not allowed" } },
      };
      authPartialUpdate.mockRejectedValueOnce(refusal);

      await act(() =>
        expect(probed!.saveLanguage("en")).rejects.toBe(refusal),
      );

      expect(notify.error).toHaveBeenCalledWith("Language not allowed");
      expect(probed?.error).toBe("Language not allowed");
      expect(probed?.language).toBe("de");
      expect(updateUser).not.toHaveBeenCalled();
      expect(consoleError).not.toHaveBeenCalled();
      consoleError.mockRestore();
    });

    it("tells the user in their language when the server gives no reason", async () => {
      auth.user = { id: "u1", user_language: "de" };
      renderProvider("de");
      authPartialUpdate.mockRejectedValueOnce(new Error("Network Error"));

      await act(() =>
        expect(probed!.saveLanguage("en")).rejects.toThrow("Network Error"),
      );

      expect(notify.error).toHaveBeenCalledWith(
        "profile.preferences_save_error",
      );
      expect(probed?.error).toBe("profile.preferences_save_error");
    });
  });
});
