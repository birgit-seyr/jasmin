/**
 * Single source of truth for the languages a user can pick and the backend
 * will store.
 *
 * The real list lives in ``apps/shared/languages.py`` (``LanguageChoices``)
 * and reaches the client as the generated ``UserLanguageEnum`` /
 * ``TenantLanguageEnum``. This module adds the two things a schema enum
 * cannot carry — a display label and a flag — so every picker, type guard
 * and payload builder reads one list instead of repeating its own.
 *
 * This is narrower than "languages the UI can render": i18next also ships
 * ``fr`` and ``it`` bundles and will display them if detection selects one.
 * Those are not offered here because the backend's choice fields reject them.
 *
 * Deliberately NOT re-exported from ``./index``: importing that module
 * initialises i18next, and a payload builder that only needs the code list
 * should not boot the whole i18n stack to get it.
 */

import { UserLanguageEnum } from "@shared/api/generated/models";

export interface SupportedLanguage {
  code: UserLanguageEnum;
  /** The language's own name, as a speaker of it would read it. */
  label: string;
  flag: string;
}

/**
 * The order pickers render in, declared rather than derived: German first,
 * because ``de`` is the in-house default and i18next's ``fallbackLng``. The
 * generated enum's own ordering carries no display meaning.
 */
export const SUPPORTED_LANGUAGES: readonly SupportedLanguage[] = [
  { code: UserLanguageEnum.de, label: "Deutsch", flag: "🇩🇪" },
  { code: UserLanguageEnum.en, label: "English", flag: "🇺🇸" },
];

export const SUPPORTED_LANGUAGE_CODES: readonly UserLanguageEnum[] =
  SUPPORTED_LANGUAGES.map((language) => language.code);

/**
 * Narrow an arbitrary locale string to a code the backend accepts.
 *
 * Language detection yields whatever the browser reports — ``fr``, ``it``,
 * ``es``, or a regional tag like ``de-DE`` — while ``user_language`` and
 * ``tenant_language`` are choice fields that 400 on anything outside the
 * list. Any value that came from detection rather than from a picker has to
 * pass through here before it goes into a payload. Regional tags are NOT
 * accepted: split on ``-`` first, so the caller decides what the base of an
 * unsupported regional tag should fall back to.
 */
export function isSupportedLanguageCode(
  value: unknown,
): value is UserLanguageEnum {
  return (
    typeof value === "string" &&
    (SUPPORTED_LANGUAGE_CODES as readonly string[]).includes(value)
  );
}
