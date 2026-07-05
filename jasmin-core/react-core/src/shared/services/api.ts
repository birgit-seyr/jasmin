/// <reference types="vite/client" />
import axios, { AxiosError, AxiosRequestConfig } from "axios";
import { isSuperAdminHostname } from "@shared/auth/superAdminHost";
import { getErrorCode, type JasminErrorPayload } from "@shared/utils/apiError";
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

interface QueueItem {
  resolve: (value: string | PromiseLike<string>) => void;
  reject: (reason?: unknown) => void;
}

let isRefreshing = false;
let failedQueue: QueueItem[] = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach((p) => (error ? p.reject(error) : p.resolve(token!)));
  failedQueue = [];
};

/**
 * Perform a single refresh call, deduplicated across concurrent callers.
 *
 * If a refresh is already in flight (e.g. triggered by a 401 from another
 * request), subsequent callers wait on the same promise instead of firing a
 * second `/auth/refresh/` POST. This avoids a race with
 * `ROTATE_REFRESH_TOKENS` where the first call rotates the cookie and the
 * second hits the blacklist → user gets force-logged-out on page reload.
 */
export async function performRefresh(): Promise<string> {
  if (isRefreshing) {
    return new Promise<string>((resolve, reject) => {
      failedQueue.push({ resolve, reject });
    });
  }
  isRefreshing = true;
  try {
    const { data } = await axiosInstance.post<{ access: string }>(
      refreshEndpoint(),
      {},
    );
    setAccessToken(data.access);
    processQueue(null, data.access);
    return data.access;
  } catch (err) {
    processQueue(err, null);
    throw err;
  } finally {
    isRefreshing = false;
  }
}

// ---- Request interceptor: attach access token -----------------------------
// No tenant header: the backend resolves the tenant from the subdomain
// (TenantMainMiddleware) — a client-sent header was never read and only
// implied a security mechanism that didn't exist.
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
const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/privacy-policy"];
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
function handleRefreshFailure() {
  // Refresh failed → user is logged out. Clear the in-memory token so
  // subscribers (AuthContext) flip `isAuthenticated` to false; the
  // route guards in JasminApp / SuperAdminApp will then render the
  // login page in place. We avoid `window.location.href` here because
  // a hard navigation during an error path can leave React mid-render
  // and produce a blank page.
  clearAccessToken();
  try {
    localStorage.removeItem("auth");
  } catch {
    /* no-op */
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

    // ANY non-2xx (or network error) on the refresh endpoint itself means
    // the session is over. Don't try to recover, just log the user out.
    // This covers 401 (expected), 5xx (server hiccup), 0 (network error),
    // and anything weird returned by an intermediary (e.g. service worker).
    const reqUrl = originalRequest?.url ?? "";
    if (reqUrl.includes("/auth/refresh/")) {
      handleRefreshFailure();
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
        const ttlSeconds = error.response?.data?.details?.ttl_seconds;
        const access = await runStepUpFlow({
          ttlSeconds: typeof ttlSeconds === "number" ? ttlSeconds : 300,
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
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      })
        .then((token) => {
          originalRequest.headers = {
            ...(originalRequest.headers ?? {}),
            Authorization: `Bearer ${token}`,
          };
          return axiosInstance(originalRequest);
        })
        .catch((err) => Promise.reject(err));
    }

    originalRequest._retry = true;

    try {
      const access = await performRefresh();
      originalRequest.headers = {
        ...(originalRequest.headers ?? {}),
        Authorization: `Bearer ${access}`,
      };
      return axiosInstance(originalRequest);
    } catch (refreshError) {
      handleRefreshFailure();
      return Promise.reject(refreshError);
    }
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
