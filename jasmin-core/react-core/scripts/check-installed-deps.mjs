// Fails when the installed node_modules no longer match package-lock.json.
//
// In the dev stack node_modules is a named volume that a lockfile change never
// reaches, so every other check would quietly run the old packages. npm records
// what it installed in node_modules/.package-lock.json; this compares that with
// the lockfile entry by entry. An optional package that is absent is skipped:
// the lockfile lists every platform's native binaries (esbuild, rollup), and
// only the current platform's get installed.
import { existsSync, readFileSync } from "node:fs";

const INSTALLED = "node_modules/.package-lock.json";
const FIX = "Run `make dev-sync-deps` (or `npm ci` outside the dev stack).";

if (!existsSync(INSTALLED)) {
  console.error(`✗ ${INSTALLED} is missing, so nothing is installed. ${FIX}`);
  process.exit(1);
}

const locked = JSON.parse(readFileSync("package-lock.json", "utf8")).packages;
const installed = JSON.parse(readFileSync(INSTALLED, "utf8")).packages;

const drift = [];
for (const [path, entry] of Object.entries(locked)) {
  if (path === "" || entry.link) continue;
  const have = installed[path];
  if (!have) {
    if (!entry.optional) drift.push(`${path}: not installed (lock ${entry.version})`);
  } else if (have.version !== entry.version) {
    drift.push(`${path}: ${have.version} installed, lock ${entry.version}`);
  }
}
for (const path of Object.keys(installed)) {
  if (!(path in locked)) drift.push(`${path}: installed but not in the lock`);
}

if (drift.length) {
  console.error("✗ node_modules differs from package-lock.json:");
  for (const line of drift.slice(0, 15)) console.error(`  ${line}`);
  if (drift.length > 15) console.error(`  … and ${drift.length - 15} more`);
  console.error(FIX);
  process.exit(1);
}
console.log("✓ node_modules matches package-lock.json.");
