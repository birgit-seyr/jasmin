/**
 * WARN-ONLY Italian i18n coverage.
 *
 * Reports keys defined in the German bundle (the source of truth + the
 * ``fallbackLng``) that are MISSING from the Italian bundle — for those keys an
 * Italian user silently sees the German string.
 *
 * Like ``en_missing_translations.test.ts`` (and unlike the ENFORCED
 * ``de_missing_translations.test.ts``), this test NEVER fails CI: Italian is
 * allowed to lag German. It is a visibility / drift guard, so a PR that adds a
 * German key without an Italian one shows up in the test output instead of
 * slipping in unnoticed.
 *
 * Scope mirrors the German test: the deferred apps (cultivation / economics /
 * staff) are excluded.
 */

import { describe, it } from "vitest";

import de from "../locales/de";
import itLocale from "../locales/it";

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

describe("IT i18n coverage (warn-only)", () => {
  it("reports German keys missing from Italian (never fails CI)", () => {
    const deKeys = new Set<string>();
    const itKeys = new Set<string>();
    flatten(de, "", deKeys);
    flatten(itLocale, "", itKeys);

    const missing = [...deKeys].filter((key) => {
      const namespace = key.split(".")[0];
      if (EXCLUDED_NAMESPACES.has(namespace)) return false;
      return !itKeys.has(key);
    });

    if (missing.length === 0) {
      console.log(
        "\nIT i18n: complete — every in-scope German key has an Italian value.\n",
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
      `IT i18n: ${missing.length} German key(s) missing from Italian — these ` +
        "fall back to German for IT users (warn-only, NOT a CI failure):",
      ...[...byNamespace.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([namespace, count]) => `  ${namespace}: ${count}`),
      "",
    ];
    console.warn(lines.join("\n"));
    // No throw: Italian is permitted to trail German (German is fallbackLng).
  });
});
