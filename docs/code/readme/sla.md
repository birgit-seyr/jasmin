# Security SLAs

**Status:** Recurring discipline doc, reviewed annually
**Last updated:** 2026-06-03

What we commit to, internally and to procurement, on time-to-patch
for dependency vulnerabilities + on security-incident response.

## Dependency vulnerabilities (Dependabot + pip-audit)

Dependabot opens PRs weekly per `.github/dependabot.yml`. `pip-audit
--strict` also runs on every PR via `.github/workflows/ci.yml`,
which catches CVEs that haven't yet produced a Dependabot patch
release.

**Triage SLA:**

| Severity | First-look | Patch deployed |
|---|---|---|
| **Critical** (CVSS ≥ 9.0 or active exploitation) | same business day | within 48 hours |
| **High** (CVSS 7.0–8.9) | within 3 business days | within 1 calendar week |
| **Medium** (CVSS 4.0–6.9) | within 1 calendar week | next regular deploy (≤ 2 weeks) |
| **Low** (CVSS < 4.0) | next monthly housekeeping | next regular deploy |
| **Disputed / not applicable** (e.g. PYSEC-2025-183 today) | same business day | suppress in `pip-audit --ignore-vuln` with written justification in this file or `docs/todos/audit_checklist.txt` |

"First-look" means a human has read the advisory and assessed
whether it applies to the codebase. "Patch deployed" means the
updated dependency is running in prod.

**What happens between first-look and patch deploy:**

1. Decide: does the advisory apply to *our* usage? (Many CVEs are
   on code paths we don't hit.) Document the decision in the
   triage notes.
2. If applicable + a patched release exists → merge the Dependabot
   PR (after CI passes), deploy.
3. If applicable + no patched release → choose: pin to a safe
   transitive version, vendor-patch, or remove the dependency.
   Open a tracking issue with the deadline.
4. If not applicable → close the Dependabot PR with a written
   rationale and add the advisory ID to the `pip-audit
   --ignore-vuln` list with the same rationale (so the next CI run
   doesn't re-surface it).

**Currently-suppressed advisories** (cross-reference against this
list when an audit asks):

| ID | Justification | Re-review trigger |
|---|---|---|
| PYSEC-2025-183 (pyjwt) | Disputed by upstream; does not affect this codebase's token-validation path. | When pyjwt ships a 2.x release that addresses the disputed item, drop the suppression and re-run pip-audit. |

## Security incident response

Goal: notify the supervisory authority within 72 hours of becoming
aware of a personal data breach (GDPR Art. 33).

The full runbook lives at `docs/gdpr/breach-runbook.md`. The
internal SLA is:

| Phase | SLA |
|---|---|
| Detection → incident lead aware | within 1 hour of any operator noticing |
| Initial triage call (impact scope) | within 4 hours of detection |
| Decision on supervisory-authority notification | within 24 hours of detection |
| DPA notification (if required) | within 72 hours per Art. 33 |
| Affected-subject notification (if Art. 34 high-risk) | "without undue delay" — practically: same day as DPA notification or next business day |
| Post-mortem complete + action items filed | within 2 weeks of containment |

## Internal-software vulnerability reports

External researchers / customers reporting a vulnerability in our
own code (not a dependency) email **security@<platform-domain>**.
First response within 1 business day. The recipient address is
configured outside this file because changing it shouldn't require
a PR.

## Review schedule

Reviewed annually (next: 2027-06). Out-of-cycle review triggered
by:

- Any incident that required activating the breach runbook
- A Dependabot advisory we couldn't triage inside the SLA above
  (root-cause: tighten the process or staff it differently)
- Major change in regulatory expectations (new DPA guidance,
  EDPB opinion, etc.)
