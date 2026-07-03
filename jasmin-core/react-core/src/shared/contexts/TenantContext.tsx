import type { ReactNode } from "react";
import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Tenant, TenantSettingsToDict } from "@shared/api/generated/models";
import { isSuperAdminHostname } from "@shared/auth/superAdminHost";
import {
  tenantsCurrentRetrieve,
  tenantsTenantsRetrieve,
} from "@shared/api/generated/tenants/tenants";
import {
  getAccessToken,
  subscribeAccessToken,
} from "@shared/services/tokenStore";

/**
 * Local extension of the orval-generated ``Tenant`` type:
 *
 *   - **``slug``** — derived from the subdomain on the client, not on the
 *     wire. We attach it after every fetch.
 *   - **``settings`` / ``current_settings``** — widened to a free-form
 *     ``Record`` because ``getSetting(key)`` does dotted-key lookups
 *     against arbitrary ``TenantSettings`` columns that the generated
 *     ``TenantSettingsProperty`` enumerates more strictly than we use.
 *   - **Index signature** — accepts ad-hoc fields that exist on the
 *     backend response but aren't yet in the orval schema (i.e. the gap
 *     between a backend field addition and the next ``make
 *     generate-frontend-api`` run). Without it, every new ``Tenant``
 *     column would require a typing patch before the frontend could
 *     even read it.
 *
 * The net effect: every backend field auto-flows in via ``Tenant``; we
 * only maintain the *frontend-only* additions here.
 */
type TenantData = Omit<
  Tenant,
  "settings" | "current_settings" | "features"
> & {
  slug?: string;
  settings?: Record<string, unknown>;
  current_settings?: Record<string, unknown>;
  // Backend ships the active feature flags as a string list. The
  // generated ``TenantFeatures`` widens to ``unknown | null`` (the
  // OpenAPI schema models it as a JSONField), which would lose the
  // ``.includes(...)`` typing every consumer uses.
  features?: string[];
  [key: string]: unknown;
};

/**
 * The ``TenantSettings`` overlay exactly as the backend's ``to_dict()``
 * ships it. ``used_tiers_for_offers`` is a JSONField on the wire (the
 * generated alias is ``unknown``); the backend stores a list of tier
 * numbers, so it is narrowed here.
 */
type TenantOverlaySettings = Omit<
  TenantSettingsToDict,
  "used_tiers_for_offers"
> & {
  used_tiers_for_offers?: number[] | null;
};

/**
 * Every key ``getSetting`` can resolve with a KNOWN type: the tenant
 * scalars the backend merges into ``settings`` (mirrors
 * ``_merged_settings_dict`` in the tenants serializers) plus the full
 * ``TenantSettings`` overlay, which wins on key collisions.
 */
type TenantSettingMap = Pick<
  Tenant,
  | "currency"
  | "timezone"
  | "tenant_language"
  | "date_format"
  | "time_format"
  | "csv_format"
  | "number_locale"
  | "navigation"
  | "ai"
  | "allow_upload_for_data_lists"
> &
  TenantOverlaySettings;

/**
 * Overloaded setting getter: a literal known key returns its declared
 * type (``| null`` because the tenant payload may not have loaded yet
 * and the default value defaults to ``null``); any other string —
 * dotted paths like ``"navigation.show_members"`` included — stays on
 * the untyped ``unknown`` overload.
 */
interface TenantSettingGetter<SettingMap> {
  <K extends keyof SettingMap & string>(
    key: K,
    defaultValue?: SettingMap[K],
  ): SettingMap[K] | null;
  (key: string, defaultValue?: unknown): unknown;
}

interface TenantContextValue {
  tenant: TenantData | null;
  loading: boolean;
  error: string | null;
  tenantSlug: string | undefined;
  tenantName: string | undefined;
  tenantDescription: string | undefined;
  /** Read a merged tenant setting (tenant scalars + ``TenantSettings``
   * overlay). Known keys come back typed; dotted / dynamic keys fall
   * through to the ``unknown`` overload. */
  getSetting: TenantSettingGetter<TenantSettingMap>;
  /** Same lookup against the raw ``TenantSettings`` overlay only (no
   * tenant scalars merged in). */
  getCurrentSetting: TenantSettingGetter<TenantOverlaySettings>;
  getCurrency: () => unknown;
  getTimezone: () => unknown;
  logoUrl: string | null;
  /** ``logoUrl`` with a fallback to the bundled Jasmin logo when the tenant
   * has none — for UI chrome (nav bar, login, member/customer headers).
   * ``null`` when there is neither a tenant logo NOR the bundled fallback
   * file, so consumers render nothing (not a broken image). Documents/PDFs
   * keep using the raw ``logoUrl`` (a platform logo on a tenant's invoice
   * would be wrong). */
  displayLogoUrl: string | null;
  /** Resolved absolute URL for ``tenant.bio_logo`` (EU organic
   * certification mark). Same shape as ``logoUrl``: ``null`` when the
   * tenant has no bio logo uploaded. Used by invoice / delivery-note
   * PDFs to render the organic mark above the control-number
   * disclosure. */
  bioLogoUrl: string | null;
  faviconUrl: string | null;
  /** Re-fetch the current tenant + settings from the API. Use after a
   * save that mutates a Tenant column or a TenantSettings overlay value
   * so the next ``getSetting(...)`` returns the new value. */
  refreshTenant: () => Promise<void>;
  /** Fetch the full (auth-gated) tenant payload — IBAN/BIC, contact
   * info, and the ``settings`` / ``current_settings`` overlays that
   * ``getSetting(...)`` reads. The mount-time fetch hits the
   * anonymous ``/api/tenants/current/`` endpoint which only carries
   * the branding allowlist (login-page bootstrap). After login
   * completes, ``AuthContext`` ``await``s this to enrich the tenant
   * state with operational fields before redirecting.
   * No-op on the super-admin / platform domain. */
  refreshTenantFull: () => Promise<void>;
}

export const TenantContext = createContext<TenantContextValue | undefined>(
  undefined,
);

export function isPlatformDomain() {
  // Single source of truth for platform/super-admin host detection — the
  // env-driven leftmost-label check in ``superAdminHost.ts``. Both dev
  // (``<sub>.localhost``) and prod (``<sub>.domain.com``) collapse to that
  // one rule; a non-leftmost match (``tenant.<sub>.domain.com``) is a tenant.
  return isSuperAdminHostname(window.location.hostname);
}

export const TenantProvider = ({ children }: { children: ReactNode }) => {
  const [currentTenant, setCurrentTenant] = useState<TenantData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Get tenant from subdomain
  const getTenantFromDomain = useCallback(() => {
    const hostname = window.location.hostname;
    const subdomain = hostname.split(".")[0];

    // Handle specific subdomains
    if (hostname === "test.localhost" || hostname === "test_tenant.localhost") {
      return "test"; // Maps to test_tenant schema
    }

    if (hostname === "admin.localhost") {
      return "public"; // Maps to public schema for super admin
    }

    // For other subdomains, use the subdomain as tenant slug
    return subdomain;
  }, []);

  useEffect(() => {
    // Skip tenant loading if we're on the platform domain
    if (isPlatformDomain()) {
      setCurrentTenant(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const initTenant = async () => {
      try {
        setLoading(true);
        const tenantSlug = getTenantFromDomain();

        // Get tenant data from API
        const data = await tenantsCurrentRetrieve();
        if (cancelled) return;

        setCurrentTenant({
          ...(data as unknown as TenantData),
          slug: tenantSlug,
        });
      } catch (err) {
        if (cancelled) return;
        console.error("Failed to load tenant:", err);
        const error = err as Error & { code?: string };

        // Handle ad blocker or network issues
        if (
          error.code === "ERR_BLOCKED_BY_CLIENT" ||
          error.message === "Network Error"
        ) {
          console.warn("API blocked by ad blocker, using fallback tenant data");
          const tenantSlug = getTenantFromDomain();

          // Fallback tenant data
          setCurrentTenant({
            slug: tenantSlug,
            name: tenantSlug === "public" ? "Super Admin" : "Test Tenant",
            schema_name: tenantSlug === "test" ? "test_tenant" : tenantSlug,
          });
        } else {
          setError((err as Error).message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    initTenant();

    return () => {
      cancelled = true;
    };
  }, [getTenantFromDomain]);

  // Re-fetch the current tenant. Same logic as initTenant minus the
  // platform-domain bail-out and the loading flag (we don't want callers
  // to see a spinner just because they saved a setting).
  // Post-login enrichment: fetch the full (auth-gated) tenant row
  // from ``GET /api/tenants/tenants/<id>/`` and MERGE it into the
  // existing branding-only state. AuthContext ``await``s this after
  // ``setSession`` so any page rendered post-redirect has the full
  // tenant payload available (IBAN / BIC for invoice PDFs, ``settings``
  // overlays for ``getSetting(...)``, contact info for PDF headers,
  // etc.).
  //
  // The merge preserves the pre-login branding fields verbatim — the
  // full payload is a strict superset, but keeping the spread order
  // explicit makes the dependency obvious and tolerates future
  // divergence (e.g. a field that only the branding endpoint computes).
  const refreshTenantFull = useCallback(async () => {
    if (isPlatformDomain()) return;
    const tenantId = currentTenant?.id;
    if (!tenantId) {
      // Initial bootstrap fetch hasn't completed yet (or failed). The
      // branding endpoint always returns ``id``, so the absence here
      // means we have nothing to enrich.
      console.warn(
        "refreshTenantFull: no tenant id available; skipping post-login fetch",
      );
      return;
    }
    try {
      const fullData = await tenantsTenantsRetrieve(tenantId);
      setCurrentTenant((prev) => ({
        ...(prev ?? {}),
        ...(fullData as unknown as TenantData),
        // Preserve the slug we computed from the subdomain (server
        // response carries ``schema_name`` not ``slug``).
        slug: prev?.slug,
      }));
    } catch (err) {
      // Non-fatal — the user is logged in either way. Sidebars that
      // depend on ``getSetting(...)`` will fall back to their default
      // values until the next refresh succeeds.
      console.error("Failed to refresh full tenant:", err);
    }
  }, [currentTenant?.id]);

  // Boot-time race fix: ``initTenant`` (anonymous slim fetch) and
  // ``AuthContext``'s silent refresh run concurrently. AuthContext
  // calls ``refreshTenantFull()`` as soon as the silent refresh
  // resolves, but if the slim fetch hasn't returned yet,
  // ``currentTenant?.id`` is undefined and ``refreshTenantFull``
  // bails. With no re-trigger, the ``settings`` overlay (footer text,
  // entry lines, etc.) stayed empty until the user manually saved
  // something — which is what made hard-reload still produce a PDF
  // without a footer even though the data was in TenantSettings.
  //
  // This effect deterministically runs the full fetch once per
  // tenant id, regardless of which boot path won the race. The ref
  // guard prevents the effect from re-firing on the state update
  // that ``refreshTenantFull`` itself causes (merge into
  // ``currentTenant``).
  const fullFetchedForIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!currentTenant?.id) return;
    if (fullFetchedForIdRef.current === currentTenant.id) return;

    // Hard-reload race: the anonymous slim tenant fetch can complete
    // BEFORE the silent JWT refresh seeds the access token. Firing
    // ``refreshTenantFull()`` here without a token produced an
    // immediate 401 → silent-refresh → retry path that worked
    // functionally but littered the devtools console with red 401s.
    // Defer until the token is present; subscribe so we re-run the
    // effect's body the moment the silent refresh lands.
    if (!getAccessToken()) {
      const unsubscribe = subscribeAccessToken((token) => {
        if (!token) return;
        // ``currentTenant.id`` is ``string | undefined`` on the
        // generated ``Tenant`` model; the ref is ``string | null``.
        // Capture into a local + null-coalesce so the type narrows
        // and the assignment is sound. The ``return`` above already
        // guarantees ``currentTenant`` is non-null.
        const tenantId = currentTenant.id ?? null;
        if (fullFetchedForIdRef.current === tenantId) return;
        fullFetchedForIdRef.current = tenantId;
        refreshTenantFull();
        unsubscribe();
      });
      return unsubscribe;
    }

    fullFetchedForIdRef.current = currentTenant.id;
    refreshTenantFull();
    // ``refreshTenantFull`` reads ``currentTenant?.id`` from its own
    // closure; the ref guard above is what prevents the effect from
    // re-firing on every state update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTenant?.id]);

  // Re-fetch after a mutation that may have changed any tenant field.
  // When we already know the tenant id (i.e. we're past the pre-login
  // bootstrap) the auth-gated full payload is the authoritative source
  // — it carries the ``settings`` / ``current_settings`` overlays that
  // ``getSetting(...)`` reads. Calling the anonymous slim endpoint here
  // instead REPLACES the tenant state with the branding allow-list and
  // silently wipes the settings overlay, so a subsequent
  // ``getSetting("use_personalized_offers", true)`` (or any other
  // overlay key) would fall back to its hard-coded default and look
  // like a "save didn't take" bug to office users — see audit playbook
  // for context.
  //
  // Pre-id bootstrap (no auth, no tenant resolved yet): fall through to
  // the slim anonymous endpoint just to pull branding for the login
  // page.
  const refreshTenant = useCallback(async () => {
    if (isPlatformDomain()) return;
    if (currentTenant?.id) {
      await refreshTenantFull();
      return;
    }
    try {
      const tenantSlug = getTenantFromDomain();
      const data = await tenantsCurrentRetrieve();
      setCurrentTenant({
        ...(data as unknown as TenantData),
        slug: tenantSlug,
      });
    } catch (err) {
      console.error("Failed to refresh tenant:", err);
    }
  }, [currentTenant?.id, refreshTenantFull, getTenantFromDomain]);

  // Get tenant setting. One directional cast to the overloaded getter:
  // the dynamic dotted-key walk is inherently untyped, the overload
  // re-attaches the known-key types at the call sites.
  const getSetting = useCallback(
    (key: string, defaultValue: unknown = null) => {
      if (!currentTenant?.settings) return defaultValue;

      // Support nested keys like 'members.allows_trial_members'
      const keys = key.split(".");
      let value: unknown = currentTenant.settings;

      for (const k of keys) {
        if (value && typeof value === "object" && k in value) {
          value = (value as Record<string, unknown>)[k];
        } else {
          return defaultValue;
        }
      }

      return value;
    },
    [currentTenant],
  ) as TenantSettingGetter<TenantSettingMap>;

  const getCurrentSetting = useCallback(
    (key: string, defaultValue: unknown = null) => {
      if (!currentTenant?.current_settings) return defaultValue;

      const keys = key.split(".");
      let value: unknown = currentTenant.current_settings;

      for (const k of keys) {
        if (value && typeof value === "object" && k in value) {
          value = (value as Record<string, unknown>)[k];
        } else {
          return defaultValue;
        }
      }

      return value;
    },
    [currentTenant],
  ) as TenantSettingGetter<TenantOverlaySettings>;

  // Get currency for current tenant
  const getCurrency = useCallback(() => {
    return getSetting("currency", "EUR");
  }, [getSetting]);

  // Get timezone for current tenant
  const getTimezone = useCallback(() => {
    return getSetting("timezone", "UTC");
  }, [getSetting]);

  const logoUrl = useMemo(() => {
    const logo = currentTenant?.logo;
    if (!logo) return null;

    if (logo.startsWith("http://") || logo.startsWith("https://")) {
      return logo;
    }

    const backendUrl = import.meta.env.VITE_API_URL || "";
    return `${backendUrl}${logo}`;
  }, [currentTenant?.logo]);

  // UI fallback: when the tenant has uploaded no logo, show the bundled
  // Jasmin logo (public/jasmin_logo.png) so nav/login/headers aren't blank.
  // If that bundled file is ALSO absent, fall through to null so consumers
  // render nothing instead of a broken-image icon. Optimistic: assume it's
  // present (no first-paint flicker) and only drop to null if the probe 404s.
  const [fallbackLogoMissing, setFallbackLogoMissing] = useState(false);
  useEffect(() => {
    const img = new Image();
    img.onerror = () => setFallbackLogoMissing(true);
    img.src = "/jasmin_logo.png";
    return () => {
      img.onerror = null;
    };
  }, []);
  const displayLogoUrl =
    logoUrl ?? (fallbackLogoMissing ? null : "/jasmin_logo.png");

  // Same resolver as ``logoUrl`` for the organic-certification mark.
  const bioLogoUrl = useMemo(() => {
    const bioLogo = currentTenant?.bio_logo;
    if (!bioLogo) return null;

    if (bioLogo.startsWith("http://") || bioLogo.startsWith("https://")) {
      return bioLogo;
    }

    const backendUrl = import.meta.env.VITE_API_URL || "";
    return `${backendUrl}${bioLogo}`;
  }, [currentTenant?.bio_logo]);

  // NB: we intentionally do NOT <link rel="preload"> the logo. Protected-media
  // URLs carry a per-sign `?st=` token (TimestampSigner), so the URL the slim
  // tenant fetch yields differs from the one after ``refreshTenantFull``
  // re-signs it — the preloaded link was always superseded and the browser
  // logged "preloaded but not used". The login <img> already sets
  // `fetchpriority="high"`, which is the correct LCP signal here.

  // The tenant logo doubles as the browser tab icon. Modern browsers
  // accept any image format (PNG, SVG, ...) and scale it down to favicon
  // size — no separate upload needed.
  const faviconUrl = logoUrl;

  // Push the URL into a live <link rel="icon"> in the document head so
  // the browser actually picks it up. The static <link> in index.html
  // is a placeholder; without this effect, every tenant would show the
  // same tab icon.
  useEffect(() => {
    if (!faviconUrl) return;
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    const previousHref = link.href;
    link.href = faviconUrl;
    return () => {
      if (link) link.href = previousHref;
    };
  }, [faviconUrl]);

  const value = useMemo<TenantContextValue>(
    () => ({
      // Current tenant data
      tenant: currentTenant,
      loading,
      error,

      // Tenant info
      tenantSlug: currentTenant?.slug,
      tenantName: currentTenant?.name,
      tenantDescription: currentTenant?.description ?? undefined,

      // Settings
      getSetting,
      getCurrentSetting,
      getCurrency,
      getTimezone,
      logoUrl,
      displayLogoUrl,
      bioLogoUrl,
      faviconUrl,

      // Actions
      refreshTenant,
      refreshTenantFull,
    }),
    [
      currentTenant,
      loading,
      error,
      getSetting,
      getCurrentSetting,
      getCurrency,
      getTimezone,
      logoUrl,
      displayLogoUrl,
      bioLogoUrl,
      faviconUrl,
      refreshTenant,
      refreshTenantFull,
    ],
  );

  return (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  );
};
