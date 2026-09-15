/**
 * Guard: an import modal's documentation table must name the REAL CSV headers.
 *
 * Each onboarding modal carries two lists — `columns` (which generates the
 * downloadable template, so its `dataIndex` values ARE the wire schema) and
 * `columnDocRows` (the "which columns are there" help table). If they drift,
 * a CSV hand-built from the help text fails on EVERY row with "this field is
 * required", naming columns the user was never shown.
 *
 * Source-scanning rather than render-based on purpose: the two arrays are
 * local to the component, and the invariant is about the source of truth
 * agreeing with the documentation, not about the DOM.
 */
import { readFileSync } from "fs";
import { join } from "path";

import { describe, expect, it } from "vitest";

const MODALS = [
  "src/features/members/modals/CoopShareImportModal.tsx",
  "src/features/abos/modals/SepaMandateImportModal.tsx",
  "src/features/abos/modals/ExistingSubscriptionImportModal.tsx",
];

const repoRoot = join(__dirname, "..", "..");

/** Pull `dataIndex: "..."` out of the block starting at `const <name> = [`. */
function arrayBlock(source: string, declaration: RegExp): string {
  const start = source.search(declaration);
  if (start === -1) return "";
  const end = source.indexOf("\n  ];", start);
  return source.slice(start, end === -1 ? undefined : end);
}

describe("import modals document the real CSV headers", () => {
  it.each(MODALS)("%s", (relPath) => {
    const source = readFileSync(join(repoRoot, relPath), "utf8");

    const templateBlock = arrayBlock(source, /const \w*[Cc]olumns = \[/);
    const docBlock = arrayBlock(source, /const columnDocRows = \[/);

    const templateFields = new Set(
      [...templateBlock.matchAll(/dataIndex: "([a-zA-Z_]+)"/g)].map((m) => m[1]),
    );
    const documented = [...docBlock.matchAll(/field: "([a-zA-Z_]+)"/g)].map(
      (m) => m[1],
    );

    // Both lists must actually have been found — a refactor that renames either
    // array would otherwise make this test pass vacuously.
    expect(templateFields.size).toBeGreaterThan(0);
    expect(documented.length).toBeGreaterThan(0);

    // Every doc row must also carry `field` (not just `key`). Counted on a
    // bare `key: "` — prettier reflows a long row onto several lines, so
    // anything anchored to `{ key: "` silently under-counts.
    const docRowCount = [...docBlock.matchAll(/\bkey: "/g)].length;
    expect(
      documented.length,
      "every columnDocRows entry needs an explicit `field`",
    ).toBe(docRowCount);

    const undocumentable = documented.filter((f) => !templateFields.has(f));
    expect(
      undocumentable,
      `documented field(s) the template does not generate: ${undocumentable.join(", ")}`,
    ).toEqual([]);
  });
});
