/**
 * Source-scanning regression test for the "raw decimal interpolation"
 * bug class.
 *
 * Background: the tenant `number_locale` setting drives whether a value
 * displays as `12.34` (en-US) or `12,34` (de-DE) — but only if the cell
 * goes through `useNumberFormat().format(...)` / `formatNumber(...)`.
 * Several cells were caught dropping the raw backend value straight into
 * JSX or a template literal:
 *
 *     {record.tax_rate ? `${record.tax_rate} %` : ""}      // BAD
 *     {`${item.price_per_unit} €/${unit}`}                  // BAD
 *
 * Those bypass the formatter entirely — so the displayed value depends
 * on the Decimal-serialiser shape ("98.00" vs 98) and ALWAYS uses "."
 * as the decimal separator regardless of tenant locale.
 *
 * This test fails if any new code re-introduces that pattern for the
 * known-decimal fields. The fix is always to wrap the access in
 * `format(Number(x), N)` (UI) or `formatNumber(x, N, locale)` (PDFs).
 */

import { readFileSync } from "fs";
import { globSync } from "node:fs";
import { join, relative } from "path";

import { describe, expect, it } from "vitest";

// Decimal-typed fields that must go through the locale-aware formatter.
// `rabatt` is intentionally excluded — it's a PositiveSmallIntegerField on
// the backend, integer-valued, always renders the same in any locale.
const DECIMAL_FIELDS = [
  "tax_rate",
  "price_per_unit",
  "price_1",
  "price_2",
  "price_3",
  "line_netto",
  "line_brutto",
  "netto",
  "brutto",
  "amount_per_pu",
  // Domain-specific "...amount" fields the backend serializes as Decimal.
  // (Plain `amount` is too generic — too many false positives — so we
  // require an "_amount" suffix or a known prefix.)
  "purchase_amount",
  "theoretical_purchase_amount",
  "additional_theoretical_purchase_amount",
  "harvest_amount",
  "theoretical_harvest_amount",
  "additional_theoretical_harvest_amount",
  "wash_amount",
  "clean_amount",
  "kg_per_piece",
  "current_stock",
  // Share-weight measurement fields (Decimal on backend, 3 dp).
  "weight1",
  "weight2",
  "weight3",
  "weight4",
  "target_weight",
  "share_type_variation_average_weight",
];

// Variable names this pattern shows up under — typically the row passed
// into a column render or a line item passed into a PDF row.
const ACCESSORS = ["record", "item", "row", "data", "line"];

// Files exempt from the rule:
//   - zugferd.ts emits ZUGFeRD XML which MUST be canonical (".")
//   - qrcodeGenerator.ts emits SEPA EPC QR code body, must be canonical
//   - the helper itself + this test reference the field names in docs
//   - test files / fixtures
const ALLOWLIST = [
  "src/shared/pdfs/zugferd.ts",
  "src/shared/pdfs/qrcodeGenerator.ts",
  "src/shared/utils/numberFormat.ts",
  "src/shared/utils/__tests__/noRawDecimalInterpolation.test.ts",
];

function isAllowlisted(relPath: string): boolean {
  if (relPath.includes("__tests__")) return true;
  if (relPath.endsWith(".test.ts") || relPath.endsWith(".test.tsx")) return true;
  return ALLOWLIST.some((a) => relPath === a || relPath.endsWith(a));
}

// Match `${X.field}` (template literal interpolation, expression is
// JUST the accessor — anything wrapped in a call like `format(x.field, 2)`
// is fine because the close-brace doesn't immediately follow).
const TEMPLATE_RE = new RegExp(
  `\\$\\{\\s*(?:${ACCESSORS.join("|")})\\.(?:${DECIMAL_FIELDS.join("|")})\\s*\\}`,
  "g",
);

// Match `{X.field}` (JSX child expression that prints the raw field).
// Same shape — close-brace immediately after the accessor.
const JSX_RE = new RegExp(
  `(?<![$])\\{\\s*(?:${ACCESSORS.join("|")})\\.(?:${DECIMAL_FIELDS.join("|")})\\s*\\}`,
  "g",
);

// Match `return X.field` or `return X.field as ...` inside a render
// function. This is the column-render shape used by Ant Table, where
// the returned value becomes the cell's children — same display bypass
// as JSX interpolation, but the regex above misses it because there's
// no surrounding `{`. We require `return` on the same line right
// before the accessor to keep false positives low.
const RETURN_RE = new RegExp(
  `\\breturn\\s+(?:${ACCESSORS.join("|")})\\.(?:${DECIMAL_FIELDS.join("|")})(?:\\s+as\\s+[A-Za-z_<>, ?]+)?\\s*;`,
  "g",
);

// Match `${someVar} <unit>` inside a template literal — the local-variable
// equivalent of `${record.field} %`. Catches lines like
//   `${totalCleanAmount} ${getUnitLabel(record.unit as string)}`
//   `${amountPerPu} ${unitLabel}/${puLabel}`
//   `${total} kg`
//   `${price} €`
//
// Restricted to **simple identifiers** (no member access, no calls) followed
// by **a space** and either:
//   - a currency symbol (€)
//   - a known unit word (kg / l / ml / Stk / VPE / KG / etc.)
//   - another `${...Label}` / `${...Suffix}` interpolation
//   - a `${getUnitLabel(...)}` call
//
// Notably we do NOT match `%` (would false-positive on CSS like
// `width: ${col}%`) and we require space before the unit (so URL/path
// concatenations like `${backendUrl}${logo}` don't trip).
//
// Method calls (`${total.toFixed(2)} kg`) and function results
// (`${format(x, 2)} kg`) safely bypass it because the inside isn't a bare
// identifier.
const VAR_WITH_UNIT_RE =
  /\$\{[A-Za-z_][A-Za-z0-9_]*\}\s+(?:€|\b(?:kg|KG|l|ml|g|mg|Stk|STK|VPE)\b|\$\{[A-Za-z_][A-Za-z0-9_]*(?:Label|_label|Suffix|_suffix)\}|\$\{getUnitLabel\b)/g;

describe("no raw decimal interpolation in cell/PDF renders", () => {
  it("every reference to a decimal field flows through a formatter", () => {
    // Resolve src/ from this test file's location
    // (src/shared/utils/__tests__ -> src).
    const srcRoot = join(__dirname, "..", "..", "..");
    const files = globSync("**/*.{ts,tsx}", { cwd: srcRoot });

    const violations: string[] = [];

    for (const file of files) {
      const relPath = `src/${file}`.replace(/\\/g, "/");
      if (isAllowlisted(relPath)) continue;

      const contents = readFileSync(join(srcRoot, file), "utf8");

      const templateHits = contents.match(TEMPLATE_RE) ?? [];
      const jsxHits = contents.match(JSX_RE) ?? [];
      const returnHits = contents.match(RETURN_RE) ?? [];
      const varUnitHits = contents.match(VAR_WITH_UNIT_RE) ?? [];
      const all = [
        ...templateHits,
        ...jsxHits,
        ...returnHits,
        ...varUnitHits,
      ];

      if (all.length > 0) {
        // Find the line numbers for a useful error message. Lines with the
        // marker `// lint-allow: no-raw-decimal` opt out — use it when the
        // matched expression is a STRING field shadowing a decimal name
        // (e.g. `sizeLabel`, `typeName`) or for any documented false positive.
        const lines = contents.split("\n");
        const offending: string[] = [];
        lines.forEach((line, i) => {
          // Marker may be on the same line OR the line immediately above.
          const marker = "lint-allow: no-raw-decimal";
          if (line.includes(marker)) return;
          if (i > 0 && lines[i - 1].includes(marker)) return;
          if (
            TEMPLATE_RE.test(line) ||
            JSX_RE.test(line) ||
            RETURN_RE.test(line) ||
            VAR_WITH_UNIT_RE.test(line)
          ) {
            offending.push(`  ${relPath}:${i + 1}  ${line.trim()}`);
          }
          // RegExp with /g flag retains lastIndex — reset for next line.
          TEMPLATE_RE.lastIndex = 0;
          JSX_RE.lastIndex = 0;
          RETURN_RE.lastIndex = 0;
          VAR_WITH_UNIT_RE.lastIndex = 0;
        });
        violations.push(...offending);
      }
    }

    if (violations.length > 0) {
      const fixHint =
        "\n\nFix each by wrapping the access:\n" +
        '  UI:   `${format(Number(record.tax_rate), 2)} %`\n' +
        '  PDF:  `${formatNumber(item.price_per_unit, 2, locale)} €`\n';
      throw new Error(
        `Found ${violations.length} raw decimal interpolation${
          violations.length === 1 ? "" : "s"
        }:\n${violations.join("\n")}${fixHint}`,
      );
    }

    expect(violations).toEqual([]);
  });

  it("the regexes themselves catch the canonical bug pattern", () => {
    // Sanity check the regex — otherwise this test could pass vacuously.
    const buggy = '{record.tax_rate ? `${record.tax_rate} %` : ""}';
    expect(buggy.match(TEMPLATE_RE)).not.toBeNull();

    const fixed =
      '{record.tax_rate ? `${format(Number(record.tax_rate), 2)} %` : ""}';
    TEMPLATE_RE.lastIndex = 0;
    expect(fixed.match(TEMPLATE_RE)).toBeNull();

    const jsxBug = "<span>{item.price_per_unit}</span>";
    JSX_RE.lastIndex = 0;
    expect(jsxBug.match(JSX_RE)).not.toBeNull();

    const jsxFine = "<span>{format(item.price_per_unit, 2)}</span>";
    JSX_RE.lastIndex = 0;
    expect(jsxFine.match(JSX_RE)).toBeNull();

    // The conditional access `{record.tax_rate ? ... : ""}` must not match —
    // it's a guard, not a render.
    const guard = "{record.tax_rate ? something : nothing}";
    JSX_RE.lastIndex = 0;
    expect(guard.match(JSX_RE)).toBeNull();

    // `return X.field` shape (the DocumentationPurchase bug).
    const returnBug = "        return record.purchase_amount as ReactNode;";
    RETURN_RE.lastIndex = 0;
    expect(returnBug.match(RETURN_RE)).not.toBeNull();

    const returnFine =
      "        return format(Number(record.purchase_amount), 2);";
    RETURN_RE.lastIndex = 0;
    expect(returnFine.match(RETURN_RE)).toBeNull();

    // Bare `return record.purchase_amount;` (no cast) must match too.
    const returnPlain = "        return record.purchase_amount;";
    RETURN_RE.lastIndex = 0;
    expect(returnPlain.match(RETURN_RE)).not.toBeNull();

    // `${var} <unit>` — local-variable interpolation followed by a unit.
    // This is the HarvestingList / WashingList bug shape.
    const varUnitBug1 = "`${total} ${unitLabel}`";
    VAR_WITH_UNIT_RE.lastIndex = 0;
    expect(varUnitBug1.match(VAR_WITH_UNIT_RE)).not.toBeNull();

    const varUnitBug2 = "`${amountPerPu} ${unitLabel}/${puLabel}`";
    VAR_WITH_UNIT_RE.lastIndex = 0;
    expect(varUnitBug2.match(VAR_WITH_UNIT_RE)).not.toBeNull();

    const varUnitBug3 = "`${total} kg`";
    VAR_WITH_UNIT_RE.lastIndex = 0;
    expect(varUnitBug3.match(VAR_WITH_UNIT_RE)).not.toBeNull();

    const varUnitBug4 = "`${price} €`";
    VAR_WITH_UNIT_RE.lastIndex = 0;
    expect(varUnitBug4.match(VAR_WITH_UNIT_RE)).not.toBeNull();

    // Fixed shapes — must NOT match.
    const varUnitFine1 = "`${format(total, 2)} ${unitLabel}`";
    VAR_WITH_UNIT_RE.lastIndex = 0;
    expect(varUnitFine1.match(VAR_WITH_UNIT_RE)).toBeNull();

    const varUnitFine2 = "`${total.toFixed(2)} kg`";
    VAR_WITH_UNIT_RE.lastIndex = 0;
    expect(varUnitFine2.match(VAR_WITH_UNIT_RE)).toBeNull();
  });
});

// Suppress the unused-relative import (kept for path tests in future).
void relative;
