// @vitest-environment node
/**
 * Codebase guard: no raw axios HTTP calls outside the documented
 * exceptions.
 *
 * The project's standing rule (see CLAUDE.md):
 *   - Reach for TanStack Query + Orval-generated API clients first.
 *   - Raw axios is allowed ONLY for cases where generated clients
 *     can't carry the right semantics: multipart uploads (Content-Type
 *     has to be set per request), the auth-flow plumbing in
 *     ``services/api.ts`` / ``services/stepUp.ts`` / ``AuthContext``
 *     (these define or compose the axios instance the generated
 *     clients eventually run through), and a handful of FormData-based
 *     PATCH calls.
 *
 * This test walks ``src/`` and reports every raw ``axios.<method>(`` or
 * ``axiosInstance.<method>(`` call site outside the allowlist with
 * ``path:line:snippet`` so the failure message points the reader at
 * exactly the spot to refactor (or, if the new file is a legitimate
 * exception, add to ``ALLOWED`` with a comment).
 *
 * The detection regex matches the HTTP verbs (``get`` / ``post`` /
 * ``put`` / ``patch`` / ``delete`` / ``head`` / ``options`` /
 * ``request``). It deliberately does NOT match ``axios.create``,
 * ``axios.CancelToken``, ``axios.isAxiosError`` or the various type
 * references (``AxiosError`` etc.), because none of those are HTTP
 * calls.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const SRC = join(REPO, "src");

/**
 * Files where raw axios is intentional. Every entry must have a
 * one-line WHY comment — that's the contract the next reviewer
 * checks against when this test fails and they're tempted to just
 * append the new file here.
 */
const ALLOWED: ReadonlyArray<{ path: string; why: string }> = [
  {
    path: "src/shared/services/api.ts",
    why: "Defines the axiosInstance + interceptors every other call goes through.",
  },
  {
    path: "src/shared/services/stepUp.ts",
    why: "Step-up POST must bypass the interceptor (which itself triggers step-up).",
  },
  {
    path: "src/shared/contexts/AuthContext.tsx",
    why: "Login / refresh / 2FA-verify direct token handling — must own the cookie path.",
  },
  // Multipart uploads. Generated clients post JSON; multipart needs
  // Content-Type per request + a raw FormData body, so each call site
  // talks to ``axiosInstance`` directly.
  {
    path: "src/shared/ui/DownloadCsvTemplateButton.tsx",
    why: "Multipart CSV upload.",
  },
  {
    path: "src/features/commissioning/modals/ShareTypeVariationModal.tsx",
    why: "Multipart image upload on the share-type-variation form.",
  },
  {
    path: "src/features/commissioning/pdfs/forResellers/generateDeliveryNotePDF.tsx",
    why: "Multipart PDF upload after the React-PDF render.",
  },
  {
    path: "src/features/commissioning/pdfs/forResellers/generateInvoicePDF.tsx",
    why: "Multipart PDF upload after the React-PDF render.",
  },
  {
    path: "src/features/configuration/pages/ConfigurationApp.tsx",
    why: "Multipart tenant-settings PATCH (logo + bio_logo file fields).",
  },
  {
    path: "src/features/configuration/pages/ConfigurationGeneral.tsx",
    why: "Multipart tenant-settings PATCH (logo + bio_logo file fields).",
  },
  // Generic reusable components whose API target is supplied by the
  // parent. The whole point of these is that the caller passes a URL
  // string + method choice in props; rewriting them to take generated
  // hooks would invert the abstraction.
  {
    path: "src/shared/tables/BasicEditableTable/EditableTable.tsx",
    why: "Generic table: caller passes ``apiEndpoints`` so it can target any list endpoint.",
  },
  {
    path: "src/shared/tables/BasicEditableTable/useEditableTable.ts",
    why: "Generic table CRUD hook — same ``apiEndpoints`` contract as EditableTable.",
  },
  {
    path: "src/shared/ui/BulkActionButton.tsx",
    why: "Generic bulk-action button: caller passes the endpoint + HTTP method.",
  },
  // Super-admin app — still on the pre-generated-client pattern; the
  // super-admin URLs don't fully flow through orval yet.
  {
    path: "src/features/platform/pages/SuperAdminDashboard.tsx",
    why: "Super-admin dashboard (tenants list + backup trigger); not yet routed through generated clients.",
  },
  {
    path: "src/features/platform/pages/SuperAdminLoginPage.tsx",
    why: "Super-admin login posts directly to ``/api/super-admin/auth/login/`` (separate JWT realm).",
  },
  {
    path: "src/features/platform/pages/TenantDetail.tsx",
    why: "Super-admin tenant detail; same pattern as SuperAdminDashboard.",
  },
  // Modals extracted out of the super-admin pages above — same realm, same
  // reason: the super-admin create endpoints aren't routed through orval yet.
  {
    path: "src/features/platform/modals/CreateAdminModal.tsx",
    why: "Super-admin create-tenant-admin POST; not yet routed through generated clients.",
  },
  {
    path: "src/features/platform/modals/CreateUserModal.tsx",
    why: "Super-admin create-tenant-user POST; not yet routed through generated clients.",
  },
  {
    path: "src/features/platform/modals/CreateTenantModal.tsx",
    why: "Super-admin create-tenant POST; not yet routed through generated clients.",
  },
  // Commissioning bulk-download endpoints stream files (PDF / ZIP)
  // straight from the server — the generated clients aren't a fit
  // for raw blob downloads.
  {
    path: "src/features/commissioning/pages/DeliveryNotes.tsx",
    why: "Bulk download of PDF / ZIP blobs from `/bulk_download_documents_{pdf,zip}/`.",
  },
];

const ALLOWED_SET = new Set(ALLOWED.map((entry) => entry.path));

// HTTP-method call shape on the axios instance. The three identifiers
// — ``axios`` (direct), ``axiosInstance`` (the configured wrapper),
// and ``axiosService`` (the default export of services/api.ts, just
// a renamed import of ``axiosInstance``) — all reach the same wire,
// so any of them is a raw call. Word-boundary anchors keep
// ``isAxiosError`` / ``create`` / ``request``-the-prop from matching.
// We DO match ``.request(`` because ``axiosInstance.request(config)``
// is just as raw as ``.post()``.
const HTTP_CALL = /\b(?:axios|axiosInstance|axiosService)\s*\.\s*(?:get|post|put|patch|delete|head|options|request)\b\s*\(/;
// Also the CALLABLE form — ``axiosService<T>({ url, method })`` /
// ``axiosInstance(config)`` — which is just as raw as ``.post()`` but has no
// method property, so the dot-form regex above misses it. ``<[^()]*>`` (not
// ``<[^>]*>``) so a nested generic like ``axiosService<Record<string,
// unknown>>(...)`` is still matched.
const CALLABLE_CALL =
  /\b(?:axios|axiosInstance|axiosService)\s*(?:<[^()]*>)?\s*\(/;

/**
 * Recursively walk ``dir`` and yield every file path that survives
 * the ignore filters.
 */
function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      yield* walk(full);
      continue;
    }
    yield full;
  }
}

/**
 * Apps the platform owner has explicitly deferred from "use generated
 * clients / TanStack Query" enforcement. Per CLAUDE.md ("For now ignore
 * the apps cultivation/economics/staff, unless i tell you explicitely.")
 * — the rule applies to the frontend pages of those apps too.
 *
 * Anything under ``src/pages/<app>/`` is skipped wholesale; nothing
 * else is. When an app graduates, just delete its entry here and run
 * the test to see what's left to clean up.
 */
const DEFERRED_APPS = [
  "src/features/staff/pages/",
  "src/features/cultivation/pages/",
  "src/features/economics/pages/",
];

function isCandidateFile(path: string): boolean {
  if (!/\.(?:tsx?|jsx?)$/.test(path)) return false;
  // Generated Orval client — uses axios under the hood but it's the
  // approved abstraction, not a raw call we'd hand-write.
  if (path.includes("/api/generated/")) return false;
  // Test files, both layouts.
  if (path.includes("/__tests__/")) return false;
  if (/\.test\.(tsx?|jsx?)$/.test(path)) return false;
  // The MSW handler files mock axios traffic; they're allowed to
  // reference axios shapes without actually calling out.
  if (path.includes("/test/msw/")) return false;
  // Deferred apps — see DEFERRED_APPS above for the rationale.
  const normalized = path.replace(/\\/g, "/");
  if (DEFERRED_APPS.some((prefix) => normalized.includes(prefix))) {
    return false;
  }
  return true;
}

interface Violation {
  path: string;
  line: number;
  snippet: string;
}

function scanFile(path: string): Violation[] {
  const text = readFileSync(path, "utf8");
  const out: Violation[] = [];
  text.split("\n").forEach((line, idx) => {
    if (HTTP_CALL.test(line) || CALLABLE_CALL.test(line)) {
      out.push({ path, line: idx + 1, snippet: line.trim() });
    }
  });
  return out;
}

describe("no raw axios calls outside the allowlist", () => {
  it("every axios.<method>(...) / axiosInstance.<method>(...) call site is documented", () => {
    const violations: Violation[] = [];

    for (const abs of walk(SRC)) {
      if (!isCandidateFile(abs)) continue;
      const rel = relative(REPO, abs).replace(/\\/g, "/");
      if (ALLOWED_SET.has(rel)) continue;
      for (const v of scanFile(abs)) {
        violations.push({ ...v, path: rel });
      }
    }

    if (violations.length > 0) {
      const formatted = violations
        .map((v) => `  ${v.path}:${v.line}\n      ${v.snippet}`)
        .join("\n");
      throw new Error(
        `Found ${violations.length} raw axios call(s) outside the allowlist.\n\n` +
          `Use the Orval-generated API clients (src/api/generated/) with TanStack Query, or — for multipart uploads — add the file to ALLOWED in this test with a one-line WHY.\n\n` +
          `Offending sites:\n${formatted}`,
      );
    }

    expect(violations).toEqual([]);
  });

  it("every allowlist entry still exists on disk", () => {
    // Catches drift in the other direction: a file gets renamed /
    // deleted but its allowlist entry sticks around, silently
    // permitting whatever takes its place.
    const missing: string[] = [];
    for (const { path } of ALLOWED) {
      const abs = join(REPO, path);
      try {
        statSync(abs);
      } catch {
        missing.push(path);
      }
    }
    if (missing.length > 0) {
      throw new Error(
        `These allowlist entries no longer exist on disk — remove them from ALLOWED:\n` +
          missing.map((p) => `  ${p}`).join("\n"),
      );
    }
    expect(missing).toEqual([]);
  });
});
