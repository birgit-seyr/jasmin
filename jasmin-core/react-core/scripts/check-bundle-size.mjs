// Bundle-size budget + gzip report for the production build (CI gate).
//
// Guards the "a heavy dependency silently lands on the boot critical path"
// regression class — e.g. a vendor lib pulled into the entry via a barrel
// re-export. It parses dist/index.html for the entry <script> + every
// modulepreloaded chunk (== what EVERY user downloads on first load), reports
// their gzip sizes (a lightweight stand-in for a treemap visualiser), and
// fails (exit 1) if a budget is exceeded. Dependency-free (Node stdlib only),
// matching scripts/check-prod-audit.mjs. Run after `npm run build`.
//
// Budgets are gzip KB. Bump them DELIBERATELY when a real feature lands; a
// surprise jump almost always means an eager import that belongs in a lazy
// route chunk instead of the boot path.
//
// Only German is boot weight: shared/i18n keeps `de` in i18next's `resources`
// as the fallback floor and fetches every other language as its own chunk on
// demand. So `locale-de` is budgeted below, and any OTHER `locale-*` chunk
// reaching the critical path is a regression, not a bigger number.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const DIST = "dist";

function gzipKB(relPath) {
  return gzipSync(readFileSync(join(DIST, relPath))).length / 1024;
}

let html;
try {
  html = readFileSync(join(DIST, "index.html"), "utf8");
} catch {
  console.error("✗ dist/index.html not found — run `npm run build` first.");
  process.exit(1);
}

const entry = (html.match(/<script[^>]+src="\/(assets\/js\/[^"]+)"/) || [])[1];
const preloaded = [
  ...html.matchAll(
    /<link[^>]+rel="modulepreload"[^>]+href="\/(assets\/js\/[^"]+)"/g,
  ),
].map((m) => m[1]);
const criticalPath = [...new Set([entry, ...preloaded].filter(Boolean))];

if (!entry) {
  console.error("✗ Could not find the entry <script> in dist/index.html.");
  process.exit(1);
}

const sizes = Object.fromEntries(criticalPath.map((p) => [p, gzipKB(p)]));
const totalKB = Object.values(sizes).reduce((a, b) => a + b, 0);

console.log("Critical-path chunks (modulepreloaded, gzip):");
for (const p of [...criticalPath].sort((a, b) => sizes[b] - sizes[a])) {
  console.log(
    `  ${sizes[p].toFixed(1).padStart(7)} kB  ${p.replace("assets/js/", "")}`,
  );
}

const reactChunk = criticalPath.find((p) => /vendor-react-/.test(p));
const deLocaleChunk = criticalPath.find((p) => /locale-de-/.test(p));

// A budget whose chunk has vanished has to FAIL rather than quietly score
// zero. A chunk leaving the critical path is exactly the kind of change these
// budgets exist to notice, so treating it as 0 kB switches the gate off at
// the one moment it was needed.
for (const [name, chunk] of [
  ["vendor-react", reactChunk],
  ["locale-de", deLocaleChunk],
]) {
  if (!chunk) {
    console.error(
      `\u2717 No ${name} chunk on the boot critical path. Either the chunking ` +
        "changed or it stopped being preloaded \u2014 check dist/index.html.",
    );
    process.exit(1);
  }
}

// German is the only language that boots; the rest are fetched on demand. One
// of them turning up here means a static import crept back in and dragged the
// whole translation set onto the critical path with it.
const eagerLocales = criticalPath.filter((p) =>
  /locale-(?!de-)[a-z]{2}-/.test(p),
);
if (eagerLocales.length) {
  console.error(
    `\u2717 Non-German locale chunk(s) preloaded at boot: ${eagerLocales.join(", ")}. ` +
      "Only locale-de belongs on the critical path.",
  );
  process.exit(1);
}

// @react-pdf and its font / layout / hyphenation stack is ~450 kB gzip that
// only staff-gated PDF pages can use. It does not reach the boot path by being
// imported, but by sharing a dependency with something that is — so assert its
// absence rather than budgeting its size.
const eagerPdf = criticalPath.filter((p) => /vendor-pdf-/.test(p));
if (eagerPdf.length) {
  console.error(
    `\u2717 vendor-pdf on the boot critical path: ${eagerPdf.join(", ")}. ` +
      "Something in the entry's static closure shares a dependency with it \u2014 " +
      "check base64-js and the commissioning components barrel.",
  );
  process.exit(1);
}

// Budgets (gzip KB).
const budgets = [
  { name: "total critical-path (boot preload)", kb: totalKB, limit: 600 },
  { name: "entry chunk (app boot code)", kb: sizes[entry], limit: 45 },
  {
    name: "locale-de (the resident fallback bundle)",
    kb: sizes[deLocaleChunk],
    limit: 75,
  },
  { name: "vendor-react", kb: sizes[reactChunk], limit: 60 },
];

let failed = false;
console.log("\nBudgets:");
for (const b of budgets) {
  const ok = b.kb <= b.limit;
  if (!ok) failed = true;
  console.log(
    `  ${ok ? "✓" : "✗"} ${b.name}: ${b.kb.toFixed(1)} kB (limit ${b.limit} kB)`,
  );
}

if (failed) {
  console.error(
    "\n✗ Bundle-size budget exceeded — likely a heavy dependency newly on the " +
      "boot path. Fix the eager import (move it into a lazy route chunk) or, if " +
      "the growth is intentional, bump the budget in scripts/check-bundle-size.mjs.",
  );
  process.exit(1);
}
console.log("\n✓ Bundle within budget.");
