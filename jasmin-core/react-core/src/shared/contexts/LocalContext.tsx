import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import dayjs from "dayjs";
import { useAuth } from "./AuthContext";
import { TenantContext } from "./TenantContext";
import { authPartialUpdate } from "@shared/api/generated/auth/auth";
import type { UserProfileUpdateRequest } from "@shared/api/generated/models";

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

/** Activate the requested locale on dayjs once it's been (lazily)
 * registered. Synchronous call sites use this fire-and-forget; the
 * brief window between the call and the chunk arriving is invisible
 * in practice because most user-visible date rendering happens
 * after at least one paint. */
function applyDayjsLocale(language: string): void {
  loadDayjsLocale(language)
    .then(() => dayjs.locale(language))
    .catch((err) =>
      console.warn(`Failed to activate dayjs locale "${language}":`, err),
    );
}

interface UserPreferences {
  language?: string;
  theme?: string;
  sidebar_collapsed?: boolean;
}

interface LocalContextValue {
  language: string;
  theme: string;
  sidebarCollapsed: boolean;
  loading: boolean;
  error: string | null;
  saveLanguage: (newLanguage: string) => Promise<void>;
  saveTheme: (newTheme: string) => Promise<void>;
  saveSidebarCollapsed: (newSidebarCollapsed: boolean) => Promise<void>;
  savePreferences: (newPreferences: UserPreferences) => Promise<void>;
  setLanguage: (newLanguage: string) => void;
  setTheme: (newTheme: string) => void;
  setSidebarCollapsed: (newSidebarCollapsed: boolean) => void;
  toggleSidebar: () => void;
  getBrowserLanguage: () => string;
}

const LocalContext = createContext<LocalContextValue | undefined>(undefined);

export function useLocale() {
  const context = useContext(LocalContext);
  if (!context) {
    throw new Error("useLocale must be used within a LocaleProvider");
  }
  return context;
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  // Direct ``useContext`` instead of ``useTenant()`` because LocaleProvider
  // is also mounted on the platform (super-admin) domain where there is no
  // TenantProvider — ``useTenant()`` would throw.
  const tenantCtx = useContext(TenantContext);
  const tenantLanguage = tenantCtx?.tenant?.tenant_language ?? null;
  const [language, setLanguage] = useState("en");
  const [theme, setTheme] = useState("light");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Get browser language as fallback
  const getBrowserLanguage = useCallback(() => {
    const browserLang =
      navigator.language ||
      (navigator as unknown as { userLanguage?: string }).userLanguage;
    return browserLang?.split("-")[0] || "en"; // Get just the language code (e.g., 'en' from 'en-US')
  }, []);

  const getSystemTheme = useCallback(() => {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }, []);

  // Initialize language from user, tenant, or browser.
  //
  // Precedence:
  //   1. ``user.user_language`` — the logged-in user's saved preference
  //      wins. They explicitly set this on their profile.
  //   2. ``tenant.tenant_language`` — used pre-login (LoginPage) AND
  //      post-logout so the marketing/auth surface speaks the tenant's
  //      configured language instead of whatever the browser thinks.
  //   3. Browser ``navigator.language`` — last resort, e.g. when the
  //      LocaleProvider runs on the platform domain (no TenantProvider
  //      mounted) before the super-admin signs in.
  useEffect(() => {
    let initialLanguage = "en"; // Default fallback
    let initialTheme = "light"; // Default fallback
    let initialSidebarCollapsed = false;

    if (user?.user_language) {
      initialLanguage = user.user_language;
    } else if (tenantLanguage) {
      initialLanguage = tenantLanguage;
    } else {
      // Use browser language detection
      initialLanguage = getBrowserLanguage();
    }

    if (user?.theme) {
      initialTheme = user.theme;
    } else {
      // Check localStorage first, then system preference
      const savedTheme = localStorage.getItem("theme");
      initialTheme = savedTheme || getSystemTheme();
    }

    if (user?.sidebar_collapsed !== undefined) {
      initialSidebarCollapsed = user.sidebar_collapsed;
    } else {
      // Check localStorage for sidebar preference
      const savedSidebarState = localStorage.getItem("sidebarCollapsed");
      initialSidebarCollapsed = savedSidebarState === "true";
    }

    setLanguage(initialLanguage);
    setTheme(initialTheme);
    setSidebarCollapsed(initialSidebarCollapsed);
    applyDayjsLocale(initialLanguage);
    // ``tenantLanguage`` arrives asynchronously after the pre-login
    // tenant bootstrap fetch — re-running this effect when it
    // resolves is what makes the LoginPage flip from browser-default
    // to the tenant's configured language.
  }, [user, tenantLanguage, getBrowserLanguage, getSystemTheme]);

  // Update dayjs locale when language changes
  useEffect(() => {
    applyDayjsLocale(language);
  }, [language]);

  // Update localStorage when theme changes
  useEffect(() => {
    localStorage.setItem("theme", theme);
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
        }
        if (newPreferences.theme) {
          setTheme(newPreferences.theme);
        }
        if (newPreferences.sidebar_collapsed !== undefined) {
          setSidebarCollapsed(newPreferences.sidebar_collapsed);
        }
        return;
      }

      try {
        setLoading(true);
        setError(null);

        // Only fields the server persists for a profile PATCH; theme &
        // sidebar_collapsed are local-only preferences.
        const profilePayload: UserProfileUpdateRequest = {};
        // Persist only a backend-supported language (the user_language field is
        // constrained to these). A language from browser/tenant detection could
        // be fr/it (or anything) — switch the UI to it locally below, but never
        // send an unsupported code to the server (it would 400).
        if (
          newPreferences.language === "de" ||
          newPreferences.language === "en"
        ) {
          profilePayload.user_language = newPreferences.language;
        }
        if (Object.keys(profilePayload).length > 0) {
          await authPartialUpdate(String(user.id), profilePayload);
        }

        // Update local state
        if (newPreferences.language) {
          setLanguage(newPreferences.language);
          applyDayjsLocale(newPreferences.language);
        }
        if (newPreferences.theme) {
          setTheme(newPreferences.theme);
        }
        if (newPreferences.sidebar_collapsed !== undefined) {
          setSidebarCollapsed(newPreferences.sidebar_collapsed);
        }

        // Update auth data in localStorage
        try {
          const storedAuth = localStorage.getItem("auth");
          if (storedAuth) {
            const auth = JSON.parse(storedAuth);
            if (auth.user) {
              if (newPreferences.language)
                auth.user.user_language = newPreferences.language;
              if (newPreferences.theme) auth.user.theme = newPreferences.theme;
              if (newPreferences.sidebar_collapsed !== undefined)
                auth.user.sidebar_collapsed = newPreferences.sidebar_collapsed;
              localStorage.setItem("auth", JSON.stringify(auth));
            }
          }
        } catch (storageError) {
          console.error("Failed to update stored auth:", storageError);
        }
      } catch (err) {
        console.error("Failed to save preferences:", err);
        const errorMessage =
          (err as Error).message || "Failed to save preferences";
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [user],
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

  const saveTheme = useCallback(
    async (newTheme: string) => {
      if (!newTheme || newTheme === theme) {
        return;
      }
      await savePreferences({ theme: newTheme });
    },
    [theme, savePreferences],
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

  const setThemeLocal = useCallback((newTheme: string) => {
    setTheme(newTheme);
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

  const value = useMemo<LocalContextValue>(
    () => ({
      language,
      theme,
      sidebarCollapsed,
      loading,
      error,
      saveLanguage,
      saveTheme,
      saveSidebarCollapsed,
      savePreferences,
      setLanguage: setLanguageLocal,
      setTheme: setThemeLocal,
      setSidebarCollapsed: setSidebarCollapsedLocal,
      toggleSidebar,
      getBrowserLanguage,
    }),
    [
      language,
      theme,
      sidebarCollapsed,
      loading,
      error,
      saveLanguage,
      saveTheme,
      saveSidebarCollapsed,
      savePreferences,
      setLanguageLocal,
      setThemeLocal,
      setSidebarCollapsedLocal,
      toggleSidebar,
      getBrowserLanguage,
    ],
  );

  return (
    <LocalContext.Provider value={value}>{children}</LocalContext.Provider>
  );
}
