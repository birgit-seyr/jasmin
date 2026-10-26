// @vitest-environment node
/**
 * Codebase guard: every ``eslint-disable`` directive says why.
 *
 * A disable switches a rule off for good at that spot, and the rule's next
 * real finding there goes unseen. The reason is what lets a reader judge
 * whether the exception still holds, so it sits on the directive itself, in
 * ESLint's own description syntax:
 *
 *     // eslint-disable-next-line react-hooks/exhaustive-deps -- syncs only on route change
 *     /* eslint-disable react-refresh/only-export-components --
 *        the PDF module exports its builder next to the component *\/
 *
 * A block comment may carry the reason on the lines after the ``--``. A
 * comment elsewhere in the function does not count: it drifts away from the
 * directive it explains.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const SRC = join(REPO, "src");

const DIRECTIVE = /eslint-disable(?:-next-line|-line)?\b/;

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      yield* walk(full);
      continue;
    }
    yield full;
  }
}

const THIS_FILE = fileURLToPath(import.meta.url);

function isCandidateFile(path: string): boolean {
  if (!/\.(?:tsx?|jsx?)$/.test(path)) return false;
  // This file's own examples are directives without a reason, on purpose.
  if (path === THIS_FILE) return false;
  // The generated Orval client is rewritten on every regeneration.
  return !path.includes("/api/generated/");
}

/** True when the directive on ``line`` carries a ``--`` description, on the
 *  line itself or, for a block comment left open, on the lines after it. */
function hasReason(line: string): boolean {
  const afterDirective = line.slice(line.search(DIRECTIVE));
  const marker = afterDirective.search(/\s--(?:\s|$)/);
  if (marker === -1) return false;
  const reason = afterDirective
    .slice(marker)
    .replace(/^\s--/, "")
    .replace(/\*\/.*$/, "")
    .trim();
  if (reason) return true;
  const openBlock = line.includes("/*") && !line.includes("*/");
  return openBlock;
}

interface Violation {
  path: string;
  line: number;
  snippet: string;
}

function scanFile(path: string): Violation[] {
  const out: Violation[] = [];
  readFileSync(path, "utf8")
    .split("\n")
    .forEach((line, idx) => {
      if (DIRECTIVE.test(line) && !hasReason(line)) {
        out.push({ path, line: idx + 1, snippet: line.trim() });
      }
    });
  return out;
}

describe("eslint-disable directives carry a reason", () => {
  it("every eslint-disable has a -- description", () => {
    const violations: Violation[] = [];
    for (const path of walk(SRC)) {
      if (isCandidateFile(path)) violations.push(...scanFile(path));
    }
    const report = violations
      .map((v) => `  ${relative(REPO, v.path)}:${v.line}: ${v.snippet}`)
      .join("\n");
    expect(
      violations,
      `eslint-disable without a reason. Add "-- <why>" to the directive:\n${report}`,
    ).toEqual([]);
  });

  it("recognises the description forms in use", () => {
    expect(
      hasReason(
        "// eslint-disable-next-line react-hooks/exhaustive-deps -- syncs only on route change",
      ),
    ).toBe(true);
    expect(
      hasReason("/* eslint-disable react-refresh/only-export-components --"),
    ).toBe(true);
    expect(
      hasReason("// eslint-disable-next-line react-hooks/exhaustive-deps"),
    ).toBe(false);
    expect(
      hasReason("/* eslint-disable-next-line jsx-a11y/no-autofocus */"),
    ).toBe(false);
    expect(
      hasReason("// eslint-disable-next-line react-hooks/exhaustive-deps --"),
    ).toBe(false);
  });
});
