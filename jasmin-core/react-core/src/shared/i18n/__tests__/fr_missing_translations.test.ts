/**
 * WARN-ONLY French i18n coverage.
 *
 * Reports keys defined in the German bundle (the source of truth + the
 * ``fallbackLng``) that are MISSING from the French bundle — for those keys a
 * French user silently sees the German string.
 *
 * Like ``en_missing_translations.test.ts`` (and unlike the ENFORCED
 * ``de_missing_translations.test.ts``), this test NEVER fails CI: French is
 * allowed to lag German. It is a visibility / drift guard, so a PR that adds a
 * German key without a French one shows up in the test output instead of
 * slipping in unnoticed.
 *
 * Scope mirrors the German test: the deferred apps (cultivation / economics /
 * staff) are excluded.
 */

import { describe, it } from "vitest";

import de from "../locales/de";
import fr from "../locales/fr";

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

describe("FR i18n coverage (warn-only)", () => {
  it("reports German keys missing from French (never fails CI)", () => {
    const deKeys = new Set<string>();
    const frKeys = new Set<string>();
    flatten(de, "", deKeys);
    flatten(fr, "", frKeys);

    const missing = [...deKeys].filter((key) => {
      const namespace = key.split(".")[0];
      if (EXCLUDED_NAMESPACES.has(namespace)) return false;
      return !frKeys.has(key);
    });

    if (missing.length === 0) {
      console.log(
        "\nFR i18n: complete — every in-scope German key has a French value.\n",
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
      `FR i18n: ${missing.length} German key(s) missing from French — these ` +
        "fall back to German for FR users (warn-only, NOT a CI failure):",
      ...[...byNamespace.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([namespace, count]) => `  ${namespace}: ${count}`),
      "",
    ];
    console.warn(lines.join("\n"));
    // No throw: French is permitted to trail German (German is fallbackLng).
  });
});
