/**
 * WARN-ONLY English i18n coverage.
 *
 * Reports keys defined in the German bundle (the source of truth + the
 * ``fallbackLng``) that are MISSING from the English bundle — for those keys an
 * English user silently sees the German string.
 *
 * Unlike ``de_missing_translations.test.ts`` (which is ENFORCED — a key used in
 * code but missing from German renders the raw key and is a real bug), this test
 * NEVER fails: English is allowed to lag German. It is a visibility / drift
 * guard, so a PR that adds a German key without an English one shows up in the
 * test output instead of slipping in unnoticed.
 *
 * Scope mirrors the German test: the deferred apps (cultivation / economics /
 * staff) are excluded, and French / Italian are intentionally ignored.
 */

import { describe, it } from "vitest";

import de from "../locales/de";
import en from "../locales/en";

// Top-level namespaces deliberately left to fall back to German for now.
const EXCLUDED_NAMESPACES = new Set(["cultivation", "economics", "staff"]);

function flatten(obj: unknown, prefix: string, acc: Set<string>): void {
  if (obj === null || typeof obj !== "object") {
    acc.add(prefix);
    return;
  }
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    flatten(v, prefix ? `${prefix}.${k}` : k, acc);
  }
}

describe("EN i18n coverage (warn-only)", () => {
  it("reports German keys missing from English (never fails CI)", () => {
    const deKeys = new Set<string>();
    const enKeys = new Set<string>();
    flatten(de, "", deKeys);
    flatten(en, "", enKeys);

    const missing = [...deKeys].filter((key) => {
      const namespace = key.split(".")[0];
      if (EXCLUDED_NAMESPACES.has(namespace)) return false;
      return !enKeys.has(key);
    });

    if (missing.length === 0) {
      console.log(
        "\nEN i18n: complete — every in-scope German key has an English value.\n",
      );
      return;
    }

    const byNamespace = new Map<string, number>();
    for (const key of missing) {
      const namespace = key.split(".")[0];
      byNamespace.set(namespace, (byNamespace.get(namespace) ?? 0) + 1);
    }

    const lines = [
      "",
      `EN i18n: ${missing.length} German key(s) missing from English — these ` +
        "fall back to German for EN users (warn-only, NOT a CI failure):",
      ...[...byNamespace.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([namespace, count]) => `  ${namespace}: ${count}`),
      "",
    ];
    console.warn(lines.join("\n"));
    // No throw: English is permitted to trail German (German is fallbackLng).
  });
});
