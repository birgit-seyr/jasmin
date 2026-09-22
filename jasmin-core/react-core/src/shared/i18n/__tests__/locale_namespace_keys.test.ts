/**
 * Every locale barrel must name its namespaces exactly the way ``de`` does.
 *
 * A stray name is invisible: i18next finds no key under it, falls through to
 * ``fallbackLng``, and the user simply sees German. Nothing fails, nothing
 * logs. fr and it shipped ``abo`` where every other locale — and all ~200
 * ``t("abos.…")`` call sites — use ``abos``, so the whole namespace was
 * unreachable in those languages.
 *
 * A locale may hold FEWER namespaces than de (fr and it are deliberate stubs
 * that degrade to German). It may not hold a name de does not have.
 */

import { describe, expect, it } from "vitest";

// Suffixed because the Italian bundle would otherwise shadow vitest's ``it``.
import deLocale from "../locales/de";
import enLocale from "../locales/en";
import frLocale from "../locales/fr";
import itLocale from "../locales/it";

const deNamespaces = new Set(Object.keys(deLocale));

describe.each([
  ["en", enLocale],
  ["fr", frLocale],
  ["it", itLocale],
])("%s locale namespaces", (_name, bundle) => {
  it("uses only namespace names that exist in de", () => {
    const unknown = Object.keys(bundle).filter((k) => !deNamespaces.has(k));
    expect(unknown).toEqual([]);
  });

  it("is not empty", () => {
    expect(Object.keys(bundle).length).toBeGreaterThan(0);
  });
});
