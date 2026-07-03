/**
 * Reports DE translation keys that are USED in the code but NOT DEFINED
 * in any of the JSON files under ``src/i18n/locales/de/``.
 *
 * Static-scan approach: walk every ``.ts``/``.tsx``/``.jsx`` file under
 * ``src/`` (skipping ``node_modules``, ``__tests__``, and the generated
 * API client), regex out every ``t("key", ...)`` and ``<Trans
 * i18nKey="key">`` reference, flatten the DE bundle into a Set of
 * dotted paths, and diff.
 *
 * Known limitations (documented so the output is interpretable):
 *  - Dynamic keys like ``t(`commissioning.${size}`)`` are skipped (no
 *    way to resolve them statically). If you depend on a variation
 *    template, add the static endpoints explicitly to the DE bundle.
 *  - Plural forms (``t("items", { count })`` resolved at runtime to
 *    ``items_one`` / ``items_other``) appear as missing because the
 *    base key isn't in the JSON. Suppress those by adding a base key
 *    or by editing the IGNORE_PATTERNS list below.
 *  - This test does NOT detect EXTRA keys (defined in DE but never
 *    used). That's a separate dead-code question — out of scope here.
 */

import fs from "node:fs";
import path from "node:path";
import { describe, it } from "vitest";

import de from "../locales/de";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

// src/shared/i18n/__tests__ -> src (scan the whole source tree, not just shared/)
const SRC_ROOT = path.resolve(__dirname, "..", "..", "..");

const SCANNED_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"]);

const SKIPPED_DIR_NAMES = new Set([
  "node_modules",
  "__tests__",
  "__pycache__",
  "test",
  "tests",
  "generated", // orval-generated API client — uses t() purely for error messages we pin elsewhere
]);

// Substrings matched against the full file path. Useful when a whole
// area legitimately uses dynamic keys you don't want to flag.
const SKIPPED_PATH_FRAGMENTS: string[] = [
  "/i18n/__tests__/",
  "/api/generated/",
  // Deferred apps (see CLAUDE.md "ignore the apps cultivation/economics/staff")
  // — excluded so their in-progress keys don't block the enforced DE-coverage
  // check for the in-scope apps.
  "/features/staff/",
  "/features/cultivation/",
  "/features/economics/",
];

// Exact keys you've decided to allow as missing — e.g. keys resolved
// at runtime via plural suffixing, or keys you genuinely intend to
// load from the http backend later.
const IGNORE_KEYS = new Set<string>([
  // add entries here as needed
]);

// Key-prefix patterns. Anything starting with one of these is skipped.
// Useful for entire dynamic ranges like ``commissioning.${size}``.
const IGNORE_KEY_PREFIXES: string[] = [
  // e.g. "commissioning.size_dynamic.",
];

// ---------------------------------------------------------------------------
// 1. Flatten the DE bundle into a Set of dotted keys
// ---------------------------------------------------------------------------

function flatten(
  obj: unknown,
  prefix: string,
  acc: Set<string>,
): void {
  if (obj === null || typeof obj !== "object") {
    acc.add(prefix);
    return;
  }
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    const next = prefix ? `${prefix}.${k}` : k;
    flatten(v, next, acc);
  }
}

const definedKeys = new Set<string>();
flatten(de, "", definedKeys);

// ---------------------------------------------------------------------------
// 2. Walk the source tree, extract t("...") and i18nKey="..." references
// ---------------------------------------------------------------------------

interface Reference {
  key: string;
  file: string;
  line: number;
}

// ``\bt\(\s*["']([^"']+)["']`` matches
//   t("foo"), t( "foo", ... ), t('foo')
// but NOT
//   t(`foo.${x}`)         (template literal — dynamic)
//   t(variable)           (no quote — dynamic)
//   .t("foo") via someObj — accepted false positive (very rare in practice)
const T_CALL_RE = /\bt\(\s*["']([^"'\n]+)["']/g;

// ``<Trans i18nKey="foo">`` form — also captures single-quoted variant.
const TRANS_KEY_RE = /\bi18nKey\s*=\s*["']([^"'\n]+)["']/g;

function walk(dir: string, files: string[]): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIPPED_DIR_NAMES.has(entry.name)) continue;
      walk(path.join(dir, entry.name), files);
      continue;
    }
    const ext = path.extname(entry.name);
    if (!SCANNED_EXTENSIONS.has(ext)) continue;
    files.push(path.join(dir, entry.name));
  }
}

function shouldSkipPath(filePath: string): boolean {
  return SKIPPED_PATH_FRAGMENTS.some((frag) => filePath.includes(frag));
}

function lineNumber(text: string, offset: number): number {
  let line = 1;
  for (let i = 0; i < offset; i++) if (text.charCodeAt(i) === 10) line++;
  return line;
}

function collectReferences(): Reference[] {
  const refs: Reference[] = [];
  const files: string[] = [];
  walk(SRC_ROOT, files);

  for (const file of files) {
    if (shouldSkipPath(file)) continue;
    const text = fs.readFileSync(file, "utf8");
    const relPath = path.relative(SRC_ROOT, file);

    for (const re of [T_CALL_RE, TRANS_KEY_RE]) {
      re.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = re.exec(text)) !== null) {
        const key = match[1];
        // Only flag dotted keys — single-word "args" like t("foo") in
        // unit tests usually aren't namespaced keys. If you DO have
        // top-level keys without a dot (rare), drop this filter.
        if (!key.includes(".")) continue;
        refs.push({ key, file: relPath, line: lineNumber(text, match.index) });
      }
    }
  }
  return refs;
}

// ---------------------------------------------------------------------------
// 3. Diff + report
// ---------------------------------------------------------------------------

function isIgnored(key: string): boolean {
  if (IGNORE_KEYS.has(key)) return true;
  return IGNORE_KEY_PREFIXES.some((p) => key.startsWith(p));
}

describe("DE i18n coverage", () => {
  it("reports t(...) and <Trans i18nKey=...> references that aren't in src/i18n/locales/de", () => {
    const refs = collectReferences();

    // Group by key so each missing key reports all its call sites.
    const missingByKey = new Map<string, Reference[]>();
    for (const ref of refs) {
      if (isIgnored(ref.key)) continue;
      if (definedKeys.has(ref.key)) continue;
      const list = missingByKey.get(ref.key) ?? [];
      list.push(ref);
      missingByKey.set(ref.key, list);
    }

    if (missingByKey.size === 0) {
      console.log("\nDE i18n coverage: all referenced keys resolved.\n");
      return;
    }

    const sortedKeys = [...missingByKey.keys()].sort();
    const lines: string[] = [
      "",
      `DE i18n: ${missingByKey.size} translation key(s) used in code but ` +
        "missing from src/i18n/locales/de/:",
      "",
    ];
    for (const key of sortedKeys) {
      lines.push(`  ${key}`);
      const sites = missingByKey.get(key)!;
      // Show up to 3 call sites per key to keep the output readable.
      for (const site of sites.slice(0, 3)) {
        lines.push(`      ${site.file}:${site.line}`);
      }
      if (sites.length > 3) {
        lines.push(`      … and ${sites.length - 3} more`);
      }
    }
    lines.push("");

    // Enforced: a key used in code but missing from the DE bundle (the
    // fallbackLng) renders the raw key string to the user — exactly the bug
    // this guards. Deferred apps are excluded via SKIPPED_PATH_FRAGMENTS so
    // the in-scope backlog stays empty.
    throw new Error(lines.join("\n"));
  });
});
