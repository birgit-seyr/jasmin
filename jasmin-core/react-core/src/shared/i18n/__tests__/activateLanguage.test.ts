/**
 * German is the only language in i18next's ``resources``; the rest are
 * fetched on demand. Two invariants hold that up, and neither is visible
 * from a type or a lint rule:
 *
 *  - ``de`` must be resident SYNCHRONOUSLY at import time. It is the
 *    ``fallbackLng``, so if it ever became lazy a key would render as its
 *    own raw string to the user during the fetch window.
 *  - i18next must never come to rest on a language whose bundle is absent.
 *    Several call sites read ``i18n.language`` synchronously, and one posts
 *    it as a new member's ``user_language``.
 */

import { describe, expect, it } from "vitest";

import i18n, { activateLanguage } from "@shared/i18n";

describe("locale bundling at import time", () => {
  it("has German resident without awaiting anything, and nothing else", () => {
    expect(i18n.hasResourceBundle("de", "translation")).toBe(true);
    expect(i18n.hasResourceBundle("en", "translation")).toBe(false);
    expect(i18n.hasResourceBundle("fr", "translation")).toBe(false);
    expect(i18n.hasResourceBundle("it", "translation")).toBe(false);
  });
});

describe("activateLanguage", () => {
  it("fetches a language on demand and switches to it", async () => {
    await activateLanguage("en");

    expect(i18n.hasResourceBundle("en", "translation")).toBe(true);
    expect(i18n.language).toBe("en");
    // A real bundle, not an empty object standing in for one.
    const bundle = i18n.getResourceBundle("en", "translation");
    expect(Object.keys(bundle).length).toBeGreaterThan(10);
  });

  it("registers the bundle before switching, never the other way round", async () => {
    const seen: boolean[] = [];
    const record = () => seen.push(i18n.hasResourceBundle("it", "translation"));
    i18n.on("languageChanged", record);
    try {
      await activateLanguage("it");
    } finally {
      i18n.off("languageChanged", record);
    }

    // Every languageChanged observer saw the keys already in the store, so
    // no render can catch the new language without its translations.
    expect(seen).not.toHaveLength(0);
    expect(seen.every(Boolean)).toBe(true);
  });

  it("resolves a regional code to its base language", async () => {
    await activateLanguage("en-US");
    expect(i18n.language).toBe("en");
  });

  it("settles on German when the language cannot be loaded", async () => {
    await activateLanguage("zz");
    expect(i18n.hasResourceBundle("zz", "translation")).toBe(false);
    expect(i18n.language).toBe("de");
  });

  it("switches back to German without a fetch", async () => {
    await activateLanguage("en");
    expect(i18n.language).toBe("en");
    await activateLanguage("de");
    expect(i18n.language).toBe("de");
  });
});
