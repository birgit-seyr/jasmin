/**
 * The display list in ``../languages`` and the backend's ``LanguageChoices``
 * must carry exactly the same codes. The enums asserted against are generated
 * from that Python list, so a language added on one side only fails here
 * rather than reaching a user as a rejected save or as a picker option
 * nothing can render.
 */

import { describe, expect, it } from "vitest";

import {
  TenantLanguageEnum,
  UserLanguageEnum,
} from "@shared/api/generated/models";

import {
  SUPPORTED_LANGUAGES,
  SUPPORTED_LANGUAGE_CODES,
  isSupportedLanguageCode,
} from "../languages";

const sorted = (codes: readonly string[]): string[] => [...codes].sort();

describe("supported languages", () => {
  it("holds exactly the codes user_language accepts", () => {
    expect(sorted(SUPPORTED_LANGUAGE_CODES)).toEqual(
      sorted(Object.values(UserLanguageEnum)),
    );
  });

  it("holds exactly the codes tenant_language accepts", () => {
    expect(sorted(SUPPORTED_LANGUAGE_CODES)).toEqual(
      sorted(Object.values(TenantLanguageEnum)),
    );
  });

  it("gives every language a distinct code, a label and a flag", () => {
    expect(new Set(SUPPORTED_LANGUAGE_CODES).size).toBe(
      SUPPORTED_LANGUAGES.length,
    );
    for (const language of SUPPORTED_LANGUAGES) {
      expect(language.label).not.toBe("");
      expect(language.flag).not.toBe("");
    }
  });

  it("refuses a detected locale the backend would reject", () => {
    // What browser detection hands us on a tenant with no configured
    // language — none of these may reach a choice-field payload.
    expect(isSupportedLanguageCode("fr")).toBe(false);
    expect(isSupportedLanguageCode("it")).toBe(false);
    expect(isSupportedLanguageCode(undefined)).toBe(false);
    expect(isSupportedLanguageCode(null)).toBe(false);
  });

  it("refuses a regional tag so callers split it themselves", () => {
    expect(isSupportedLanguageCode("de-DE")).toBe(false);
    expect(isSupportedLanguageCode("de")).toBe(true);
  });
});
