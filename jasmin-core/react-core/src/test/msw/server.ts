/**
 * MSW server used by Vitest. Each test file can override handlers with
 * `server.use(...)` and the global `afterEach` in `src/test/setup.ts` calls
 * `server.resetHandlers()` to keep tests isolated.
 *
 * Default handlers below cover the boot calls every authenticated page
 * makes (silent refresh, tenant config) so individual tests don't have to
 * reinvent that scaffolding.
 */
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

const handlers = [
  // Silent refresh — by default we say "no cookie" so the user starts logged out.
  http.post(/\/api\/(super-admin\/)?auth\/refresh\/?$/, () =>
    HttpResponse.json({ detail: "No refresh cookie" }, { status: 401 }),
  ),
];

export const server = setupServer(...handlers);
