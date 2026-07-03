# Access hardening — super-admin + destructive endpoints

Two controls that protect the highest-blast-radius surfaces of the
platform: the **super-admin host** (can drop tenant schemas, manage
backups, run platform-wide ops) and the small set of **destructive
endpoints** that long-lived sessions shouldn't be able to fire without
re-proving identity.

These are layered, not alternative:

```
                          ┌─────────────────────────────┐
                          │  IP allowlist (nginx edge)  │  ← who can REACH the host
                          └──────────────┬──────────────┘
                                         │
                          ┌──────────────▼──────────────┐
                          │  JWT auth + IsSuperAdmin    │  ← who YOU are
                          └──────────────┬──────────────┘
                                         │
                          ┌──────────────▼──────────────┐
                          │  Step-up auth on destructive │  ← did you JUST prove it?
                          │  endpoints (5-min sudo TTL)  │
                          └─────────────────────────────┘
```

Status (2026-06-15):
- IP allowlist — **wired, fail-closed, and CI-verified.** The dedicated nginx
  server block and the `deny all;` allowlist ship in the repo; the file is not
  "empty" — until an operator adds `allow` lines it returns 403 to every IP, so
  the control is *active* (a usable "don't ship to prod without filling it in"
  lockdown). The `gateway` CI job + `scripts/verify_super_admin_allowlist.sh`
  assert the dedicated block, the allowlist `include`, and the fail-closed deny
  stay wired so the control can't silently regress (super-admins skip 2FA on
  the strength of it).
- Step-up auth — **shipped, gating 3 endpoints** (GDPR approve-deletion,
  super-admin role grant, super-admin backup-trigger). See Part 2 for the
  current shape and the rollout checklist for extending it.

---

## Part 1 — Super-admin IP allowlist

### What's already in place

| Piece | Where | Status |
|---|---|---|
| Dedicated nginx `server` block for the admin host | [`nginx/nginx.conf.template:278`](../../nginx/nginx.conf.template) | ✅ |
| `include /etc/nginx/super_admin_allowed_ips.conf;` | line 281 of the template | ✅ |
| Allowlist file with `deny all;` fallback | [`nginx/super_admin_allowed_ips.conf`](../../nginx/super_admin_allowed_ips.conf) | ✅ |
| Allowlist file pre-populated with operator IPs | the file | ❌ — currently only `deny all;` |
| CI guardrail keeping the above wired | [`scripts/verify_super_admin_allowlist.sh`](../../scripts/verify_super_admin_allowlist.sh) + `gateway` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) | ✅ |

So the path is already wired at the edge. Until at least one `allow`
line is added, the super-admin host returns **403 to every IP**, which
is itself a usable lockdown ("don't ship to prod without filling it
in"). With one `allow` line added, the host serves only the listed IPs.

### Operational steps

1. Find your current IP — `curl -s ifconfig.me` (IPv4) or `curl -s -6 ifconfig.me` (IPv6).
2. Edit [`nginx/super_admin_allowed_ips.conf`](../../nginx/super_admin_allowed_ips.conf):

   ```nginx
   allow 203.0.113.42;      # home
   allow 198.51.100.0/29;   # office /29
   allow 2001:db8::/64;     # IPv6 prefix
   deny all;                # keep this last
   ```

3. Reload nginx without a rebuild:
   `docker compose exec gateway nginx -s reload`.
   **Caveat:** this file is bind-mounted into the gateway as a *single
   file*, so an inode-replacing edit (vim, `sed -i`, `cp`) leaves the
   container serving the stale content even after `nginx -s reload`.
   After such an edit, run `docker compose restart gateway` instead (or
   append in place with `>>`). The durable fix is a directory bind-mount.
4. Verify: from an allowed IP, `https://admin.<FRONTEND_DOMAIN>` loads.
   From any other network (e.g. phone on 4G), the same URL returns 403.

### Threat model

| Attack | Caught here? | Notes |
|---|---|---|
| Credential stuffing / brute force against super-admin login | ✅ never reaches Django | `django-axes` lockout is a backup if this layer is ever bypassed |
| Stolen super-admin password used from attacker network | ✅ | Single most important property |
| Stolen super-admin password used from YOUR network (compromised laptop, phishing on your machine) | ❌ | Mitigated by future TOTP + step-up |
| Session fixation while you hold a valid session | ❌ | Mitigated by future step-up on destructive endpoints |
| Subdomain takeover of `admin.${FRONTEND_DOMAIN}` | ❌ | DNS / TLS concern, not IP |

### Operational caveats

- **Residential IPs rotate.** Most German residential ISPs reset the
  IPv4 at least every 24h. Options:
  - Telekom business static-IP add-on (~€5/mo).
  - Tailscale exit node from a small VPS — gives you a stable
    public IP without a residential static contract.
  - WireGuard tunnel to a Hetzner Cloud `cx11` (~€4/mo).
- **Mobile / travel breaks** unless tunnelled. Plan for this if you
  ever do on-call from a phone tether.
- **Lockout recovery.** If your IP ever rotates and you lose access
  before noticing, you'll be locked out of the host. Two escape
  hatches:
  - SSH to the prod box, edit the file, reload nginx (always
    available because SSH is on a different host firewall layer). If your
    edit replaces the file's inode (vim / `sed -i` / `cp`), the
    single-file bind-mount keeps the container on the stale copy after
    `nginx -s reload` — run `docker compose restart gateway` instead.
  - Keep a small VPS in the allowlist as a permanent jump host.

### Why it does NOT remove the TOTP-MFA TODO

The allowlist protects against attackers *not on your network*. It
does nothing against:
- Malware on your own machine that exfiltrates a session cookie.
- A coworker (future second super-admin) phishing-trained into typing
  the password on a clone domain.

TOTP-MFA closes the "stolen password from your own network" gap.
Track separately; don't conflate.

---

## Part 2 — Step-up auth on destructive endpoints

### The problem

JWT access tokens last 15 min, refresh tokens 7 days. That's the right
tradeoff for normal use — you don't want to re-login every hour — but
it means a session that's been alive for hours can fire **irreversible**
actions with no fresh proof of identity. A laptop left open at a café
or a compromised browser extension can do the same.

Step-up auth = "you've already authenticated to use the app, but before
**this specific action** you must re-prove identity right now."

### Shape

A single JWT claim drives everything:

```
"step_up_verified_at": <unix-timestamp>
```

When set and within `STEP_UP_TTL_SECONDS` (default 300s) of `now`, the
token is in "sudo mode" and gated endpoints accept the call.

### Currently gated endpoints

**Unconditional gates** (every write through these endpoints requires step-up):

| Endpoint | Role gate | Why gated |
|---|---|---|
| `POST /api/gdpr/admin/approve-deletion/<id>/` | `IsAdmin` (tenant) | Anonymises a member's PII — Art. 17 cannot be undone. |
| `PATCH /api/super-admin/tenants/<id>/users/<user_id>/roles/` | `IsSuperAdmin` | Grants office / admin within a tenant; classic privilege escalation. |
| `POST /api/super-admin/backups/trigger/` | `IsSuperAdmin` | Materialises a full encrypted DB dump on disk. |
| `POST /api/commissioning/bulk_send_invoice_remainders_via_email/` | `IsOffice` | Fans out reminder emails to every reseller — mass-spam / SMTP-abuse vector. |
| `POST /api/commissioning/bulk_send_offers_via_email/` | `IsOffice` | Fans out offer emails to selected resellers — same blast radius. |

**Field-conditional gates** (step-up fires only when the listed fields appear in the request payload):

| Endpoint | Sensitive fields | Why gated |
|---|---|---|
| `POST/PUT/PATCH /api/payments/billing_profiles/` | `iban`, `account_holder`, `sepa_mandate_reference`, `sepa_mandate_signed_at` | Mandate changes redirect direct-debit money. Editing the profile's `notes` or `is_active` flag bypasses the modal. |
| `POST/PUT/PATCH /api/commissioning/members/` | `iban`, `account_owner` | Legacy SEPA fields on the Member row — same risk. Office editing name / address / note PATCHes through unprompted. |

Wired via either `permission_classes=[..., RequiresStepUp]` (unconditional) or the
`requires_step_up_for_fields(*field_names)` factory (conditional) inside
the viewset's `get_permissions()`. The canonical "what's gated" lists:

- `_STEP_UP_ACTIONS` on [`TenantManagementViewSet`](../../jasmin-core/django-core/apps/shared/super_admin/viewsets.py).
- `_SEPA_SENSITIVE_FIELDS` on [`BillingProfileViewSet`](../../jasmin-core/django-core/apps/payments/viewsets.py) and [`MemberViewSet`](../../jasmin-core/django-core/apps/commissioning/viewsets/members_viewsets.py).
- `permission_classes` on each gated function-based view / `APIView`.

### Mechanism

**Permission class** [`apps/accounts/permissions.py`](../../jasmin-core/django-core/apps/accounts/permissions.py)::`RequiresStepUp`
- Reads `request.auth.payload.get("step_up_verified_at")`.
- Returns False (not raise) for anonymous callers so the 401 path
  wins ahead of any step-up prompt.
- Raises `StepUpRequired` when the claim is missing or older than
  `STEP_UP_TTL_SECONDS`, which the global handler maps to:

  ```json
  HTTP 403
  {
    "code": "auth.step_up_required",
    "message": "This action requires fresh authentication.",
    "details": { "ttl_seconds": 300 }
  }
  ```

**Step-up endpoints** — there are two siblings because tenant and
super-admin JWTs use different auth classes:

| Path | Auth | Use |
|---|---|---|
| `POST /api/auth/step-up/` | tenant JWT (`IsAuthenticated`) | Tenant office / admin re-confirms before approving GDPR deletion. |
| `POST /api/super-admin/auth/step-up/` | super-admin JWT (`SuperAdminJWTAuthentication`) | Super-admin re-confirms before role grants / backup triggers. |

Both:
- Take `{ password }` (and, when `STEP_UP_REQUIRES_TOTP=True`, `totp_code`).
- Re-validate via `user.check_password()` — separate from the login flow's
  `authenticate()` so step-up does NOT touch django-axes lockout counters.
  Step-up is reached only by users with a valid session, so brute force has
  to get past login first anyway.
- Mint a fresh access token via `AccessToken.for_user(user)` (tenant) or
  `AccessToken()` + claim copy (super-admin), carrying the existing
  identity claims plus the new `step_up_verified_at`.
- Return `{ access, ttl_seconds }`. The refresh token is **not**
  rotated — step-up affects the access token only.

Throttled under the `login` scope.

**Frontend interceptor** [`services/api.ts`](../../jasmin-core/react-core/src/services/api.ts) +
[`services/stepUp.ts`](../../jasmin-core/react-core/src/services/stepUp.ts) +
[`components/auth/StepUpProvider.tsx`](../../jasmin-core/react-core/src/components/auth/StepUpProvider.tsx):

- Axios response interceptor catches `403` with body `code:
  "auth.step_up_required"`.
- Deduplicates concurrent step-up requests — one modal even if 3
  destructive calls fire at once.
- `StepUpProvider` (mounted in [`App.jsx`](../../jasmin-core/react-core/src/App.jsx) inside
  both the tenant and platform branches) renders the password modal.
- After successful step-up the rotated access token replaces the
  in-memory one and the original request retries with the new
  `Authorization` header.
- The interceptor guards with `_stepUpRetry` so a misbehaving
  server can't loop the prompt, and skips itself on the step-up
  endpoint to prevent recursion.

### Settings

```python
# config/settings.py
STEP_UP_TTL_SECONDS = 300        # 5 minutes
STEP_UP_REQUIRES_TOTP = False    # flip to True once TOTP MFA ships
```

Both read from environment variables (`STEP_UP_TTL_SECONDS`,
`STEP_UP_REQUIRES_TOTP`) so per-tenant prod overrides are easy.

### What it does NOT cover

- Doesn't catch an attacker who has both your password AND your
  session AND is willing to type the password again into the step-up
  prompt. Mitigation: pair with TOTP (`STEP_UP_REQUIRES_TOTP=True`).
- Doesn't undo an already-fired destructive action. If you need
  reversibility, add a soft-delete + grace period instead of (or in
  addition to) step-up. Tenant deletion is a good candidate for soft
  delete with a 7-day undo window.

### Extending the gated list

Pick the variant that matches the endpoint's blast radius:

1. **Every write is irreversible** → unconditional `RequiresStepUp`.
   - Function-based / `APIView`: set `permission_classes = (RequiresStepUp,)`
     (composed with role permissions by `APIViewRolePermissionsMixin`).
   - ViewSet action: add the action name to a `_STEP_UP_ACTIONS`
     frozenset and append `RequiresStepUp()` in `get_permissions()`.
2. **Only some fields are sensitive** → conditional gate via
   `requires_step_up_for_fields(*field_names)`. Append the instance
   in `get_permissions()` and short-circuit on read methods + on
   writes that don't touch the listed fields. See
   [`BillingProfileViewSet`](../../jasmin-core/django-core/apps/payments/viewsets.py)
   for the canonical shape.
3. Add a test that the endpoint returns `403 auth.step_up_required`
   with no step-up claim, and succeeds with one (for unconditional
   gates), or that the gate fires only when sensitive fields appear
   in the payload (for conditional gates). Pattern in
   [`apps/accounts/tests/test_step_up.py`](../../jasmin-core/django-core/apps/accounts/tests/test_step_up.py).
4. Update the "Currently gated endpoints" tables above.

---

## Rollout order

The cheapest, highest-impact thing first:

1. **Add your IP to `super_admin_allowed_ips.conf` and reload nginx.**
   ~5 minutes. Closes the largest attack surface immediately.
2. **Decide on a stable IP solution** (business static-IP, Tailscale
   exit node, or VPS jump host). Without this, step 1 will lock you
   out at some point.
3. ~~**Ship step-up on the 3 most irreversible endpoints first**~~ —
   done 2026-06-09. Currently gating GDPR approve-deletion, the
   super-admin role grant, and the backup trigger.
4. **Ship TOTP MFA for super-admin and office.** When that lands, flip
   `STEP_UP_REQUIRES_TOTP=True` so step-up requires a fresh TOTP code,
   not just a password.
5. **Extend the gated endpoint list** — extended 2026-06-09 to cover
   IBAN/SEPA mandate changes (Member + BillingProfile, field-conditional)
   and bulk-email send (invoice reminders + offers). Still outstanding:
   `DELETE /tenants/<id>/` once it's implemented (currently no
   destroy method on `TenantManagementViewSet`). See
   "Extending the gated list" in Part 2 for the recipe.

---

## Related code

**IP allowlist (Part 1):**
- [`nginx/nginx.conf.template:266-`](../../nginx/nginx.conf.template) — super-admin server block
- [`nginx/super_admin_allowed_ips.conf`](../../nginx/super_admin_allowed_ips.conf) — the allowlist file
- [`scripts/verify_super_admin_allowlist.sh`](../../scripts/verify_super_admin_allowlist.sh) — CI guardrail (run by the `gateway` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))
- [`apps/shared/super_admin/permissions.py`](../../jasmin-core/django-core/apps/shared/super_admin/permissions.py) — `IsSuperAdmin`

**Step-up auth (Part 2):**
- [`apps/accounts/permissions.py`](../../jasmin-core/django-core/apps/accounts/permissions.py) — `RequiresStepUp`
- [`apps/accounts/errors.py`](../../jasmin-core/django-core/apps/accounts/errors.py) — `StepUpRequired`
- [`apps/accounts/services/step_up_service.py`](../../jasmin-core/django-core/apps/accounts/services/step_up_service.py) — token-rotation service
- [`apps/accounts/views.py`](../../jasmin-core/django-core/apps/accounts/views.py) — `step_up_view`
- [`apps/shared/super_admin/views/auth.py`](../../jasmin-core/django-core/apps/shared/super_admin/views/auth.py) — `super_admin_step_up_view`
- [`jasmin-core/react-core/src/services/stepUp.ts`](../../jasmin-core/react-core/src/services/stepUp.ts) — frontend bridge
- [`jasmin-core/react-core/src/components/auth/StepUpProvider.tsx`](../../jasmin-core/react-core/src/components/auth/StepUpProvider.tsx) — password modal
- [`apps/accounts/tests/test_step_up.py`](../../jasmin-core/django-core/apps/accounts/tests/test_step_up.py) — permission + endpoint + integration tests

**Other:**
- [`apps/shared/auth_cookies.py`](../../jasmin-core/django-core/apps/shared/auth_cookies.py) — refresh-cookie wiring
- [`apps/accounts/services/friendly_captcha_service.py`](../../jasmin-core/django-core/apps/accounts/services/friendly_captcha_service.py) — Friendly Captcha verification on the 4 anonymous auth endpoints. Shipped dormant; activation steps tracked in [`docs/todos/code.md`](../todos/code.md) → "Bot / form-spam protection".
- [`docs/security/auth-reference.md`](auth-reference.md) — JWT + cookie design
