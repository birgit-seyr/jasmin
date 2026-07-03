/**
 * Source-scanning regression test for the "missing render on decimal
 * column" bug class.
 *
 * Background: an `EditableTable` column with `inputType: "decimal*"` /
 * `"percentage"` and NO `render:` falls back to Ant Table's default
 * behaviour — print `record[dataIndex]` verbatim. The backend ships
 * decimal fields as canonical "."-form strings (DRF Decimal serializer:
 * `Decimal("12.5")` → `"12.500"`), so the cell reads "12.500" regardless
 * of the tenant's `number_locale`. In de-DE that looks like 12500.
 *
 * `noRawDecimalInterpolation.test.ts` catches the *other* shape of the
 * same bug — explicit `${record.field}` interpolation in renders / PDFs.
 * This test catches the "no render at all" shape, which the interpolation
 * regex by definition cannot find.
 *
 * Fix is always the same: add a render that routes the value through
 * `useNumberFormat().format(Number(value), N)`. The component itself is
 * locale-aware; the bug is just bypassing it.
 */

import { readFileSync } from "fs";
import { globSync } from "node:fs";
import { join } from "path";

import { describe, expect, it } from "vitest";

// src/shared/utils/__tests__ -> src (scan the whole source tree, not just shared/)
const SRC = join(__dirname, "..", "..", "..");

// Decimal-flavoured inputTypes whose values must be locale-formatted.
const DECIMAL_INPUT_TYPES = [
  "decimal1",
  "decimal2",
  "decimal3",
  "positive_decimal2",
  "negative_decimal2",
  "positive_decimal3",
  "negative_decimal3",
  "percentage",
];

const INPUT_TYPE_RE = new RegExp(
  `inputType:\\s*["'](?:${DECIMAL_INPUT_TYPES.join("|")})["']`,
  "g",
);

// A render anywhere in the enclosing object means the column author has
// taken responsibility for the display string. We don't check what the
// render does — `noRawDecimalInterpolation` catches the common mistakes
// of returning the raw value.
const RENDER_RE = /\brender\s*:/;

// A spread inside the object literal may bring in a render from a shared
// column config (e.g. `{ ...shareArticleColumn, inputType: "decimal2" }`).
// We can't follow spreads statically, so treat their presence as a pass.
const SPREAD_RE = /\.\.\./;

// Marker that the enclosing object is in fact a column config — column
// objects always carry at least `dataIndex` or `key`. Without this guard
// the regex flags hook configs like `useShareTypeVariationColumns({
// inputType: "positive_decimal2", width: "5em" })`, where the render is
// attached inside the hook and not the caller.
const COLUMN_MARKER_RE = /\b(?:dataIndex|key)\s*:/;

/**
 * Walk back from `idx` to the immediate enclosing `{`, then forward to
 * its matching `}`. Returns `null` if the braces are unbalanced (e.g.
 * the match is in a string literal that contains a `}` — unlikely for
 * column configs but cheaper to return null than mis-report).
 */
function findEnclosingBlock(
  src: string,
  idx: number,
): { start: number; end: number } | null {
  let depth = 0;
  let start = -1;
  for (let i = idx - 1; i >= 0; i--) {
    const ch = src[i];
    if (ch === "}") depth++;
    else if (ch === "{") {
      if (depth === 0) {
        start = i;
        break;
      }
      depth--;
    }
  }
  if (start === -1) return null;
  depth = 0;
  let end = -1;
  for (let i = start; i < src.length; i++) {
    const ch = src[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  return end === -1 ? null : { start, end };
}

// Files exempt from the rule:
//   - EditableTable internals reference inputType in types/sorters
//   - test files / fixtures
function isAllowlisted(relPath: string): boolean {
  if (relPath.includes("__tests__")) return true;
  if (relPath.endsWith(".test.ts") || relPath.endsWith(".test.tsx")) return true;
  if (relPath.startsWith("shared/tables/BasicEditableTable/")) return true;
  return false;
}

describe("decimal column has render", () => {
  const files = globSync("**/*.{ts,tsx}", { cwd: SRC });
  const offenders: Array<{ file: string; line: number; snippet: string }> = [];

  for (const f of files) {
    if (isAllowlisted(f)) continue;
    const content = readFileSync(join(SRC, f), "utf8");
    INPUT_TYPE_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = INPUT_TYPE_RE.exec(content)) !== null) {
      const block = findEnclosingBlock(content, m.index);
      if (!block) continue;
      const objText = content.slice(block.start, block.end + 1);
      if (!COLUMN_MARKER_RE.test(objText)) continue;
      if (RENDER_RE.test(objText)) continue;
      if (SPREAD_RE.test(objText)) continue;
      const line = content.slice(0, m.index).split("\n").length;
      offenders.push({ file: `src/${f}`, line, snippet: m[0] });
    }
  }

  it("every EditableTable column with a decimal/percentage inputType defines a render", () => {
    if (offenders.length > 0) {
      const detail = offenders
        .map((o) => `  ${o.file}:${o.line} — ${o.snippet}`)
        .join("\n");
      throw new Error(
        `Found ${offenders.length} column(s) with a decimal inputType but no render:\n${detail}\n\n` +
          `Without a render, Ant Table prints the raw backend value ("12.500" from a Decimal field), ` +
          `which leaks the canonical "." separator regardless of tenant locale. ` +
          `Add a render that calls useNumberFormat().format(Number(value), N).`,
      );
    }
    expect(offenders).toEqual([]);
  });
});
