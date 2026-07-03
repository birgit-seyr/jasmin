/**
 * Auth endpoint URL maps.
 *
 * These are hand-wired (not Orval-generated) on purpose:
 *  - The super-admin endpoints live on the public schema, which
 *    ``make generate-schema`` (run under ``tenant_urls``) never emits,
 *    so there's no generated client for them at all.
 *  - The tenant auth routes drive ``AuthProvider``, which must run before
 *    the rest of the app (and thus before any generated query hook) is
 *    ready.
 *
 * Kept here, beside ``services/api.ts``, as the single source of truth so
 * the maps don't get re-hardcoded across ``AuthContext`` and the
 * super-admin login page.
 */

export interface AuthEndpoints {
  login: string;
  register: string;
  logout: string;
  refresh: string;
  /** ``null`` where the flow doesn't exist (super-admin has no 2FA verify). */
  verify2fa: string | null;
}

export const TENANT_AUTH_ENDPOINTS: AuthEndpoints = {
  login: "/api/auth/login/",
  register: "/api/auth/register/",
  logout: "/api/auth/logout/",
  refresh: "/api/auth/refresh/",
  verify2fa: "/api/auth/two-factor/verify/",
};

export const SUPER_ADMIN_AUTH_ENDPOINTS: AuthEndpoints = {
  login: "/api/super-admin/auth/login/",
  register: "/api/super-admin/auth/register/",
  logout: "/api/super-admin/auth/logout/",
  refresh: "/api/super-admin/auth/refresh/",
  verify2fa: null,
};
