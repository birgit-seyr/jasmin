/**
 * In-memory access token store.
 *
 * The access token is intentionally kept OUT of localStorage / sessionStorage
 * so an XSS payload cannot exfiltrate it. The refresh token is never visible
 * to JavaScript at all — it lives in an HttpOnly cookie set by Django.
 *
 * The token is held in a module-scoped variable so any module that imports
 * `getAccessToken()` (e.g. the axios interceptor) sees the latest value
 * synchronously, without going through React state.
 *
 * On a hard reload the in-memory token is lost. AuthContext recovers it by
 * calling `/api/auth/refresh/` (or the super-admin equivalent) on boot — the
 * HttpOnly refresh cookie survives reloads, so the silent refresh succeeds
 * for any still-logged-in session.
 */

let _accessToken: string | null = null;

type Subscriber = (token: string | null) => void;
const subscribers = new Set<Subscriber>();

export function getAccessToken(): string | null {
  return _accessToken;
}

export function setAccessToken(token: string | null): void {
  _accessToken = token;
  subscribers.forEach((cb) => {
    try {
      cb(token);
    } catch (err) {
      console.error("tokenStore subscriber threw:", err);
    }
  });
}

export function clearAccessToken(): void {
  setAccessToken(null);
}

export function subscribeAccessToken(cb: Subscriber): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}
