// @vitest-environment node
import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { evaluateAuditOutput, runGate } from "../check-prod-audit.mjs";

const report = (vulnerabilities: Record<string, unknown> = {}) =>
  JSON.stringify({ auditReportVersion: 2, vulnerabilities, metadata: {} });

const advisory = (id: string, severity: string) => ({
  severity,
  via: [{ severity, url: `https://github.com/advisories/${id}`, title: `title ${id}` }],
});

describe("evaluateAuditOutput", () => {
  it("passes a report without high or critical advisories", () => {
    const result = evaluateAuditOutput(
      report({ lodash: advisory("GHSA-low", "moderate"), dep: { via: ["lodash"] } }),
      {},
    );
    expect(result.status).toBe("ok");
  });

  it("fails on a high advisory outside the allowlist and names it", () => {
    const result = evaluateAuditOutput(report({ pkg: advisory("GHSA-high", "high") }), {});
    expect(result.status).toBe("fail");
    expect(result.lines.join("\n")).toContain("HIGH  GHSA-high  title GHSA-high");
  });

  it("passes an allow-listed advisory", () => {
    const result = evaluateAuditOutput(report({ pkg: advisory("GHSA-known", "critical") }), {
      "GHSA-known": "reason",
    });
    expect(result.status).toBe("ok");
  });

  it.each([
    ["npm's error object", JSON.stringify({ error: { code: "EAUDITNOPJSON", summary: "audit failed" } }), "audit failed"],
    ["a registry error", JSON.stringify({ message: "Service Unavailable", statusCode: 503 }), "HTTP 503"],
    ["an old-format report", JSON.stringify({ advisories: {}, metadata: {} }), "not an audit report"],
    ["a report without vulnerabilities", JSON.stringify({ auditReportVersion: 2, vulnerabilities: null }), "not an audit report"],
    ["a report next to an error", JSON.stringify({ auditReportVersion: 2, vulnerabilities: {}, error: "partial" }), "partial"],
    ["no output", "", "printed no JSON"],
    ["plain text", "npm ERR! network timeout", "printed no JSON"],
  ])("treats %s as no report", (_label, raw, expected) => {
    const result = evaluateAuditOutput(raw, {});
    expect(result.status).toBe("no-report");
    expect(result.lines.join("\n")).toContain(expected);
  });
});

describe("runGate", () => {
  const quiet = { log: vi.fn(), error: vi.fn(), sleep: vi.fn(async () => {}) };

  it("asks again when npm prints no report, and passes once a report arrives", async () => {
    const audit = vi
      .fn()
      .mockReturnValueOnce(JSON.stringify({ message: "timeout", statusCode: 504 }))
      .mockReturnValueOnce(report());
    await expect(runGate({ ...quiet, audit, attempts: 3 })).resolves.toBe(0);
    expect(audit).toHaveBeenCalledTimes(2);
  });

  it("fails closed after the last attempt without a report", async () => {
    const audit = vi.fn(() => JSON.stringify({ message: "timeout", statusCode: 504 }));
    const error = vi.fn();
    await expect(runGate({ ...quiet, error, audit, attempts: 3 })).resolves.toBe(1);
    expect(audit).toHaveBeenCalledTimes(3);
    expect(error.mock.calls.at(-1)?.[0]).toContain("No audit report after 3 attempts");
  });

  it("fails without retrying when the report has an advisory", async () => {
    const audit = vi.fn(() => report({ pkg: advisory("GHSA-new", "high") }));
    await expect(runGate({ ...quiet, audit, attempts: 3 })).resolves.toBe(1);
    expect(audit).toHaveBeenCalledTimes(1);
  });
});

describe("the script run as a command", () => {
  const script = resolve(__dirname, "../check-prod-audit.mjs");
  let stubDir = "";

  afterEach(() => {
    if (stubDir) rmSync(stubDir, { recursive: true, force: true });
    stubDir = "";
  });

  // A fake `npm` first on PATH that prints the given audit output.
  const runWithStubNpm = (output: string, entry = script) => {
    stubDir = mkdtempSync(join(tmpdir(), "prod-audit-"));
    writeFileSync(join(stubDir, "audit.json"), output);
    const stub = join(stubDir, "npm");
    writeFileSync(stub, `#!/bin/sh\ncat "${join(stubDir, "audit.json")}"\nexit 1\n`);
    chmodSync(stub, 0o755);
    return spawnSync(process.execPath, [entry], {
      encoding: "utf8",
      env: { ...process.env, PATH: `${stubDir}:${process.env.PATH ?? ""}` },
    });
  };

  it("exits 1 and names an advisory outside the allowlist", () => {
    const run = runWithStubNpm(report({ pkg: advisory("GHSA-stub-high", "high") }));
    expect(run.status).toBe(1);
    expect(run.stderr).toContain("GHSA-stub-high");
  });

  it("exits 0 on a clean report", () => {
    const run = runWithStubNpm(report());
    expect(run.status).toBe(0);
    expect(run.stdout).toContain("npm prod audit OK");
  });

  it("still runs the audit when started through a symlink", () => {
    stubDir = mkdtempSync(join(tmpdir(), "prod-audit-"));
    const link = join(stubDir, "linked-check.mjs");
    symlinkSync(script, link);
    const linkDir = stubDir;
    stubDir = "";
    const run = runWithStubNpm(report({ pkg: advisory("GHSA-stub-link", "critical") }), link);
    rmSync(linkDir, { recursive: true, force: true });
    expect(run.status).toBe(1);
    expect(run.stderr).toContain("GHSA-stub-link");
  });
});
