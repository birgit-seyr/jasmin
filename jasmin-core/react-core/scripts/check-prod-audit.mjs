// Production-dependency npm audit gate for CI.
//
// `npm audit` has no native per-advisory ignore (unlike pip-audit's
// --ignore-vuln), so we run it and filter its JSON here: fail on ANY
// high/critical advisory in the production tree EXCEPT those explicitly
// allow-listed below with a documented reason. Dev-only tooling vulns are
// excluded via --omit=dev (surfaced separately, advisory-only, in CI).
//
// It fails closed: unless npm prints a real audit report, the gate fails. When
// npm's registry audit service errors or times out, npm prints an error object
// instead and exits non-zero, which must not read as "no advisories". npm
// never retries the audit request itself, so the gate asks again a few times
// before giving up.
import { execSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ATTEMPTS = 3;
const RETRY_DELAY_MS = 15_000;

// Accepted advisories. Keep this short; revisit each on every dependency bump.
export const ALLOWLIST = {
  // quill HTML-export XSS. No fixed release exists — quill 2.0.3 is the latest
  // and react-quill-new pins it; npm's "fix" only pins quill 2.0.2, which has
  // the same export behaviour (a paper fix). Mitigated: every place that
  // renders stored rich-text HTML runs it through DOMPurify.sanitize first.
  // Remove this entry once a patched quill ships.
  "GHSA-v3m3-f69x-jf25":
    "quill HTML-export XSS — no upstream fix; output is DOMPurify-sanitised on render",
  // React Router RSC-mode CSRF bypass. The installed react-router-dom is
  // inside the advisory range (7.12.0–8.2.0), and npm's only "fix" is a
  // semver-major DOWNGRADE to 7.11.0.
  // Not exploitable here: this is a client-side Vite SPA that never runs React
  // Router's RSC / server-components mode (no server actions, no data-router
  // RSC handler), which is the sole attack surface for this advisory.
  // Remove this entry once a patched forward release ships.
  "GHSA-qwww-vcr4-c8h2":
    "React Router RSC-mode CSRF — npm's only fix is a downgrade; not exploitable in this client-only SPA (no RSC mode)",
};

function runNpmAudit() {
  try {
    return execSync("npm audit --omit=dev --json", { encoding: "utf8" });
  } catch (err) {
    // npm audit exits non-zero when vulnerabilities exist; the JSON is on stdout.
    return err.stdout?.toString() ?? "";
  }
}

// npm's error output: {"error": {"code", "summary", "detail"}}, or npm's echo of
// the failed request ({"message", "statusCode", ...}), which npm 10 merges with
// an "error" key.
function describeError(report) {
  const parts = [];
  if (report.error !== undefined) {
    const { code, summary, detail } = report.error ?? {};
    const text =
      typeof report.error === "object" && report.error !== null
        ? [code, summary, detail].filter(Boolean).join(" — ")
        : String(report.error);
    if (text) parts.push(text);
  }
  if (report.statusCode !== undefined) parts.push(`HTTP ${report.statusCode}`);
  if (typeof report.message === "string") parts.push(report.message);
  return parts.join("; ") || "an object that is not an audit report";
}

/**
 * Judge the stdout of `npm audit --omit=dev --json`.
 *
 * @param {string} raw
 * @param {Record<string, string>} [allowlist]
 * @returns {{ status: "ok" | "fail" | "no-report", lines: string[] }}
 *
 * Returns ``{ status, lines }``: status ``"ok"`` (a report with no high or
 * critical advisory outside the allowlist), ``"fail"`` (a report with such
 * advisories), or ``"no-report"`` (anything else — npm's error object,
 * unparseable output), which is worth one more attempt and fails the gate in
 * the end.
 */
export function evaluateAuditOutput(raw, allowlist = ALLOWLIST) {
  let report;
  try {
    report = JSON.parse(raw);
  } catch {
    return {
      status: "no-report",
      lines: ["`npm audit --json` printed no JSON:", raw.slice(0, 2000)],
    };
  }
  const isReport =
    report !== null &&
    typeof report === "object" &&
    report.auditReportVersion === 2 &&
    report.vulnerabilities !== null &&
    typeof report.vulnerabilities === "object" &&
    report.error === undefined;
  if (!isReport) {
    return {
      status: "no-report",
      lines: [`npm audit returned no report: ${describeError(report ?? {})}`],
    };
  }

  const offenders = new Set();
  for (const vuln of Object.values(report.vulnerabilities)) {
    for (const via of vuln.via ?? []) {
      // String entries are transitive links, not root advisories — skip them.
      if (typeof via !== "object") continue;
      if (!["high", "critical"].includes(via.severity)) continue;
      const id = (via.url ?? "").split("/").pop();
      if (allowlist[id]) continue;
      offenders.add(`${via.severity.toUpperCase()}  ${id}  ${via.title ?? via.name ?? ""}`);
    }
  }

  if (offenders.size > 0) {
    return {
      status: "fail",
      lines: [
        "Production high/critical npm advisories outside the allowlist:",
        ...[...offenders].map((o) => "  " + o),
        "",
        "Fix the dependency, or — if there is genuinely no upstream fix — add the",
        "advisory id to ALLOWLIST in scripts/check-prod-audit.mjs with a reason.",
      ],
    };
  }
  const ids = Object.keys(allowlist);
  return {
    status: "ok",
    lines: [
      "npm prod audit OK — no high/critical advisories outside the allowlist" +
        (ids.length ? ` (allow-listed: ${ids.join(", ")})` : "") +
        ".",
    ],
  };
}

/**
 * Run the gate: ask npm up to ``attempts`` times until it prints a report, then
 * judge it. Returns the process exit code (0 only for an "ok" report).
 *
 * @param {{
 *   audit?: () => string,
 *   sleep?: (ms: number) => Promise<unknown>,
 *   log?: (message: string) => void,
 *   error?: (message: string) => void,
 *   attempts?: number,
 * }} [options]
 * @returns {Promise<number>}
 */
export async function runGate({
  audit = runNpmAudit,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  log = console.log,
  error = console.error,
  attempts = ATTEMPTS,
} = {}) {
  let result;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    result = evaluateAuditOutput(audit());
    if (result.status !== "no-report" || attempt === attempts) break;
    error(
      `${result.lines.join("\n")}\nAttempt ${attempt} of ${attempts}; asking again in ` +
        `${RETRY_DELAY_MS / 1000} s.`,
    );
    await sleep(RETRY_DELAY_MS);
  }
  if (result.status === "ok") {
    log(result.lines.join("\n"));
    return 0;
  }
  if (result.status === "no-report") {
    result.lines.push(
      "",
      `No audit report after ${attempts} attempts, so the production dependencies are`,
      "unchecked. Re-run the job once npm's audit service answers again.",
    );
  }
  error(result.lines.join("\n"));
  return 1;
}

// Run only when executed, not when imported by the tests. Both sides are real
// paths: through a symlink the two spellings differ, and a guard that compared
// them as given would skip the audit and exit 0.
const executed =
  process.argv[1] !== undefined &&
  realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
if (executed) {
  process.exit(await runGate());
}
