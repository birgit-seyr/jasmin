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

// Budgets (gzip KB).
const budgets = [
  { name: "total critical-path (boot preload)", kb: totalKB, limit: 1200 },
  { name: "entry chunk (app boot code)", kb: sizes[entry], limit: 165 },
  {
    name: "vendor-react",
    kb: reactChunk ? sizes[reactChunk] : 0,
    limit: 60,
  },
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
