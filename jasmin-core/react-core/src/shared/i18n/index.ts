import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import de from './locales/de';

// German alone is bundled. It is the ``fallbackLng``, so keeping it resident
// is what guarantees a key always resolves to real text instead of to the raw
// key string — and, because i18next skips its loader entirely for as long as
// ``resources`` is set, it is also what keeps ``init`` and ``changeLanguage``
// synchronous. Every other language is a Rollup chunk that
// ``activateLanguage`` fetches on demand.
const resources = {
  de: {
    translation: de
  }
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    // DE is the in-house default. EN, FR, IT translations still
    // ship and stay fully supported — switching via the language
    // switcher writes ``i18nextLng`` to localStorage and the
    // LanguageDetector picks that up on every subsequent load. The
    // fallback below kicks in only when:
    //   * no language was previously picked (first visit), OR
    //   * the active language is missing a specific key.
    // Either way the user sees DE rather than auto-tracking their
    // browser's locale.
    fallbackLng: 'de',

    defaultNS: 'translation',

    debug: import.meta.env.DEV,

    interpolation: {
      escapeValue: false,
    },

    detection: {
      // ``navigator`` is omitted on purpose — auto-tracking the browser
      // language would show the app in EN to anyone visiting from
      // an English-locale machine on first load, which isn't what
      // we want for a German-first coop product. ``localStorage``
      // still wins (so user-picked language persists), and
      // ``htmlTag`` stays as a last-resort hook for SSR scenarios.
      order: ['localStorage', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'i18nextLng',
    },
    
    react: {
      useSuspense: false,
    }
  });

/** Each ``import`` is a distinct string literal so Vite can split one chunk
 * per language, the same shape ``loadDayjsLocale`` uses for dayjs. */
async function importLanguage(
  code: string,
): Promise<Record<string, unknown> | null> {
  switch (code) {
    case 'en':
      return (await import('./locales/en')).default;
    case 'fr':
      return (await import('./locales/fr')).default;
    case 'it':
      return (await import('./locales/it')).default;
    default:
      return null;
  }
}

/**
 * Load a language's bundle if it isn't resident, then switch to it.
 *
 * The bundle is registered BEFORE the switch, so no render can observe a
 * language without its keys: react-i18next re-renders on ``languageChanged``
 * and not on a store addition, which makes the swap a single repaint rather
 * than a frame of German followed by a frame of the target language.
 *
 * Whatever happens, the language i18next ends up on is one whose bundle is
 * loaded — a failed fetch settles on German. Several call sites read
 * ``i18n.language`` synchronously and one of them posts it as a new member's
 * ``user_language``, so it must never name a bundle that isn't there.
 */
export async function activateLanguage(language: string): Promise<void> {
  const code = (language || '').split('-')[0];
  if (!code) return;

  if (!i18n.hasResourceBundle(code, 'translation')) {
    try {
      const bundle = await importLanguage(code);
      if (bundle) {
        i18n.addResourceBundle(code, 'translation', bundle, true, true);
      }
    } catch (err) {
      console.warn(`Failed to load the "${code}" translations:`, err);
    }
  }

  const target = i18n.hasResourceBundle(code, 'translation') ? code : 'de';
  if (i18n.language !== target) {
    await i18n.changeLanguage(target);
  }
}

// Sync <html lang> with current language
i18n.on('languageChanged', (lng: string) => {
  document.documentElement.lang = lng;
});
// Set initial lang
document.documentElement.lang = i18n.language || 'en';

// The detector resolves a language before any component mounts, and only
// German is bundled — so a returning EN user boots pointing at a language
// with no keys. Kick the fetch off here rather than from a component: the
// super-admin app mounts no language bridge at all, yet chrome shared by both
// domains (the offline banner, the error boundary) still translates.
void activateLanguage(i18n.language);

export default i18n;
