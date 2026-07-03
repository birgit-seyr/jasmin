import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import Backend from 'i18next-http-backend';

import en from './locales/en';
import de from './locales/de';
import fr from './locales/fr';
import it from './locales/it';

const resources = {
  de: {
    translation: de
  },
  en: {
    translation: en
  },
  fr: {
    translation: fr
  },
  it: {
    translation: it
  }
};

i18n
  .use(Backend)
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
      // ``navigator`` removed on purpose — auto-tracking the browser
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

// Sync <html lang> with current language
i18n.on('languageChanged', (lng: string) => {
  document.documentElement.lang = lng;
});
// Set initial lang
document.documentElement.lang = i18n.language || 'en';

export default i18n;
