/**
 * Render-loop CENSUS — opt-in scan that walks every page module under
 * src/features/<app>/pages, attempts to render it inside a permissive shell,
 * and reports how many commits each one produces on initial mount.
 *
 * Run with:
 *     npx vitest run -t @census
 *
 * Goals:
 *   - Catch runaway re-render loops (1000+ commits) anywhere in the app.
 *   - Produce a sorted "render budget" table you can use to spot expensive
 *     pages that warrant a closer look.
 *
 * Non-goals:
 *   - Full integration coverage. Many pages crash here because they need
 *     route params, real APIs, or specific roles. Those crashes are
 *     EXPECTED and reported as `error` rather than failing the suite.
 *   - Pinning exact baselines per page. The only assertion is the loose
 *     anti-loop bound (PER_PAGE_COMMIT_BUDGET).
 *
 * If you want a real render-budget assertion for a specific page, write a
 * dedicated test using `profileRenders()` (see profileRenders.tsx).
 */
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, type ReactElement } from "react";

import { server } from "./msw/server";
import { profileRenders } from "./profileRenders";
import { AuthProvider } from "@shared/contexts/AuthContext";
import { LocaleProvider } from "@shared/contexts/LocalContext";
import { TenantProvider } from "@shared/contexts/TenantContext";
import { ModalProvider } from "@shared/contexts/ModalContext";
import { MenuProvider } from "@shared/contexts/MenuContext";
import { NavigationProvider } from "@shared/contexts/NavigationContext";
import { PermissionProvider } from "@shared/contexts/PermissionContext";

// Loose bound per page. A normal heavy page commits 5-30 times. Anything
// over 200 is almost certainly a setState-in-render loop.
const PER_PAGE_COMMIT_BUDGET = 200;

// How long we wait for the initial mount + any kicked-off queries to settle.
// Pages that genuinely never settle (a real loop) will still hit the budget
// well before this.
const SETTLE_MS = 250;

// Permissive default: every /api/* GET returns []. Keeps queries from hanging
// or erroring just because we didn't enumerate their endpoints.
function installPermissiveHandlers() {
  server.use(
    http.get(/\/api\/.*/, () => HttpResponse.json([])),
    http.post(/\/api\/.*/, () => HttpResponse.json({})),
    http.patch(/\/api\/.*/, () => HttpResponse.json({})),
    http.put(/\/api\/.*/, () => HttpResponse.json({})),
    http.delete(/\/api\/.*/, () => HttpResponse.json({})),
  );
}

function makeShell(children: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  // Mirror the App.jsx provider stack so pages that call useAuth/useTenant/
  // useModal/etc. can mount. Boot HTTP calls (silent refresh, tenant config,
  // permissions) all hit the permissive MSW catch-all and resolve to {} / [].
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TenantProvider>
          <AuthProvider>
            <LocaleProvider>
              <PermissionProvider user={null} tenant={null}>
                <NavigationProvider>
                  <MenuProvider>
                    <ModalProvider>
                      <Suspense fallback={null}>{children}</Suspense>
                    </ModalProvider>
                  </MenuProvider>
                </NavigationProvider>
              </PermissionProvider>
            </LocaleProvider>
          </AuthProvider>
        </TenantProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

interface PageResult {
  path: string;
  renders?: number;
  error?: string;
}

// Vite-only: import.meta.glob produces a record of lazy importers. The
// tsconfig knows about Vite's `ImportMeta` type, so this typechecks.
// Domain-first layout: every page module lives under
// ``src/features/<app>/pages/`` (there is no top-level ``src/pages/``).
const pageModules = import.meta.glob<{ default?: unknown }>(
  "../features/**/pages/**/*.{tsx,jsx}",
);

// Filter out things that aren't actual route components.
//   - __tests__/  : co-located tests, not pages
//   - /components/: page-local subcomponents
//   - /steps/     : wizard step children, mounted by their parent page,
//                   they expect ``data``/``update``/``back``/``next`` props
//                   and can't render in the permissive shell
const candidatePaths = Object.keys(pageModules).filter(
  (p) =>
    !p.includes("__tests__") &&
    !p.includes("/components/") &&
    !p.includes("/steps/"),
);

describe("@census render budget across all pages", () => {
  // Suppress Node's `uncaughtException` for the duration of this suite.
  // React schedules a recovery render after each error; if our cleanup() ran
  // before that microtask, the throw bubbles to process-level. We're
  // deliberately rendering pages without their full deps, so this is noise.
  let prevExceptionListeners: NodeJS.UncaughtExceptionListener[] = [];
  const swallow = () => {};

  beforeAll(() => {
    installPermissiveHandlers();
    prevExceptionListeners = process.listeners("uncaughtException");
    process.removeAllListeners("uncaughtException");
    process.on("uncaughtException", swallow);
  });
  afterEach(() => cleanup());
  afterAll(() => {
    process.off("uncaughtException", swallow);
    prevExceptionListeners.forEach((l) => process.on("uncaughtException", l));
    // Print the report at the end. We sort by render count, errors last.
    const rows = (globalThis as { __censusResults?: PageResult[] })
      .__censusResults;
    if (!rows?.length) return;
    const ok = rows.filter((r) => typeof r.renders === "number");
    const failed = rows.filter((r) => r.error);

    ok.sort((a, b) => (b.renders ?? 0) - (a.renders ?? 0));

     
    console.log(
      "\n────── RENDER CENSUS ──────\n" +
        ok
          .map((r) => `  ${String(r.renders).padStart(4)} commits  ${r.path}`)
          .join("\n") +
        `\n\n  ${failed.length} pages did not mount in the permissive shell ` +
        `(missing route params, providers, etc.):\n` +
        failed
          .slice(0, 40)
          .map((r) => `   - ${r.path}: ${r.error?.slice(0, 80)}`)
          .join("\n") +
        (failed.length > 40 ? `\n   ... and ${failed.length - 40} more` : "") +
        "\n──────────────────────────\n",
    );
  });

  it("walks every page module and reports commit counts", async () => {
    // Non-vacuity guard: if the page glob breaks (e.g. another src reorg),
    // candidatePaths goes empty, the loop runs zero times and the offenders
    // assertion below passes trivially — the census would silently scan zero
    // pages. Fail loudly instead. ~131 candidates today; 50 leaves headroom.
    expect(candidatePaths.length).toBeGreaterThan(50);

    const results: PageResult[] = [];
    (globalThis as { __censusResults?: PageResult[] }).__censusResults =
      results;

    for (const path of candidatePaths) {
      let renders: number | undefined;
      let errorMessage: string | undefined;

      try {
        const mod = await pageModules[path]();
        const Component = (mod.default ??
          Object.values(mod).find((v) => typeof v === "function")) as
          | React.ComponentType
          | undefined;

        if (!Component) {
          results.push({ path, error: "no default export" });
          continue;
        }

        const profiler = profileRenders();
        // We render inside a try so a thrown render doesn't kill the loop.
        // React still logs to console.error — that's expected noise here.
        render(makeShell(profiler.wrap(<Component />, path) as ReactElement));
        await new Promise((r) => setTimeout(r, SETTLE_MS));
        renders = profiler.onRender.mock.calls.length;
      } catch (err) {
        errorMessage = (err as Error).message;
      } finally {
        cleanup();
      }

      if (typeof renders === "number") {
        results.push({ path, renders });
      } else {
        results.push({ path, error: errorMessage ?? "unknown failure" });
      }
    }

    // Anti-loop assertion: any page that DID mount must commit fewer than
    // PER_PAGE_COMMIT_BUDGET times. Pages that crashed are reported, not
    // failed.
    const offenders = results.filter(
      (r) =>
        typeof r.renders === "number" && r.renders >= PER_PAGE_COMMIT_BUDGET,
    );
    expect(offenders).toEqual([]);
  }, 120_000);
});
