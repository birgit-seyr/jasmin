import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import axiosInstance, { performRefresh } from "@shared/services/api";
import {
  SUPER_ADMIN_AUTH_ENDPOINTS,
  TENANT_AUTH_ENDPOINTS,
  type AuthEndpoints,
} from "@shared/services/authEndpoints";
import { isSuperAdminHostname as isSuperAdminHost } from "@shared/auth/superAdminHost";
import { getErrorMessage } from "@shared/utils/apiError";
import type {
  LoginOrChallengeResponse,
  LoginRequest,
  LoginResponse,
  PublicRegisterRequest,
  PublicRegisterResponse,
} from "@shared/api/generated/models";
import {
  clearAccessToken,
  getAccessToken as getStoredAccessToken,
  setAccessToken as setStoredAccessToken,
  subscribeAccessToken,
} from "@shared/services/tokenStore";
import { TenantContext } from "./TenantContext";

/**
 * User metadata cached by the context. Deliberately LOOSER than the
 * generated ``LoginUser``: ``setSession`` / ``getUser`` also carry the
 * super-admin user shape, which has no ``roles`` / ``user_language`` /
 * ``member_id`` — so everything beyond ``id`` stays optional.
 */
interface AuthUser {
  id: string;
  permissions?: string[];
  roles?: string[];
  user_language?: string;
  theme?: string;
  sidebar_collapsed?: boolean;
  edit_mode?: string;
  member_id?: string | null;
  [key: string]: unknown;
}

/**
 * Data persisted in localStorage under the "auth" key.
 *
 * IMPORTANT: this object intentionally contains NO tokens. The access token
 * lives in `tokenStore` (memory only) and the refresh token lives in an
 * HttpOnly cookie set by Django. Only non-sensitive user metadata is stored
 * here so the UI can hydrate quickly on a hard reload before the silent
 * refresh completes.
 */
interface AuthMetadata {
  user?: AuthUser;
  [key: string]: unknown;
}

interface AuthContextValue {
  user: AuthUser | null;
  permissions: string[];
  userRole: string | null;
  loading: boolean;
  /** True only during the initial silent-refresh boot (NOT per-action). The
   * full-screen app loader gates on this so login actions don't remount the
   * page. */
  bootstrapping: boolean;
  error: string | null;
  isAuthenticated: boolean;
  isSuperAdmin: boolean;
  accessToken: string | null;
  hasPermission: (permission: string) => boolean;
  hasRole: (role: string | string[]) => boolean | undefined;
  /** ``/api/auth/login/`` returns ONE of two shapes: the completed
   *  login (``{ access, user, tenant }``) or, when the account has 2FA
   *  active, ``{ requires_2fa, challenge_token }`` — branch with a
   *  ``"requires_2fa" in response`` check before touching ``access``. */
  login: (data: LoginRequest) => Promise<LoginOrChallengeResponse>;
  /** Second step of login when ``login`` returned the 2FA challenge.
   *  Resolves with the completed login shape — caller doesn't need to
   *  redirect, this handles it. */
  verifyTwoFactor: (data: {
    challenge_token: string;
    code: string;
  }) => Promise<LoginResponse>;
  register: (data: PublicRegisterRequest) => Promise<PublicRegisterResponse>;
  logout: () => Promise<void>;
  refreshAccessToken: () => Promise<string>;
  /** Allows external pages (e.g. SuperAdminLoginPage) to seed the context
   *  after performing the login call themselves. */
  setSession: (access: string, user?: AuthUser) => void;
  /** Merge partial fields into the cached user metadata (e.g. after a
   *  profile edit). Persists to localStorage. */
  updateUser: (partial: Partial<AuthUser>) => void;
  getUser: () => AuthUser | null;
  getAccessToken: () => string | null;
  isSuperAdminDomain: boolean;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

// ---- Hostname helpers ----------------------------------------------------
function getEndpoints(): AuthEndpoints {
  return isSuperAdminHost(window.location.hostname)
    ? SUPER_ADMIN_AUTH_ENDPOINTS
    : TENANT_AUTH_ENDPOINTS;
}

// ---- Provider ------------------------------------------------------------
export function AuthProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<AuthMetadata | null>(null);
  // Mirror tokenStore into React state so consumers re-render on token change.
  const [accessToken, setAccessTokenState] = useState<string | null>(
    getStoredAccessToken(),
  );
  const [loading, setLoading] = useState(true);
  // ``loading`` doubles as the per-action spinner (login / verifyTwoFactor /
  // register all toggle it), so it flips on every auth action. ``bootstrapping``
  // is true ONLY during the initial silent-refresh boot. The full-screen app
  // gate must use THIS — gating on ``loading`` unmounts the login page on every
  // submit, which drops the 2FA step state (the credentials form reappears
  // instead of the code field).
  const [bootstrapping, setBootstrapping] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  // ``useContext`` (NOT ``useTenant``) because the super-admin domain
  // mounts ``AuthProvider`` WITHOUT a ``TenantProvider`` wrapper, so the
  // hook returning undefined is the expected case there. Tenant
  // subdomains always have both providers (see ``App.jsx``).
  const tenantCtx = useContext(TenantContext);

  // Keep React state in sync with the underlying tokenStore.
  // If the token is cleared from outside (e.g. api.ts response interceptor
  // after a failed silent refresh), also drop the cached user metadata so
  // pages reading `user` flip to the logged-out state immediately — without
  // requiring a hard browser reload.
  useEffect(() => {
    return subscribeAccessToken((t) => {
      setAccessTokenState(t);
      if (t === null) {
        setMeta(null);
        try {
          localStorage.removeItem("auth");
        } catch {
          /* no-op */
        }
      }
    });
  }, []);

  // Hydrate user metadata from localStorage and attempt silent refresh on boot.
  useEffect(() => {
    try {
      const storedMeta = localStorage.getItem("auth");
      if (storedMeta) {
        setMeta(JSON.parse(storedMeta) as AuthMetadata);
      }
    } catch (err) {
      console.error("Failed to parse stored auth metadata:", err);
      localStorage.removeItem("auth");
    }

    // Best-effort silent refresh. If the HttpOnly refresh cookie is still
    // valid, we recover an access token without prompting login. Failure is
    // expected and silent for logged-out users.
    //
    // We delegate to `performRefresh()` from api.ts so this call is
    // deduplicated with any 401-triggered refresh that other providers
    // (e.g. TenantContext) may fire in parallel during boot. Without that
    // dedup, ROTATE_REFRESH_TOKENS would blacklist the cookie between the
    // two calls and force-log-out the user on every page reload.
    let cancelled = false;
    (async () => {
      try {
        await performRefresh();
        // Silent refresh succeeded → we're authenticated. We deliberately do
        // NOT enrich the tenant context here. The deterministic effect in
        // TenantContext (keyed on the tenant id) owns post-refresh enrichment:
        // it runs the full auth-gated fetch exactly once, race-safely, as soon
        // as both the tenant id (anonymous slim fetch) and the access token
        // (this refresh) are present. Calling refreshTenantFull() here fired
        // before the slim fetch had resolved on a hard reload, so it only
        // logged a "no tenant id" warning and bailed — a pure no-op. The
        // explicit login path below keeps its awaited call because navigation
        // needs the full payload synchronously.
      } catch {
        // No refresh cookie or it's expired — user is logged out. The
        // pre-login branding fetch in TenantContext has already given
        // the login page everything it needs.
      } finally {
        if (!cancelled) {
          setLoading(false);
          setBootstrapping(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // Boot-once effect: this runs exactly once on AuthProvider mount to
    // attempt a silent refresh from the HttpOnly cookie. Empty deps are
    // intentional — it must fire once on mount, not on every re-render
    // (re-firing would trigger redundant silent refreshes that defeat the
    // dedup in `performRefresh`).
  }, []);

  const persistMeta = useCallback((data: AuthMetadata | null) => {
    if (data) {
      localStorage.setItem("auth", JSON.stringify(data));
    } else {
      localStorage.removeItem("auth");
    }
    setMeta(data);
  }, []);

  const setSession = useCallback(
    (access: string, user?: AuthUser) => {
      setStoredAccessToken(access);
      if (user) {
        persistMeta({ ...(meta ?? {}), user });
      }
      setError(null);
    },
    [meta, persistMeta],
  );

  const updateUser = useCallback(
    (partial: Partial<AuthUser>) => {
      const currentUser = meta?.user;
      if (!currentUser) return;
      const mergedUser = { ...currentUser, ...partial } as AuthUser;
      persistMeta({ ...(meta ?? {}), user: mergedUser });
    },
    [meta, persistMeta],
  );

  const _completePostLoginSuccess = useCallback(
    async (response: LoginResponse): Promise<void> => {
    const { access, user } = response;
    if (!access) {
      // Runtime guard against a server bug — the type says ``access`` is
      // always present on the completed-login shape.
      throw new Error("Login response missing access token");
    }
    // Spread: ``LoginUser`` is an interface (no implicit index signature),
    // the anonymous copy is structurally assignable to ``AuthUser``.
    setSession(access, { ...user });

    // Enrich the tenant context with the auth-gated payload
    // (IBAN/BIC, contact info, ``settings`` / ``current_settings``
    // overlays) BEFORE redirecting. The pre-login bootstrap only
    // carries the branding allowlist from ``CurrentTenantSerializer``;
    // post-redirect pages rely on ``getSetting(...)`` and ``tenant.iban``
    // being populated. ``await`` blocks navigation by a few ms — the
    // alternative is rendering pages with stale / missing fields. No-op
    // on the super-admin domain (no TenantProvider in scope).
    if (tenantCtx) {
      await tenantCtx.refreshTenantFull();
    }

    // Routing
    if (isSuperAdminHost(window.location.hostname)) {
      navigate("/admin");
    } else {
      const roles = user?.roles || [];
      const memberId = user?.member_id;
      if (roles.length === 1 && roles[0] === "member" && memberId) {
        navigate(`/members/members/${memberId}`);
      } else if (roles.length === 1 && roles[0] === "customer") {
        navigate("/customer");
      } else {
        navigate("/");
      }
    }
  }, [tenantCtx, navigate, setSession]);

  const login = useCallback(
    async (data: LoginRequest): Promise<LoginOrChallengeResponse> => {
      try {
        setLoading(true);
        setError(null);
        const endpoints = getEndpoints();
        // Raw axios (sanctioned): the login endpoint sets the HttpOnly
        // refresh cookie, which the orval client wrapper doesn't handle.
        const response = await axiosInstance.post<LoginOrChallengeResponse>(
          endpoints.login,
          data,
        );
        // 2FA branch — do NOT set the session yet. The LoginPage handles
        // the second step by calling ``verifyTwoFactor`` with the
        // ``challenge_token`` + 6-digit code. ``setLoading(false)`` runs
        // in the finally block so the form re-enables.
        if ("requires_2fa" in response.data) {
          return response.data;
        }
        await _completePostLoginSuccess(response.data);
        return response.data;
      } catch (err) {
        setError(getErrorMessage(err, "Login failed"));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [_completePostLoginSuccess],
  );

  const verifyTwoFactor = useCallback(
    async (data: {
      challenge_token: string;
      code: string;
    }): Promise<LoginResponse> => {
      try {
        setLoading(true);
        setError(null);
        const endpoints = getEndpoints();
        if (!endpoints.verify2fa) {
          throw new Error("2FA verify endpoint not available in this domain.");
        }
        // A successful verify always returns the completed login shape.
        const response = await axiosInstance.post<LoginResponse>(
          endpoints.verify2fa,
          data,
        );
        await _completePostLoginSuccess(response.data);
        return response.data;
      } catch (err) {
        setError(getErrorMessage(err, "Two-factor verification failed"));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [_completePostLoginSuccess],
  );

  const register = useCallback(
    async (data: PublicRegisterRequest): Promise<PublicRegisterResponse> => {
      try {
        setLoading(true);
        setError(null);
        const endpoints = getEndpoints();
        const response = await axiosInstance.post<PublicRegisterResponse>(
          endpoints.register,
          data,
        );
        // Registration creates a pending member application — the
        // response carries no tokens (the applicant can't log in until
        // approved), so there is no session to seed here.
        return response.data;
      } catch (err) {
        setError(getErrorMessage(err, "Registration failed"));
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      const endpoints = getEndpoints();
      // Empty body — refresh cookie carries the token. AllowAny on backend
      // means this still works even with an expired access token.
      await axiosInstance.post(endpoints.logout, {});
    } catch (err) {
      // Logout failures are non-fatal.
      console.error("Logout API call failed:", err);
    } finally {
      clearAccessToken();
      persistMeta(null);
      setError(null);
      // Wipe any cached API responses held by the service worker. Without
      // this, a NetworkFirst response that succeeded earlier could still be
      // served from cache to the next user on the same device.
      if (typeof window !== "undefined" && "caches" in window) {
        try {
          const names = await caches.keys();
          await Promise.all(
            names
              .filter((n) => n.includes("api-cache") || n.includes("auth"))
              .map((n) => caches.delete(n)),
          );
        } catch (err) {
          console.warn("Failed to clear SW caches on logout:", err);
        }
      }
      // Both realms (tenant + super-admin) mount the login route at /login.
      navigate("/login");
    }
  }, [navigate, persistMeta]);

  const refreshAccessToken = useCallback(async (): Promise<string> => {
    try {
      return await performRefresh();
    } catch (err) {
      console.error("Manual refresh failed:", err);
      clearAccessToken();
      throw err;
    }
  }, []);

  const getUser = useCallback((): AuthUser | null => meta?.user ?? null, [meta]);
  const getAccessToken = useCallback(
    (): string | null => accessToken,
    [accessToken],
  );
  const isAuthenticated = !!accessToken;

  const hasPermission = useCallback(
    (permission: string) => {
      const userPermissions = getUser()?.permissions || [];
      return userPermissions.includes(permission);
    },
    [getUser],
  );

  const hasRole = useCallback(
    (role: string | string[]) => {
      const u = getUser();
      if (Array.isArray(role)) return role.some((r) => u?.roles?.includes(r));
      return u?.roles?.includes(role);
    },
    [getUser],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user: getUser(),
      permissions: getUser()?.permissions || [],
      userRole: getUser()?.roles?.includes("admin")
        ? "admin"
        : getUser()?.roles?.[0] || null,
      loading,
      bootstrapping,
      error,
      isAuthenticated,
      isSuperAdmin:
        isSuperAdminHost(window.location.hostname) && isAuthenticated,
      accessToken,
      hasPermission,
      hasRole,
      login,
      verifyTwoFactor,
      register,
      logout,
      refreshAccessToken,
      setSession,
      updateUser,
      getUser,
      getAccessToken,
      isSuperAdminDomain: isSuperAdminHost(window.location.hostname),
    }),
    [
      loading,
      bootstrapping,
      error,
      isAuthenticated,
      accessToken,
      getUser,
      getAccessToken,
      hasPermission,
      hasRole,
      login,
      verifyTwoFactor,
      register,
      logout,
      refreshAccessToken,
      setSession,
      updateUser,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
