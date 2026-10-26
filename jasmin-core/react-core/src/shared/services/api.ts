/// <reference types="vite/client" />
import axios, { AxiosError, AxiosRequestConfig } from "axios";
import type { LoginUser } from "@shared/api/generated/models";
import { isSuperAdminHostname } from "@shared/auth/superAdminHost";
import {
  getErrorCode,
  getErrorStatus,
  type JasminErrorPayload,
} from "@shared/utils/apiError";
import { runStepUpFlow } from "./stepUp";
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "./tokenStore";

const API_URL: string = import.meta.env.VITE_API_URL || "";

/** Detect which auth realm the current host belongs to. */
function isSuperAdminHost(): boolean {
  return isSuperAdminHostname(window.location.hostname);
}

function refreshEndpoint(): string {
  return isSuperAdminHost()
    ? "/api/super-admin/auth/refresh/"
    : "/api/auth/refresh/";
}

function loginRedirectPath(): string {
  // Note: super-admin app mounts its login at /login (not /super-admin/login).
  // Both realms use the bare /login path; the active app is decided by host.
  return "/login";
}

const axiosInstance = axios.create({
  baseURL: API_URL,
  // CRITICAL: send the HttpOnly refresh cookie on every API call. Without
  // this the cookie is dropped and silent refresh fails.
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

/**
 * What a successful refresh hands back: the new access token and, on the
 * tenant realm, the signed-in user as the login returned it. The super-admin
 * realm's answer carries no user.
 */
export interface RefreshedSession {
  access: string;
  user?: LoginUser;
}

interface QueueItem {
  resolve: (session: RefreshedSession) => void;
  reject: (reason?: unknown) => void;
}

let isRefreshing = false;
let failedQueue: QueueItem[] = [];

const processQueue = (
  error: unknown,
  session: RefreshedSession | null = null,
) => {
  failedQueue.forEach((p) => (error ? p.reject(error) : p.resolve(session!)));
  failedQueue = [];
};

// The tabs of one origin share the refresh cookie, and the backend blacklists
// a refresh token the moment it rotates it. Two tabs refreshing at once would
// both send the same cookie, and the slower one would lose its session. Under
// this lock they take turns, and the next tab sends the cookie the previous
// one got back. Every bundle has to ask for the same lock name.
const REFRESH_LOCK = "jasmin-auth-refresh";

// What the backend answers a refresh cookie it refuses: expired, revoked, or
// blacklisted because a tab outside the lock rotated it a moment ago (a tab
// still on an older bundle, or a browser without Web Locks). Only that last
// case is worth a second try, but the answer doesn't tell them apart.
const REFUSED_COOKIE_CODES = [
  "auth.invalid_token",
  "super_admin.refresh_token_invalid",
];

// How long a refused refresh waits before trying again, so the other tab's
// answer, which carries the new cookie, has landed.
const REFUSED_COOKIE_RETRY_DELAY_MS = 500;

async function postRefresh(): Promise<RefreshedSession> {
  const { data } = await axiosInstance.post<RefreshedSession>(
    refreshEndpoint(),
    {},
  );
  return data;
}

async function postRefreshWithRetry(): Promise<RefreshedSession> {
  try {
    return await postRefresh();
  } catch (error) {
    if (!REFUSED_COOKIE_CODES.includes(getErrorCode(error) ?? "")) throw error;
    await new Promise((resolve) =>
      setTimeout(resolve, REFUSED_COOKIE_RETRY_DELAY_MS),
    );
    return postRefresh();
  }
}

/**
 * Run `request` holding the cross-tab lock (see `REFRESH_LOCK`): after any
 * refresh in flight in this tab or another, and before the next. A logout
 * takes its turn too, or a refresh answered after it would set a new, valid
 * cookie. Web Locks are missing outside secure contexts and in older browsers;
 * there `request` runs without the lock.
 */
export async function inRefreshTurn<T>(request: () => Promise<T>): Promise<T> {
  if (!("locks" in navigator)) return request();
  return await navigator.locks.request(REFRESH_LOCK, request);
}

/**
 * Refresh the session, one POST at a time in this tab and across the tabs of
 * this origin (see `REFRESH_LOCK`).
 *
 * If a refresh is already in flight in this tab (e.g. triggered by a 401 from
 * another request), later callers wait on it instead of firing a second
 * `/auth/refresh/` POST, which would send the cookie the first one just had
 * blacklisted. A refresh that fails ends this tab's session.
 */
export async function performRefresh(): Promise<RefreshedSession> {
  if (isRefreshing) {
    return new Promise<RefreshedSession>((resolve, reject) => {
      failedQueue.push({ resolve, reject });
    });
  }
  isRefreshing = true;
  try {
    const session = await inRefreshTurn(postRefreshWithRetry);
    setAccessToken(session.access);
    processQueue(null, session);
    return session;
  } catch (err) {
    handleRefreshFailure(err);
    processQueue(err, null);
    throw err;
  } finally {
    isRefreshing = false;
  }
}

// ---- Request interceptor: attach access token -----------------------------
// No tenant header: the backend resolves the tenant from the subdomain
// (TenantMainMiddleware) — a client-sent header would never be read and would
// only imply a security mechanism that doesn't exist.
axiosInstance.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Public magic-link / entry pages a LOGGED-OUT user legitimately lands on via a
// URL (often a tokenized deep-link from an email). The boot-time silent refresh
// 401s for these users, and nudging them to /login would hijack the page —
// e.g. a member opening their waiting-list offer link, or an invitee setting a
// password. On these paths we clear the session but DON'T redirect; JasminApp's
// unauthenticated routes then render the page in place. Protected pages are not
// listed, so a mid-session expiry there still bounces to /login as intended.
const PUBLIC_PATHS = [
  "/login",
  "/register",
  "/forgot-password",
  "/privacy-policy",
  "/impressum",
];
const PUBLIC_PATH_PREFIXES = [
  "/set-password/",
  "/reset-password/",
  "/waiting-list-offer/",
];

function isPublicPath(pathname: string): boolean {
  return (
    PUBLIC_PATHS.includes(pathname) ||
    PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  );
}

// ---- Response interceptor: silent refresh on 401 -------------------------
function handleRefreshFailure(error: unknown) {
  // Refresh failed → user is logged out. Clear the in-memory token so
  // subscribers (AuthContext) flip `isAuthenticated` to false; the
  // route guards in JasminApp / SuperAdminApp will then render the
  // login page in place. We avoid `window.location.href` here because
  // a hard navigation during an error path can leave React mid-render
  // and produce a blank page.
  clearAccessToken();
  // The stored user metadata belongs to every tab of this origin, as the
  // refresh cookie does. Drop it only when the server refused that cookie,
  // which ends the session in every tab; a refresh that got no answer or hit
  // a server error leaves the other tabs signed in.
  if (getErrorStatus(error) === 401) {
    try {
      localStorage.removeItem("auth");
    } catch {
      /* no-op */
    }
  }
  // Best effort: nudge the URL to /login so the back-stack is sane — but NOT
  // on public deep-link pages, where a logged-out visitor belongs (redirecting
  // them would break the emailed offer / set-password / reset links).
  try {
    if (
      typeof window !== "undefined" &&
      !isPublicPath(window.location.pathname)
    ) {
      window.history.replaceState({}, "", loginRedirectPath());
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  } catch {
    /* no-op */
  }
}

axiosInstance.interceptors.response.use(
  (response) => response,
  // Error bodies follow the canonical Jasmin error payload produced by
  // ``core.exception_handler`` — declaring it here types the step-up
  // branch below without per-site casts.
  async (error: AxiosError<JasminErrorPayload>) => {
    const originalRequest = error.config as
      | (AxiosRequestConfig & {
          _retry?: boolean;
          _stepUpRetry?: boolean;
          _stepUpTokenRetry?: boolean;
        })
      | undefined;

    // A failing refresh POST is never answered with another refresh. It is
    // performRefresh's to handle: that may try it again, and logs the user
    // out once it gives up.
    const reqUrl = originalRequest?.url ?? "";
    if (reqUrl.includes("/auth/refresh/")) {
      return Promise.reject(error);
    }

    // ---- Step-up auth: 403 with code ``auth.step_up_required`` -----------
    // The server is saying "this destructive endpoint needs a fresh
    // password re-confirmation". Pop the modal via StepUpProvider, swap
    // in the rotated access token, and retry the original request.
    //
    // Guard with ``_stepUpRetry`` so a misconfigured server that keeps
    // returning the gate even after step-up can't loop us. Don't try
    // step-up on the step-up endpoint itself — that would deadlock.
    if (
      originalRequest &&
      !originalRequest._stepUpRetry &&
      error.response?.status === 403 &&
      getErrorCode(error) === "auth.step_up_required" &&
      !reqUrl.includes("/auth/step-up/")
    ) {
      // A step-up flow may have completed while this request was in
      // flight (it was sent with the pre-step-up token, the modal was
      // confirmed, THEN this 403 arrived). Retry once with the current
      // token before prompting again — re-asking for the password
      // seconds after the user confirmed it would be wrong. Separate
      // ``_stepUpTokenRetry`` flag so a second step-up 403 on that
      // retry still falls through to the prompt below.
      const sentAuthorization: unknown = originalRequest.headers?.Authorization;
      const currentToken = getAccessToken();
      if (
        !originalRequest._stepUpTokenRetry &&
        currentToken &&
        sentAuthorization !== `Bearer ${currentToken}`
      ) {
        originalRequest._stepUpTokenRetry = true;
        originalRequest.headers = {
          ...(originalRequest.headers ?? {}),
          Authorization: `Bearer ${currentToken}`,
        };
        return axiosInstance(originalRequest);
      }

      originalRequest._stepUpRetry = true;
      try {
        // ``details`` is a free-form record — narrow the TTL before use.
        const ttlSeconds = error.response.data.details?.ttl_seconds;
        const access = await runStepUpFlow({
          ttlSeconds: typeof ttlSeconds === "number" ? ttlSeconds : 300,
          refresh: performRefresh,
        });
        originalRequest.headers = {
          ...(originalRequest.headers ?? {}),
          Authorization: `Bearer ${access}`,
        };
        return axiosInstance(originalRequest);
      } catch {
        // User cancelled the modal, or step-up itself failed. Surface
        // the original 403 — the caller's existing error UI is the
        // right place to show "action not authorised" rather than
        // chaining a less informative step-up error.
        return Promise.reject(error);
      }
    }

    // Login / register / logout failures must NEVER trigger a silent refresh.
    // The user has no valid session yet (login/register) or is intentionally
    // ending it (logout); chaining into /auth/refresh/ would either replace
    // the real error with a useless "no refresh cookie" message or rotate a
    // cookie we're about to invalidate.
    if (
      reqUrl.includes("/auth/login/") ||
      reqUrl.includes("/auth/register/") ||
      reqUrl.includes("/auth/logout/") ||
      // 2FA verify is the second step of login — same reasoning. The
      // user holds no access token yet, so a silent refresh would either
      // 401 again (no cookie) or, worse, succeed against a leftover
      // session from a different account.
      reqUrl.includes("/auth/two-factor/verify/")
    ) {
      return Promise.reject(error);
    }

    if (
      !originalRequest ||
      error.response?.status !== 401 ||
      originalRequest._retry
    ) {
      return Promise.reject(error);
    }

    if (isRefreshing) {
      return performRefresh().then(({ access }) => {
        originalRequest.headers = {
          ...(originalRequest.headers ?? {}),
          Authorization: `Bearer ${access}`,
        };
        return axiosInstance(originalRequest);
      });
    }

    originalRequest._retry = true;

    // A failed refresh has logged the user out by the time it rejects.
    const { access } = await performRefresh();
    originalRequest.headers = {
      ...(originalRequest.headers ?? {}),
      Authorization: `Bearer ${access}`,
    };
    return axiosInstance(originalRequest);
  },
);

// Export for Orval (must return a Promise)
export const axiosService = <T>(config: AxiosRequestConfig): Promise<T> => {
  const source = axios.CancelToken.source();
  const promise = axiosInstance({
    ...config,
    cancelToken: source.token,
  }).then(({ data }) => data as T);

  (promise as Promise<T> & { cancel: () => void }).cancel = () => {
    source.cancel("Query was cancelled");
  };

  return promise;
};

export default axiosInstance;
