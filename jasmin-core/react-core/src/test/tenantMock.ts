/**
 * Shared ``useTenant()`` mock for vitest. Returns a fully-shaped
 * object so any new field added to ``TenantContextValue`` doesn't
 * silently break tests that mock only a subset (which is what
 * happened when ``MemberDetail`` started reading ``getSetting`` —
 * every existing test that mocked only ``logoUrl`` started crashing
 * with "getSetting is not a function").
 *
 * Why a function-returning-object instead of a constant: callers
 * occasionally need per-test overrides (e.g. a tenant-specific
 * ``logoUrl``), and a function gives them ``makeUseTenantMock({...})``
 * sugar.
 *
 * Hoisting gotcha — ``vi.mock`` is hoisted to the top of the file
 * BEFORE imports run. Either use an async factory + dynamic import,
 * or use ``vi.hoisted``. The async-factory pattern is recommended:
 *
 *   vi.mock("@hooks/index", async () => {
 *     const { makeUseTenantMock } = await import(
 *       "../../../test/tenantMock"
 *     );
 *     const tenant = makeUseTenantMock();
 *     return {
 *       useTenant: () => tenant,
 *       // ...other hooks this file mocks
 *     };
 *   });
 *
 * Building ``tenant`` once outside the ``useTenant`` factory keeps the
 * returned object reference-stable across renders, which matters for
 * any downstream ``useCallback``/``useMemo`` deps that include it.
 *
 * Per-test override:
 *
 *   const tenant = makeUseTenantMock({
 *     logoUrl: "https://example.test/logo.png",
 *     getSetting: (key) => key === "uses_jokers" ? false : null,
 *   });
 */

export interface UseTenantMockShape {
  tenant: unknown;
  currentTenant: unknown;
  loading: boolean;
  error: unknown;
  tenantSlug: string | undefined;
  tenantName: string | undefined;
  tenantDescription: string | undefined;
  logoUrl: string | null;
  displayLogoUrl: string | null;
  faviconUrl: string | null;
  getSetting: (key: string, defaultValue?: unknown) => unknown;
  getCurrentSetting: (key: string, defaultValue?: unknown) => unknown;
  getCurrency: () => unknown;
  getTimezone: () => unknown;
  refreshTenant: () => Promise<void>;
}

export type UseTenantMockOverrides = Partial<UseTenantMockShape>;

export function makeUseTenantMock(
  overrides: UseTenantMockOverrides = {},
): UseTenantMockShape {
  return {
    tenant: null,
    currentTenant: null,
    loading: false,
    error: null,
    tenantSlug: undefined,
    tenantName: undefined,
    tenantDescription: undefined,
    logoUrl: null,
    displayLogoUrl: "/jasmin_logo.png",
    faviconUrl: null,
    // Passthrough: ``getSetting("uses_jokers", true)`` returns ``true``
    // — matches production defaults, so feature gates fall through
    // permissively in tests that don't care about them.
    getSetting: (_key: string, defaultValue?: unknown) => defaultValue,
    getCurrentSetting: (_key: string, defaultValue?: unknown) => defaultValue,
    getCurrency: () => "EUR",
    getTimezone: () => "UTC",
    refreshTenant: async () => {},
    ...overrides,
  };
}
