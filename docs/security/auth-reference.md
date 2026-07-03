# Auth reference — HttpOnly refresh cookies

> **Status**: this is the canonical reference for how authentication
> works today. The original file was a "Chunk 1 migration plan"; the
> migration is done as of 2026, so the doc was rewritten in-place as
> a how-it-works reference. Future MFA work (Chunk 2+) lives in
> [`tasks.txt`](tasks.txt) and not here — this doc
> describes the **current** auth surface only.

## Token shape

Refresh tokens are stored in **HttpOnly, Secure, SameSite cookies** —
JavaScript cannot read them and the browser attaches them automatically
on requests to the matching path. Access tokens are short-lived (15 min)
and kept in a module-scoped variable in the SPA — never `localStorage`.

| Endpoint                              | Body shape                                                                  | Cookie behaviour                                                                                            |
| ------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `POST /api/auth/login/`               | request `{email, password}`; response `{access, user, tenant}` (no refresh) | sets `refresh_token` (Path=`/api/auth/`)                                                                    |
| `POST /api/auth/refresh/`             | request empty; response `{access, tenant?}`                                 | reads `refresh_token`; rotates → sets a fresh cookie; old jti is blacklisted                                |
| `POST /api/auth/logout/`              | request empty; response `{message}`                                         | reads `refresh_token`, blacklists it, clears the cookie. `AllowAny` so an expired-access logout still works |
| `POST /api/super-admin/auth/login/`   | same shape as tenant login                                                  | sets `sa_refresh_token` (Path=`/api/super-admin/`)                                                          |
| `POST /api/super-admin/auth/refresh/` | empty                                                                       | cookie-only                                                                                                 |
| `POST /api/super-admin/auth/logout/`  | empty                                                                       | cookie-only                                                                                                 |

Code references:
[`accounts/views.py`](../jasmin-core/django-core/apps/accounts/views.py) for tenant
login/refresh/logout,
[`shared/super_admin/views.py`](../jasmin-core/django-core/apps/shared/super_admin/views.py)
for the super-admin versions,
[`shared/auth_cookies.py`](../jasmin-core/django-core/apps/shared/auth_cookies.py)
for the cookie set/clear helpers.

Rotation is **enforced**: every successful refresh blacklists the
old refresh-token jti and issues a new one. Replaying an old refresh
token after rotation is rejected.

## Frontend integration

The SPA wires this up in [`react-core/src/services/api.ts`](../jasmin-core/react-core/src/services/api.ts) and [`react-core/src/services/tokenStore.ts`](../jasmin-core/react-core/src/services/tokenStore.ts). Summary:

### 1. `withCredentials: true` on the axios instance

```ts
const api = axios.create({ baseURL: "/api", withCredentials: true });
```

Without this, the browser will neither send nor accept the cookie.

### 2. Access token lives in memory only

```ts
// tokenStore.ts
let _access: string | null = null;
export const setAccessToken = (t: string | null) => {
  _access = t;
};
export const getAccessToken = () => _access;
```

A page reload wipes the access token; the refresh cookie persists,
and the silent-refresh on boot (#6 below) re-establishes the session.

### 3. Login

```ts
const { data } = await api.post("/auth/login/", { email, password });
// data = { access, user, tenant }   ← NO refresh
setAccessToken(data.access);
```

### 4. Auth header via interceptor

```ts
api.interceptors.request.use((cfg) => {
  const t = getAccessToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
```

### 5. Silent refresh on 401

```ts
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    if (error.response?.status === 401 && !error.config.__retried) {
      try {
        const { data } = await api.post("/auth/refresh/"); // empty body
        setAccessToken(data.access);
        error.config.__retried = true;
        error.config.headers.Authorization = `Bearer ${data.access}`;
        return api(error.config);
      } catch {
        setAccessToken(null);
        // hard redirect to /login
      }
    }
    return Promise.reject(error);
  },
);
```

`api.ts:performRefresh()` deduplicates concurrent refresh calls so a
page that fires N requests at once only POSTs to `/auth/refresh/`
once.

### 6. Silent refresh on app boot

The refresh cookie persists across page reloads; the in-memory access
token doesn't. The boot path tries one refresh — success means
"already logged in", failure means "not logged in":

```ts
useEffect(() => {
  api
    .post("/auth/refresh/")
    .then(({ data }) => setAccessToken(data.access))
    .catch(() => {
      /* not logged in */
    });
}, []);
```

### 7. Logout

```ts
await api.post("/auth/logout/"); // empty body
setAccessToken(null);
// clear any in-memory user state
```

### 8. Super-admin (admin.mydomain.com)

Identical pattern, but endpoints are under `/api/super-admin/auth/`
and the cookie is `sa_refresh_token` (Path=`/api/super-admin/`). You
never touch the cookie directly — `withCredentials: true` is all
the frontend needs.

## Dev environment notes

- The backend requires explicit CORS origins
  (`CORS_ALLOW_CREDENTIALS = True` cannot be combined with a `*`
  `Allow-Origin`). Allow-list: `http(s)://([sub.])?localhost(:port)`
  and the same for `127.0.0.1`. Configurable via
  `CORS_ALLOWED_ORIGINS`.
- In dev, cookies use `SameSite=Lax` and `Secure=False` so cross-port
  Vite → Django works without HTTPS. In production both are
  tightened to `SameSite=Strict` and `Secure=True` automatically
  (driven by `DEBUG` in [`shared/auth_cookies.py:32-49`](../jasmin-core/django-core/apps/shared/auth_cookies.py#L32-L49)).

## Security properties this gives you

| Attack                                            | Defence                                                                                                                  |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| XSS exfiltrates refresh token from `localStorage` | Impossible — the token is `HttpOnly`, never reachable from JS                                                            |
| XSS exfiltrates access token from memory          | Still possible within the 15-min access-token window. Mitigation is short lifetime + CSP; this is the accepted trade-off |
| CSRF posts to `/api/auth/refresh/`                | Blocked by `SameSite=Strict` in production                                                                               |
| Stolen old refresh token replayed after rotation  | Rejected — old jti is blacklisted on refresh                                                                             |

## What's NOT in this chunk

These are deliberate future work:

- **Super-admin IP allowlist** — _shipped_, but it lives at the nginx edge,
  not in this Django auth chunk: a dedicated server block + fail-closed
  `deny all;` allowlist, CI-verified by the `gateway` job. Design + operational
  steps: [`access-hardening.md`](access-hardening.md) Part 1.
- **Step-up auth on destructive endpoints** (delete tenant, role
  changes, GDPR deletes). Design: [`access-hardening.md`](access-hardening.md) Part 2.
- **TOTP MFA mandatory for super-admin.** Sits alongside step-up —
  the latter is the consumer of TOTP for destructive actions.

When any of those land, document them in a sibling file or extend
the relevant section above — don't reopen this doc as a migration
plan.
