import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import { useAuth } from "./AuthContext";
import { TenantContext } from "./TenantContext";
import { authPartialUpdate } from "@shared/api/generated/auth/auth";
import {
  ThemeEnum,
  type UserLanguageEnum,
  type UserProfileUpdateRequest,
} from "@shared/api/generated/models";
import { isSupportedLanguageCode } from "@shared/i18n/languages";
import { notify } from "@shared/utils";
import { getServerErrorMessage } from "@shared/utils/apiError";

/**
 * Load a dayjs locale on demand. English is built into dayjs and
 * needs no import. Each ``await import("dayjs/locale/<lang>")`` is
 * a separate string literal so Vite can statically split each locale
 * into its own chunk — the user only downloads the locale they
 * actually use, instead of all 4 eagerly on every app boot.
 *
 * Silent fallback on unknown / unimportable language: dayjs.locale()
 * will use the built-in English without error if the named locale
 * isn't registered.
 */
async function loadDayjsLocale(language: string): Promise<void> {
  if (language === "en") return;
  try {
    switch (language) {
      case "de":
        await import("dayjs/locale/de");
        return;
      case "fr":
        await import("dayjs/locale/fr");
        return;
      case "it":
        await import("dayjs/locale/it");
        return;
      default:
        return;
    }
  } catch (err) {
    console.warn(`Failed to load dayjs locale "${language}":`, err);
  }
}

/** How many ``applyDayjsLocale`` calls have begun, so each can tell whether a
 * later one started while its locale was loading. */
let dayjsLocaleRequests = 0;

/** Activate the requested locale on dayjs once it's been (lazily)
 * registered. Synchronous call sites use this fire-and-forget; the
 * brief window between the call and the chunk arriving is invisible
 * in practice because most user-visible date rendering happens
 * after at least one paint.
 *
 * The latest call decides. Every locale but the built-in English is a fetch
 * away, so one requested earlier can land after one requested later — the
 * language worked out before the stored session is read, say, after the
 * signed-in user's — and must not take dayjs over then. */
function applyDayjsLocale(language: string): void {
  const request = ++dayjsLocaleRequests;
  loadDayjsLocale(language)
    .then(() => {
      if (request === dayjsLocaleRequests) dayjs.locale(language);
    })
    .catch((err) =>
      console.warn(`Failed to activate dayjs locale "${language}":`, err),
    );
}

interface UserPreferences {
  language?: string;
  theme?: ThemeEnum;
  sidebar_collapsed?: boolean;
}

interface LocaleContextValue {
  language: string;
  /** The theme in effect: the user's choice, or the device's under ``system``. */
  theme: "light" | "dark";
  /** What the user chose: light, dark, or ``system`` to follow the device. */
  themePreference: ThemeEnum;
  sidebarCollapsed: boolean;
  loading: boolean;
  error: string | null;
  saveLanguage: (newLanguage: string) => Promise<void>;
  saveThemePreference: (preference: ThemeEnum) => Promise<void>;
  saveSidebarCollapsed: (newSidebarCollapsed: boolean) => Promise<void>;
  savePreferences: (newPreferences: UserPreferences) => Promise<void>;
  setLanguage: (newLanguage: string) => void;
  setSidebarCollapsed: (newSidebarCollapsed: boolean) => void;
  toggleSidebar: () => void;
}

const LocaleContext = createContext<LocaleContextValue | undefined>(undefined);

const DEVICE_PREFERS_DARK = "(prefers-color-scheme: dark)";

function isThemePreference(value: unknown): value is ThemeEnum {
  return Object.values(ThemeEnum).includes(value as ThemeEnum);
}

/** The language last picked with a switcher in this browser, if the app still
 * offers it. */
function readLanguagePick(): UserLanguageEnum | null {
  try {
    const stored = localStorage.getItem("language");
    return isSupportedLanguageCode(stored) ? stored : null;
  } catch {
    return null;
  }
}

function storeLanguagePick(language: string): void {
  if (!isSupportedLanguageCode(language)) return;
  try {
    localStorage.setItem("language", language);
  } catch {
    // Without storage the pick holds until the page is reloaded.
  }
}

/** The first of the browser's preferred languages that the app offers, by its
 * base language (``de-AT`` counts as ``de``), or null when it offers none. */
function preferredBrowserLanguage(): UserLanguageEnum | null {
  for (const tag of [...(navigator.languages ?? []), navigator.language]) {
    const base = tag?.split("-")[0].toLowerCase();
    if (isSupportedLanguageCode(base)) return base;
  }
  return null;
}

/**
 * The language the app speaks — the first of:
 *   1. the signed-in user's saved ``user_language``;
 *   2. the language last picked with a switcher in this browser;
 *   3. the browser's own language, when the app offers it;
 *   4. the farm's ``tenant_language``;
 *   5. German, the in-house default and i18next's ``fallbackLng``.
 * Every page reads the same chain, signed in or not, so signing in changes the
 * language only for a user whose profile names another one.
 */
function resolveLanguage(
  userLanguage: string | undefined,
  tenantLanguage: string | null,
): string {
  return (
    userLanguage ||
    readLanguagePick() ||
    preferredBrowserLanguage() ||
    tenantLanguage ||
    "de"
  );
}

/** Whether the device is set to dark, following it when that changes. */
function useDeviceIsDark(): boolean {
  const [isDark, setIsDark] = useState(
    () => window.matchMedia(DEVICE_PREFERS_DARK).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(DEVICE_PREFERS_DARK);
    const follow = (event: MediaQueryListEvent) => setIsDark(event.matches);
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);
  return isDark;
}

/* eslint-disable-next-line react-refresh/only-export-components --
   the hook is the only way into the private context above */
export function useLocale() {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocale must be used within a LocaleProvider");
  }
  return context;
}

/**
 * Whether the dark theme is on, for code that picks a colour in JS rather than
 * through a CSS variable — a chart writes its series colours into SVG
 * attributes. Light outside a LocaleProvider.
 */
/* eslint-disable-next-line react-refresh/only-export-components --
   like useLocale, a way into the private context above */
export function useIsDarkTheme(): boolean {
  return useContext(LocaleContext)?.theme === "dark";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, updateUser } = useAuth();
  // Direct ``useContext`` instead of ``useTenant()`` because LocaleProvider
  // is also mounted on the platform (super-admin) domain where there is no
  // TenantProvider — ``useTenant()`` would throw.
  const tenantCtx = useContext(TenantContext);
  const tenantLanguage = tenantCtx?.tenant?.tenant_language ?? null;
  const [language, setLanguage] = useState(() =>
    resolveLanguage(user?.user_language, tenantLanguage),
  );
  const [themePreference, setThemePreference] = useState<ThemeEnum>(
    ThemeEnum.system,
  );
  const deviceIsDark = useDeviceIsDark();
  const theme =
    themePreference === ThemeEnum.system
      ? deviceIsDark
        ? "dark"
        : "light"
      : themePreference;
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The language follows the chain in ``resolveLanguage``: the signed-in
  // user's saved language, else the one picked in this browser, else the
  // browser's own when the app offers it, else the farm's, else German. It is
  // decided again when the user signs in or out, and when ``tenantLanguage``
  // arrives with the anonymous tenant fetch — which changes the language only
  // for a visitor who picked none and whose browser names none the app offers.
  useEffect(() => {
    const initialLanguage = resolveLanguage(user?.user_language, tenantLanguage);
    let initialSidebarCollapsed = false;

    // The signed-in user's saved choice; signed out, the last one made in this
    // browser; and with neither, the device decides.
    const userThemePreference = user?.theme;
    const storedThemePreference = localStorage.getItem("theme");
    let initialThemePreference: ThemeEnum = ThemeEnum.system;
    if (isThemePreference(userThemePreference)) {
      initialThemePreference = userThemePreference;
    } else if (isThemePreference(storedThemePreference)) {
      initialThemePreference = storedThemePreference;
    }

    if (user?.sidebar_collapsed !== undefined) {
      initialSidebarCollapsed = user.sidebar_collapsed;
    } else {
      // Check localStorage for sidebar preference
      const savedSidebarState = localStorage.getItem("sidebarCollapsed");
      initialSidebarCollapsed = savedSidebarState === "true";
    }

    setLanguage(initialLanguage);
    setThemePreference(initialThemePreference);
    setSidebarCollapsed(initialSidebarCollapsed);
    applyDayjsLocale(initialLanguage);
  }, [user, tenantLanguage]);

  // Update dayjs locale when language changes
  useEffect(() => {
    applyDayjsLocale(language);
  }, [language]);

  // Kept in this browser for the signed-out pages.
  useEffect(() => {
    localStorage.setItem("theme", themePreference);
  }, [themePreference]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("sidebarCollapsed", sidebarCollapsed.toString());
  }, [sidebarCollapsed]);

  // Save preferences to backend
  const savePreferences = useCallback(
    async (newPreferences: UserPreferences) => {
      if (!user) {
        // If no user, just update local state
        if (newPreferences.language) {
          setLanguage(newPreferences.language);
          applyDayjsLocale(newPreferences.language);
          storeLanguagePick(newPreferences.language);
        }
        if (newPreferences.theme) {
          setThemePreference(newPreferences.theme);
        }
        if (newPreferences.sidebar_collapsed !== undefined) {
          setSidebarCollapsed(newPreferences.sidebar_collapsed);
        }
        return;
      }

      try {
        setLoading(true);
        setError(null);

        // Only fields the server persists for a profile PATCH;
        // sidebar_collapsed is a local-only preference.
        const profilePayload: UserProfileUpdateRequest = {};
        // A language from browser/tenant detection can be anything — switch
        // the UI to it locally below, but never send an unsupported code to
        // the server, whose choice field would 400.
        if (isSupportedLanguageCode(newPreferences.language)) {
          profilePayload.user_language = newPreferences.language;
        }
        if (newPreferences.theme) {
          profilePayload.theme = newPreferences.theme;
        }
        if (Object.keys(profilePayload).length > 0) {
          await authPartialUpdate(String(user.id), profilePayload);
        }

        // Update local state. The language is also kept in this browser, so the
        // signed-out pages speak it after sign-out.
        if (newPreferences.language) {
          setLanguage(newPreferences.language);
          applyDayjsLocale(newPreferences.language);
          storeLanguagePick(newPreferences.language);
        }
        if (newPreferences.theme) {
          setThemePreference(newPreferences.theme);
        }
        if (newPreferences.sidebar_collapsed !== undefined) {
          setSidebarCollapsed(newPreferences.sidebar_collapsed);
        }

        // The signed-in user carries what the profile now holds, so a later
        // profile save, which writes the user back whole, can't undo the
        // pick. ``updateUser`` also keeps the stored ``auth`` entry.
        const savedUserFields: Parameters<typeof updateUser>[0] = {};
        if (profilePayload.user_language) {
          savedUserFields.user_language = profilePayload.user_language;
        }
        if (profilePayload.theme) savedUserFields.theme = profilePayload.theme;
        if (newPreferences.sidebar_collapsed !== undefined) {
          savedUserFields.sidebar_collapsed = newPreferences.sidebar_collapsed;
        }
        if (Object.keys(savedUserFields).length > 0) {
          updateUser(savedUserFields);
        }
      } catch (err) {
        const errorMessage =
          getServerErrorMessage(err) ?? t("profile.preferences_save_error");
        notify.error(errorMessage);
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [user, updateUser, t],
  );

  // Save language to backend and update auth
  const saveLanguage = useCallback(
    async (newLanguage: string) => {
      if (!newLanguage || newLanguage === language) {
        return;
      }
      await savePreferences({ language: newLanguage });
    },
    [language, savePreferences],
  );

  const saveThemePreference = useCallback(
    async (preference: ThemeEnum) => {
      if (preference === themePreference) {
        return;
      }
      await savePreferences({ theme: preference });
    },
    [themePreference, savePreferences],
  );

  const saveSidebarCollapsed = useCallback(
    async (newSidebarCollapsed: boolean) => {
      if (newSidebarCollapsed === sidebarCollapsed) {
        return;
      }
      await savePreferences({ sidebar_collapsed: newSidebarCollapsed });
    },
    [sidebarCollapsed, savePreferences],
  );

  // Set language without saving to backend (for temporary changes)
  const setLanguageLocal = useCallback((newLanguage: string) => {
    setLanguage(newLanguage);
    applyDayjsLocale(newLanguage);
  }, []);

  const setSidebarCollapsedLocal = useCallback(
    (newSidebarCollapsed: boolean) => {
      setSidebarCollapsed(newSidebarCollapsed);
    },
    [],
  );

  const toggleSidebar = useCallback(() => {
    const newState = !sidebarCollapsed;
    setSidebarCollapsed(newState);
    // Auto-save the preference
    if (user) {
      saveSidebarCollapsed(newState).catch(console.error);
    }
  }, [sidebarCollapsed, user, saveSidebarCollapsed]);

  const value = useMemo<LocaleContextValue>(
    () => ({
      language,
      theme,
      themePreference,
      sidebarCollapsed,
      loading,
      error,
      saveLanguage,
      saveThemePreference,
      saveSidebarCollapsed,
      savePreferences,
      setLanguage: setLanguageLocal,
      setSidebarCollapsed: setSidebarCollapsedLocal,
      toggleSidebar,
    }),
    [
      language,
      theme,
      themePreference,
      sidebarCollapsed,
      loading,
      error,
      saveLanguage,
      saveThemePreference,
      saveSidebarCollapsed,
      savePreferences,
      setLanguageLocal,
      setSidebarCollapsedLocal,
      toggleSidebar,
    ],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}
