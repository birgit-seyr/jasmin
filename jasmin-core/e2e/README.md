# Jasmin end-to-end tests

A small Playwright suite that drives the real dev stack in a browser: the
gateway nginx, the Vite frontend, Django, Postgres and Redis. It covers what the
mocked Vitest and pytest suites can't see — subdomain tenant routing, the
refresh cookie and in-memory access token across a reload, step-up, and the
generated client against the live API. It stays a handful of user journeys,
not a second copy of the unit tests: anything Vitest + MSW or pytest can check
belongs there.

Playwright **1.64.0** (pinned in `package.json`), Chromium only (Playwright's
bundled build, chromium-headless-shell 156).

## Running it

The dev stack has to be up (`make dev-up`, gateway on `http://localhost:3000`).
From the repo root:

```bash
make e2e-install                     # once: npm ci + Playwright's Chromium
make e2e                             # seed the E2E tenants, then run the suite
make e2e E2E_ARGS="--repeat-each=3"  # extra Playwright arguments
make e2e-ui                          # the same, in Playwright's UI mode
```

Or from this directory, once seeded: `npx playwright test`, `npm run test:ui`,
`npm run report` (the last HTML report), `npm run type-check`.

## Its own tenants

The suite never touches the `test` tenant. `seed_e2e` (dev only, refuses
`DEBUG=False`) creates or refreshes two tenants of its own:

| Tenant      | Host                  | Used for                                    |
| ----------- | --------------------- | ------------------------------------------- |
| `e2e`       | `e2e.localhost`       | every flow                                  |
| `e2e_other` | `e2e-other.localhost` | proving a session is bound to its tenant    |

Both carry the `seed_test_users` personas (`test-admin@`, `test-office@`,
`test-member@` … `example.com`, password `Test-Test-2026`) without two-factor
devices. `e2e` also gets (`seed_e2e_commissioning`) the share type, delivery
day and station the office flows book into, order-day defaults for every
delivery day, the share article `E2E carrots` the reseller flow orders, and a
confirmed weekly subscription for the member persona, so the member sees their
member page and a payment plan (a new one starts whenever fewer than four weeks
are left). `e2e` sends its mail through the dev stack's MailHog (`mailhog:1025`)
and keeps the `de` CSV format under its English UI.

The platform gets a super-admin `e2e-superadmin@example.com` (same password),
for the flow on `marillen.localhost:3000`.

Rows the tests create pile up between runs. The reseller flow steps through the
unsearchable reseller list from the keyboard, so it slows down slightly with
every run. To start over:

```bash
docker compose -f docker-compose.dev.yml exec backend python manage.py seed_e2e --reset
```

`--reset` drops and recreates only `e2e` and `e2e_other`. `*.localhost`
resolves to loopback in Chromium; Node's resolver (the tests' API requests)
needs `e2e.localhost`, `e2e-other.localhost` and `marillen.localhost` in
`/etc/hosts` where the system doesn't map them.

The member persona's contact details are rewritten by the self-service flow
on every run; nothing else depends on them.

## Logins

The `setup` project logs each persona in through the login form once per run
and saves its `storageState` under `.auth/` (gitignored). The saved state holds
the refresh cookie only: the access token stays in page memory, so every test
page gets its own through the silent refresh on load.

Refresh tokens rotate, and the old one is blacklisted, on every refresh. The
`test` fixture in `support/auth.ts` writes the rotated cookie back after each
test and, when the chain broke (a test logged out, or ended mid-refresh), logs
the persona in again over the API. Pick a persona with
`test.use({ persona: "office" })`; without one a test starts logged out.

Logins count against the `login` throttle (20 a minute per IP and tenant). One
run makes four (three personas and the invited member), so `--repeat-each`
above 5 within a minute runs into it.

`superAdmin: true` (`test.use({ superAdmin: true })`) runs a test as the
platform super-admin instead. Its session works the same way, with the
`sa_refresh_token` cookie (path `/api/super-admin/`, rotated on every refresh)
on `marillen.localhost`. The super-admin login is throttled to **10 an hour per
IP**, so the setup project logs in once per run and every test reuses the
session. Ten runs within an hour use the budget up; reset it locally with

```bash
docker compose -f docker-compose.dev.yml exec redis \
  sh -c "redis-cli --scan --pattern '*throttle_super_admin_login*' | xargs -r redis-cli del"
```

Never `cache.clear()` or `FLUSHDB` for this: the cache shares Redis database 0
with Huey's queue.

`accessTokenFor(persona)` returns an access token of another persona, for API
calls a test makes as someone else (it keeps that persona's saved session
going).

## Mail

`support/mailhog.ts` reads the dev stack's MailHog (`http://localhost:8025`):
`clearMailbox(address)` at the start of a flow, `waitForMail(address)` to poll
for the newest mail, `linksIn(mail)` for its links. Give every flow its own
address (a run id), so the shared MailHog never mixes two runs up.

Step-up asks for the password only (the personas have no TOTP device);
`confirmStepUp(page)` answers the prompt.

## Rules for writing tests

- **Select by role and accessible name** (`getByRole`, `getByLabel`). The
  `jsx-a11y` gate is why these exist. Add a `data-testid` only where no
  accessible name fits.
- **Toasts: assert through the live regions.** AntD's toast has no role, and
  `notify.*` mirrors each message into a screen-reader region at the app root,
  so `getByText` on toast copy matches twice and fails strict mode. Use
  `getByRole("status").filter({ hasText })` for success, info, warning and
  loading, and `getByRole("alert").filter({ hasText })` for errors. A
  validation error's toast is an `alert` itself as well, so that one matches
  twice: take `.first()`.
- **UI language: English, looked up by key.** The E2E tenants and personas are
  seeded in English and the browser runs as `en-US`. Tests read the copy from
  react-core's English locale files with `t("ns.key")` from `support/i18n.ts`,
  never as a literal, so a copy edit doesn't break a test and a missing key
  fails loudly. The only literals are seeded names.
- **No fixed waits.** Never `waitForTimeout`; wait for a visible result or for
  the response (`waitForResponse`).
- **Dates come from the real clock.** The stack can't be given a frozen clock,
  so a flow that books "next week" computes the week at run time
  (`support/dates.ts`). Never hardcode a week or a date.
- **Every test creates the rows it changes**, with unique names (a run id such
  as `Run${Date.now()}`), so a failed run doesn't break the next one. Lists grow
  with every run: find a new row through the table's search.
- **A flaky test is fixed or removed within the week**, not retried into green.
  CI retries once and reports a retry that passed as flaky.
- `workers: 1`: every test shares the `e2e` tenant's schema.

## CI

`.github/workflows/e2e.yml` runs the suite nightly and on `workflow_dispatch`
against a fresh dev stack (gateway, frontend, backend, Postgres, Redis,
MailHog), and uploads the HTML report and traces when it fails. Huey stays
down: no flow waits on it (the invitation mail goes out in the request).

## Flows

| Spec | Flow |
| ---- | ---- |
| `login-reload` | office logs in, survives a hard reload, logs out |
| `tenant-binding` | a session from `e2e` is refused on `e2e_other` |
| `role-gating` | member, office and admin see and reach only their areas |
| `member-subscription` | office books a member a subscription from next week; the share is counted |
| `reseller-documents` | order → delivery note → invoice, finalized, cancelled; no second invoice |
| `phone-drawer` | at 390×844 the drawer lists the field jobs only |
| `member-self-service` | member edits their contact details, sees their payment plan, not another member's data |
| `invitation` | office invites a member; the mailed link sets a password; the member logs in |
| `csv-export` | the member register downloads in the tenant's CSV format |
| `super-admin` | the super-admin's platform session lists the tenants |
