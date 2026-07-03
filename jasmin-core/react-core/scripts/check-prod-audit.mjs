// Production-dependency npm audit gate for CI.
//
// `npm audit` has no native per-advisory ignore (unlike pip-audit's
// --ignore-vuln), so we run it and filter its JSON here: fail on ANY
// high/critical advisory in the production tree EXCEPT those explicitly
// allow-listed below with a documented reason. Dev-only tooling vulns are
// excluded via --omit=dev (surfaced separately, advisory-only, in CI).
import { execSync } from "node:child_process";

// Accepted advisories. Keep this short; revisit each on every dependency bump.
const ALLOWLIST = {
  // quill HTML-export XSS. No fixed release exists — quill 2.0.3 is the latest
  // and react-quill-new pins it; npm's "fix" only pins quill 2.0.2, which has
  // the same export behaviour (a paper fix). Mitigated: the single place we
  // render quill HTML (PrivacyPolicyPage) runs it through DOMPurify.sanitize
  // first. Remove this entry once a patched quill ships.
  "GHSA-v3m3-f69x-jf25":
    "quill HTML-export XSS — no upstream fix; output is DOMPurify-sanitised on render",
};

let raw;
try {
  raw = execSync("npm audit --omit=dev --json", { encoding: "utf8" });
} catch (err) {
  // npm audit exits non-zero when vulnerabilities exist; the JSON is on stdout.
  raw = err.stdout?.toString() ?? "";
}

let report;
try {
  report = JSON.parse(raw);
} catch {
  console.error("Could not parse `npm audit --json` output:\n" + raw);
  process.exit(1);
}

const offenders = new Set();
for (const vuln of Object.values(report.vulnerabilities ?? {})) {
  for (const via of vuln.via ?? []) {
    // String entries are transitive links, not root advisories — skip them.
    if (typeof via !== "object") continue;
    if (!["high", "critical"].includes(via.severity)) continue;
    const id = (via.url ?? "").split("/").pop();
    if (ALLOWLIST[id]) continue;
    offenders.add(`${via.severity.toUpperCase()}  ${id}  ${via.title ?? via.name ?? ""}`);
  }
}

if (offenders.size > 0) {
  console.error(
    "Production high/critical npm advisories outside the allowlist:\n" +
      [...offenders].map((o) => "  " + o).join("\n") +
      "\n\nFix the dependency, or — if there is genuinely no upstream fix — add the\n" +
      "advisory id to ALLOWLIST in scripts/check-prod-audit.mjs with a reason.",
  );
  process.exit(1);
}

const ids = Object.keys(ALLOWLIST);
console.log(
  "npm prod audit OK — no high/critical advisories outside the allowlist" +
    (ids.length ? ` (allow-listed: ${ids.join(", ")})` : "") +
    ".",
);
