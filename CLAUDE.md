# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

Part 1 is the **rulebook** — standing instructions that always apply. Part 2 is
the **reference** — how the system is built and how to run it. New rules go in
the matching section of Part 1.

## Contents

**Part 1 — Rules**

- [Working agreements](#working-agreements)
- [Universal conventions](#universal-conventions)
- [Backend rules](#backend-rules)
  - [Per-app layout](#per-app-layout)
  - [Errors](#errors)
  - [API design & query params](#api-design--query-params)
  - [ORM & data hygiene](#orm--data-hygiene)
  - [Migrations](#migrations)
  - [Commissioning isolation](#commissioning-isolation)
- [Frontend rules](#frontend-rules)
  - [Reuse the building blocks](#reuse-the-building-blocks)
  - [EditableTable](#editabletable)
  - [Structure & imports](#structure--imports)
  - [Data fetching](#data-fetching)
  - [Styling & accessibility](#styling--accessibility)
  - [i18n](#i18n)
- [Testing rules](#testing-rules)
  - [Backend testing](#backend-testing)
  - [Frontend testing](#frontend-testing)

**Part 2 — Reference**

- [Architecture](#architecture)
- [Commands](#commands)
- [Test fixtures & patterns](#test-fixtures--patterns)
- [Configuration files](#configuration-files)
- [Common workflows](#common-workflows)
- [Debugging & logs](#debugging--logs)

---

# Part 1 — Rules

## Working agreements

- **DO NOT commit.** The user commits manually.
- **Never guess paths.** Always check which ones this repository actually uses —
  no reverse-engineering a plausible path.
- **Production is LIVE — always assume dev AND prod.** Backward compatibility
  matters. Every change ships to a running production with real tenant data,
  in-flight browser clients, cached artifacts, and already-issued tokens/URLs.
  Do NOT make hard cutovers to anything a live client or stored datum depends
  on: on-the-wire formats, signed tokens (e.g. media `?st=` tokens),
  cached/bookmarked URLs, API response shapes, enum values persisted in the DB,
  or stored data. Prefer a backward-compatible path — dual-read/dual-write,
  accept-old-and-new during a transition window, additive migrations (see
  [Migrations](#migrations)) — over a breaking change. When a change could still
  break prod despite care, call it out explicitly and describe the
  migration/rollout path rather than assuming a clean slate.
- **Audits go in a structured `.md` file.** When asked for an audit, write the
  findings to a file rather than only reporting in chat.
- **When fixing something from an audit file, don't reference that audit file in
  code comments.**
- **Never reference `docs/*.md` files in code comments.** Audit / TODO / roadmap
  docs get deleted as work lands, and the references rot. If a comment needs
  context, inline the _fact_ itself — not a pointer. `CLAUDE.md` and `README.md`
  at the repo root are the only durable exceptions and may be referenced.
- **Write skill files whenever useful.**
- **Don't proactively start new feature work in the cultivation / economics /
  staff domains** unless asked. Their frontend pages are, however, **no longer
  excluded** from the type-check / lint / build gates — treat them like any
  other feature and keep type-check + lint + build green when you touch them.

## Universal conventions

- **Use modern, state-of-the-art approaches** — current Django/React best
  practices, no legacy patterns.
- **English only.** No German in code, names, or anywhere else.
- **No hard-to-read abbreviations.** Not `dsd` for DeliveryStationDay, not `oc`
  for OrderContent. Longer but readable wins.
- **`Share` and `CoopShare` are fundamentally different models — never conflate
  them.** Use `share` in function names only where shares are meant, and
  `coop_share` where coop shares are meant. See
  [docs/domain-glossary.md](docs/domain-glossary.md).
- **Model instance IDs are strings, not UUIDs or ints.** See
  [the CharField primary key pitfall](#charfield-primary-key-pitfall).
- **`valid_from` dates are always Mondays.**

## Backend rules

### Per-app layout

The convention the apps converge on — keep new code consistent. Don't reshuffle
existing apps wholesale; apply this when creating or substantially touching a
file.

| Layer | Goes in |
| ----- | ------- |
| DRF `ViewSet`s | `viewsets.py` or a `viewsets/` package |
| `APIView`-style endpoints | `views.py` or a `views/` package |
| Serializers | `serializers` (**plural**) — never singular `serializer/` |
| Services | `services.py` or a `services/` package |
| Errors | `errors.py` (every app carries one) |

Within a `services/` package, modules that expose a `*Service` class take the
`_service.py` suffix (the dominant pattern); function-only helper / operation
modules keep a plain descriptive name **without** the suffix (e.g.
`recompute.py`, `member_cancellation.py`, `trial_conversion.py`,
`trial_policy.py`, `finalize_utils.py`). The suffix signals "there's a Service
class here", so don't add it to function modules.

**DRF `serializers` import aliasing** (by layer):

- **Serializer modules** (anything under a `serializers/` package) import DRF
  plainly — `from rest_framework import serializers` → `serializers.ModelSerializer`.
- **Viewsets / views / services** import DRF's module **aliased** —
  `from rest_framework import serializers as drf_serializers` →
  `drf_serializers.CharField()` (typically inside `inline_serializer(...)`).

There's no real name collision (these modules import serializer _names_ from the
local `serializers` package, not the `serializers` module), so this is a
readability convention — the alias keeps DRF primitives visually distinct from
the app's own serializers. Don't define ad-hoc response serializers in a views
module; put them in the local `serializers` package.

**Tenant API naming** (commissioning / payments / shared.tenants): URL paths,
`@action url_path`, and URL `name=` are all **`snake_case`** — no kebab strays
like `data-import/` or `toggle-optin`. Router `basename=` is `snake_case` too
(it only drives `reverse()`, not the URL path, so it has no client/schema
impact — but keep it readable). Prefer **plural** resource nouns for new
endpoints (`share_deliveries`, not `share_delivery`). Viewset / serializer /
service classes are `PascalCase` and **mirror their model**; don't rename a
viewset/service away from its model name to "fix" casing — fix the model (a
deliberate migration) or leave it. The **gdpr / notifications / accounts /
super-admin** apps are internally kebab-consistent — that's an accepted per-app
dialect, leave it; only hold _new_ tenant-API endpoints to snake.

### Errors

Use the errors in `errors.py` whenever possible, or write new ones there where
necessary. New errors go in the corresponding app's `errors.py` and subclass
`JasminError` (`core/errors.py`), with a stable per-case `code` — never a bare
DRF `ValidationError` or a hand-built `Response`.

Every `JasminError` code needs `de` **and** `en` entries in the locale
`errors.json` files.

### API design & query params

- **For params: use the ones in the catalogue if possible.**
- **ALWAYS use the generated types and API clients** — see
  [Data fetching](#data-fetching) for the frontend half of this rule.

**OpenAPI query params come from the catalogue — never hand-roll
`OpenApiParameter` in `@extend_schema`.** A query parameter is declared ONCE as
a `ParamSpec` (defined in `apps/shared/query_params.py`) inside the app's
catalogue — `PARAM_CATALOGUE` in `apps/commissioning/utils/query_params.py`;
payments keeps its own. That catalogue is what `validate_query_params(...)`
actually enforces at runtime, so the schema must be derived from it rather than
re-typed by hand — otherwise the docs and the validator drift silently. Real
bugs this caught: `undo` documented as `string` but validated as `bool`,
`share_option` missing its 7-value `enum`, `num_weeks`/`years_back` missing
their catalogue defaults.

**How:** prefer an existing `get_*_parameter()` helper in
`apps/commissioning/schemas.py` when one already exists; otherwise derive from
the catalogue via that module's `_catalogue_parameter(name, description=...,
required=...)`. Type / `enum` / `default` are derived — pass only `description`,
`required`, and genuine per-endpoint overrides. **If a param isn't catalogued,
add a `ParamSpec` for it** rather than declaring it inline. The only legitimate
inline `OpenApiParameter` is a non-query one
(`location=OpenApiParameter.PATH`/`HEADER`), which the catalogue doesn't model.

### ORM & data hygiene

- **Avoid Django signals where possible; prefer explicit service calls.**
- **If you write a query, make sure it's not N+1.**

#### CharField primary key pitfall

`TapirModel.id` is a `CharField` (not int/UUID). Django's ORM does NOT
auto-unwrap Model instances when filtering against a `CharField`:

```python
qs.filter(pk=member_instance)    # silently becomes filter(id=str(member))
                                 # -> matches nothing
qs.filter(pk=member_instance.pk) # CORRECT
```

With normal int/UUID PKs, `filter(pk=instance)` works because Django calls
`instance._get_pk_val()`. With `CharField`, `get_prep_value` falls back to
`str(value)` and silently produces a non-matching value.

Always pass `.pk` explicitly when filtering TapirModel rows by a model instance
(e.g. in `apps/authz/scoping.py::scope_by_user_attr`).

#### Money / Decimal hygiene

All money + stock-quantity model fields are `DecimalField`. Keep the arithmetic
in `Decimal` end-to-end — `float()` casts on a money value introduce
binary-floating-point drift that compounds over thousands of invoice lines and
gets persisted as garbage decimals like `Decimal("0.30000000000000004")` when
assigned back to a `DecimalField`.

Three rules:

1. **Never use `Decimal(float_value)` directly.** It captures the float's binary
   representation:

   ```python
   Decimal(1.1)        # Decimal('1.10000000000000008881784...')
   Decimal(str(1.1))   # Decimal('1.1')  ← always do this
   ```

2. **Use the existing helpers** at the line-item layer. Don't reinvent the
   calculator:
   - `apps.commissioning.models.mixin._to_decimal(value)` — safe float-to-Decimal
     coercer (uses the `Decimal(str(value))` pattern).
   - `_calc_line_netto(...)` / `_calc_line_brutto(...)` / `sum_netto(...)` /
     `sum_brutto(...)` / `tax_breakdown(...)` — the canonical money math, all
     using `_PRICE_QUANTIZE = Decimal("0.01")` with `ROUND_HALF_UP`. Every
     `LinePricingMixin` subclass goes through these.

3. **Send money as STRING on the wire, not float.** The frontend gets canonical
   2dp strings (e.g. `str(line.quantize(_CENT))`), not JSON numbers — full
   precision survives the API boundary. Float in JSON responses is OK only for
   non-money values (quantities sent for display, percentages like `rabatt` /
   `tax_rate` that get re-coerced via `_to_decimal()` on any downstream
   arithmetic).

If you genuinely need to round in a NEW location (a new export, a new
calculator), instantiate the same pattern locally rather than importing across
app boundaries:

```python
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")

def _round_money(value) -> Decimal:
    if isinstance(value, float):
        value = str(value)  # avoid binary-fp drift
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)
```

See `docs/code_audit/readme/engineering-audit-playbook.md` (Pass #3) for the
methodology and what "done" looks like for this rule.

### Migrations

**Migrations are forward-only in prod.** Once a migration ships to prod, never
run `migrate <app> <previous>` to reverse it — write a forward fix instead.
Reverse migrations exist for dev / CI sanity (so a local `migrate <app> zero`
works), not as a production rollback strategy.

When writing a new migration that's irreversible (RemoveField after a backfill,
schema-affecting RunSQL, etc.), make the reverse a `noop` rather than
fake-reversibility — a dropped column's data can't be restored, and pretending
otherwise is worse than declaring it gone. See
`apps/commissioning/migrations/0011_backfill_over_default_variation_capacity.py`
for the shape. Confirmed by the 2026-05-24 migration-safety audit
(`docs/code_audit/readme/engineering-audit-playbook.md`, Part 5).

#### FinalizedProtectedMixin: keep Python + Postgres allowlists in sync

`Order`, `DeliveryNoteReseller`, `InvoiceReseller`, and the 6 content models
(`OrderContent`, `DeliveryNoteContent`, `InvoiceResellerContent`, and the three
crate variants) are protected by **two parallel layers** that enforce the same
"which columns may change after `is_finalized=True`" whitelist:

1. **Python** — `FinalizedProtectedMixin.ALLOWED_FINALIZED_UPDATES` on the model
   class. Checked in `save()`.
2. **Postgres** — a `BEFORE UPDATE` / `BEFORE DELETE` trigger function installed
   via RunSQL, with its own column allowlist baked into the function body at
   migration time. The canonical shape is `PROTECTED_TABLES[<table>]["allowed"]`
   inside `apps/commissioning/migrations/0002_finalized_protection_and_reference_data.py`
   (the post-squash installer; the earlier 0007/0019/0020/0032 chain was folded
   into it and no longer exists).

The two allowlists MUST stay in sync. Drift between them means either:

- the trigger accepts a write that Python rejects (silent bypass via
  `.objects.update()`, raw SQL, etc.), or
- the trigger rejects a write that Python allows (`IntegrityError` bubbling up
  from a `model.save(update_fields=[...])` that should have worked).

The second case is the one that bites: makemigrations doesn't know about
RunSQL-installed triggers, so adding/removing/renaming a column in
`ALLOWED_FINALIZED_UPDATES` updates Python only. The trigger keeps its stale
allowlist until a follow-up migration explicitly rewrites the function body.

**Rule:** any change to `ALLOWED_FINALIZED_UPDATES` on a
`FinalizedProtectedMixin` model — adding a field, renaming it, dropping it —
needs a follow-up migration that rebuilds the trigger function with the matching
`PROTECTED_TABLES[<table>]["allowed"]` list. Mirror the `_build_function_sql` /
`_build_forward_sql` helpers from migration
`0002_finalized_protection_and_reference_data` (self-contained, reverse=noop).
Same column names on both sides.

Symptoms to grep for if you suspect drift:

- `IntegrityError: Cannot update column "X" on commissioning_Y: row has been
  finalized` for a column that's listed in `ALLOWED_FINALIZED_UPDATES`.
- A test that mutates a column on a finalized row, asserts the flag flipped, and
  the assertion fails because `refresh_from_db()` reloads the unchanged value
  (the service's broad-but-bounded except swallowed the IntegrityError
  silently).

### Commissioning isolation

The `commissioning` app should — in the future — be isolated and moved to
another project, so avoid interweaving it too much with the others, or at least
keep the option to cut it off.

**The isolation is one-way.** Other apps importing FROM `apps/commissioning/` is
fine (e.g. `apps/gdpr/models.py` reuses
`apps.commissioning.models.mixin.AdminConfirmableMixin`). What's NOT fine is the
reverse — `apps/commissioning/` importing FROM apps outside it, other than the
always-shared `apps/accounts/`, `apps/authz/`, `apps/shared/*` — because those
imports would have to be unwound at extraction. Keep that direction in mind when
making cross-app solutions.

**Status of the cross-app edges:**

- `payments` — inverted via the `apps/shared/subscription_hooks.py` seam
  (commissioning calls `notify_subscription_changed`; payments registers the
  handler in its `AppConfig.ready()`).
- `gdpr` — gone (`PIIReadLoggingMixin` now lives in `apps/shared/pii_logging.py`).

**Remaining known extraction blockers** (all deferred/runtime imports, to unwind
at extraction):

- The background-job infra `apps.notifications.jobs` (`enqueue_job` + progress
  helpers) and `apps.notifications.models.BackgroundJob`, used by
  `reseller_views`/`tasks` for bulk-send jobs. The clean fix is relocating that
  infra (incl. the `BackgroundJob` model, a migration) into `apps/shared/`.
- A read-only `apps.notifications.models.EmailLog` query in `members_viewsets`
  (the "Sent emails" modal), which needs a shared read interface.

The frontend mirrors this rule — see [Structure & imports](#structure--imports).

## Frontend rules

### Reuse the building blocks

**REUSE existing components/hooks/utils — always prefer them over
hand-rolling.** Before building a page/table/selector/download/formatter, look
for an existing one and use it. Hand-rolling a plain AntD `Table`, an inline
date range, a bespoke CSV writer, or a `dayjs().format(...)` string when a shared
equivalent exists is a defect, not a shortcut.

| Need | Use |
| ---- | --- |
| Table | `EditableTable` (`READ_ONLY_PERMISSION` for read-only reports) |
| Column defs | the `use*Column(s)` hooks — `useTimeBoundColumns`, `useActiveStatusColumn`, `useSellerColumn`, `useShareArticleColumn`, `useNoteColumn`, … |
| Date-range picker | AntD `RangePicker` + `useDateRangePresets` |
| Date display/format | `useDateFormat` — `dateFormat` (picker), `formatDate` (cells), `formatDateForAPI` (`YYYY-MM-DD` payloads). Never hardcode a date format. |
| CSV | `buildCsvString` + `downloadCsvBlob`, or `ExportCsvDateRangeModal` for a date-range export honoring the tenant `csv_format` |
| Money / currency | `useCurrency` |
| Selectors | `src/shared/selectors/*` — Year/Week/Month/Day/Member/Reseller/ShareType |
| Data | the `use*List` TanStack hooks + the `use<Entity>` wrappers (`useDeliveryStations`, `useShareTypeVariations`, `useSellers`, …) |

For most columns there are hooks — reuse them. If a needed component doesn't
exist, build it in `src/shared/` so the next page reuses it.

### EditableTable

If there needs to be an editable table, use the `EditableTable` component.

**Data ownership — never both.** A page either lets the table own its data (pass
`apiFunctions.list` + `showSearchBar`, leave `initialData` empty) OR owns it
itself (a TanStack `use*List` query → `initialData={data}`, and DON'T pass `list`
in `apiFunctions`). Passing a page query's `initialData` AND a network
`apiFunctions.list` + `showSearchBar` makes the table auto-fetch the same
endpoint a second time — a double fetch with two racing `setData` paths. When the
page owns the data, search still works (client-side over the loaded rows) and
post-mutation refresh comes from `onSaveSuccess`/`onDeleteSuccess` → query
invalidation.

**Loading state — one prop, deliberate flag.** Drive the grid spinner via the
single declared `loading` prop (it's OR-ed with the table's own save/delete
loading; do NOT rely on prop-spread). Pick the source flag by page type:

- `isFetching` for filter-driven tables (year/week/member selectors) — with the
  global `staleTime: 0`, a revisited cached key has `isLoading === false` and
  would show no refresh spinner.
- `isLoading` for plain lists (spinner only on the genuine first load).
- `isPending` for mutations (TanStack Query v5 renamed mutation `isLoading` →
  `isPending`).

### Structure & imports

**Domain-first.** There is no single global modals folder. A modal that is
generic or used by several unrelated apps lives in `src/shared/modals/`; a modal
that belongs to exactly one app lives in `src/features/<app>/modals/`. The same
rule applies to components and hooks (generic → `src/shared/{ui,hooks}/`;
app-specific → `src/features/<app>/{components,hooks}/`). Page-level
cards/sections are co-located in `src/features/<app>/components/`. See
[Frontend structure](#frontend-structure) for the full layout.

- **Path aliases** — keep all FOUR config files in sync: `vite.config.js`,
  **`vite.config.production.js`** (the prod build — `npm run build` uses this
  one, easy to miss), `vitest.config.ts`, `tsconfig.json`. Live aliases: `@`
  (src root), `@app`, `@shared`, `@features`, `@hooks` (→ `shared/hooks`),
  `@routing` (→ `app/routing`). The old `@components`/`@pages`/`@services`
  aliases are **removed**.
- **Cross-boundary → alias; intra-module near-siblings → relative.** Importing
  the shared layer or another feature uses `@shared/…` / `@features/<app>/…`; a
  file importing the card beside it uses `./Card`.
- **One-way layering (ESLint-enforced):** `src/shared/**` must NOT import
  `@features/*` or `@app/*`. Features import `shared/` freely.
  (`eslint.config.js` has the `no-restricted-imports` rule.)
- **Commissioning isolation (one-way, mirrors the backend rule):**
  `commissioning`, `members`, `abos`, `customer`, `warehouse` form the
  commissioning bounded context — they may import each other + `shared/`, but
  must NOT import non-context features (`configuration`, `auth`, `platform`, …).
  Other features may import FROM the context. A module shared _across_ contexts
  (or domain-free) stays in `shared/`.
- **Verify a structural move with all four:** `npm run type-check`,
  `npm run lint`, `npm run build`, `npm run test:run`. type-check skips `.jsx`
  files + `vi.mock()` strings, so **the build is the real oracle** for `.jsx`;
  tests catch stale `vi.mock` paths and the `no-raw-axios` allowlist.

### Data fetching

- **ALWAYS use TanStack Query whenever possible** (except for multipart).
- **Use the generated interfaces wherever possible.** Almost never use a raw URL
  — always the generated types and API clients. The exceptions are upload and
  multipart.

### Styling & accessibility

- **Don't use inline styles** unless really necessary — use the CSS files.
- **Add `aria-label`s where advisable** when making a frontend component, and
  generally think about the a11y implications.
- **Don't use `<Empty/>`** — use a subtle grey "no data" message instead.

### i18n

**No inline fallbacks.** Use bare `t("ns.key")` — never `t(key, "Fallback")`.

The German locale files under `src/shared/i18n/locales/de/**` are the source of
truth and must stay complete. `de` is the `fallbackLng`, so a key missing from
`en`/`fr`/`it` degrades to German (acceptable for now), but a key missing from
`de` renders the raw key string to the user. Whenever you add a `t()` call, add
the `de` key in the same change.

Keys use `.` as the separator, so a key like `commissioning.x_template.csv` must
be **nested** (`{"x_template": {"csv": "…"}}`), not a flat dotted JSON key — a
flat `"x_template.csv"` is unreachable and renders the key.

**`fr` and `it` can be ignored for now** — don't add or maintain their keys;
their incompleteness is a deliberate, deferred gap (they degrade to `de` via
`fallbackLng`). Keep `de` complete (mandatory) and add `en` alongside it; only
`de` must never miss a key.

## Testing rules

### Backend testing

**Test both the present AND absent case of an optional/nullable FK** (or any
presence-guarded branch). A guard like `x.seller.name if x.seller else ""`
short-circuits: a fixture that leaves the FK NULL takes the `else` branch and
NEVER evaluates the related-object access, so the test goes green while the real
failure hides in the present-branch. Build fixtures from realistic data (a
documentation `Purchase` almost always HAS a seller), not the minimal happy
path — the "rare" branch is often the common one in prod.

> The concrete miss this rule was written for: the purchase CSV export crashed
> on `seller.name` (Reseller has no `name` — it's `seller.contact.name`) for
> every real row, but the export test passed because its purchase had
> `seller=None`, so `.name` was never touched.

**No time-bomb tests — freeze the clock, never hardcode a bare future
date/week.** A test that hardcodes a future date or week (`FUTURE_WEEK = 30`,
`VALID_FROM = date(2026, 9, 7)`, `year=2026`) AND exercises now-relative code
(past/current-week guards like `PastWeekError`, subscription lead-time /
`SubscriptionStartTooSoon`, `is_past`/`is_future`, `current_year_week`, relative
`_monday_n_weeks_ahead(...)` math) will pass today and silently rot — it
detonates the moment the wall clock crosses that date/week.

**Rule:** any test whose outcome depends on "now" must pin the clock with
`time_machine.travel(datetime(YYYY, M, D, 12, 0), tick=False)` — an autouse
fixture, since a class decorator only works on `unittest.TestCase`, not plain
pytest classes — so its hardcoded future value stays future forever.

- Scope the freeze to the smallest safe unit (module or class, not blindly the
  whole file) — sibling classes that rely on distinct `auto_now` timestamps break
  under `tick=False`, e.g. a "sort newest first" test where a frozen instant ties
  every timestamp.
- Freeze the **whole flow**, not just data creation — the past/future *query*
  must run under the same frozen clock as the setup, or the guard still flips.
- Pick a freeze instant on the Monday of a week comfortably before your hardcoded
  future value and away from any year boundary (relative-date math that crosses
  Dec→Jan is its own bomb, invisible to any literal scanner).
- The CI guard `apps/shared/tests/test_no_unfrozen_future_dates.py` catches
  unfrozen **date literals** but NOT week-number constants or year-boundary
  relative math — don't rely on it to catch this.

### Frontend testing

**ANY frontend test that mocks `react-i18next` MUST export the full surface** —
`useTranslation`, `Trans`, AND `initReactI18next`. Almost everything in `src/`
(any `hooks/`, `pages/`, `services/`, `utils/apiError`, plus any component that
imports those) transitively pulls in `src/shared/i18n/index.ts`, which calls
`.use(initReactI18next)` at module load. A partial mock fails the whole test file
with `No "initReactI18next" export is defined on the "react-i18next" mock`
before any test runs.

Canonical shape — do NOT shorten; `Trans` and `initReactI18next` are
load-bearing even when the component doesn't reference them:

```tsx
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));
```

#### Frontend test conventions — `jasmin-core/react-core`

**Setup**

| | |
| --- | --- |
| Runner | Vitest 3 + jsdom + @testing-library/react |
| Configs | `vitest.config.ts` (jsdom default); per-file `// @vitest-environment node` pragma for Node-only suites (PDF generation, file I/O) |
| Setup | `src/test/setup.ts` — jest-dom matchers, RTL cleanup, matchMedia/window polyfills (env-guarded so node-env files don't crash) |
| MSW | `src/test/msw/server.ts` — `setupServer` with default 401 on `/auth/refresh/` so pages start logged-out. `setup.ts` wires `listen({onUnhandledRequest:'error'})` / `resetHandlers` / `close`. |
| Run | `npm test` (watch), `npm run test:run` (CI-style single run), `npm run test:ui` (browser UI) |

**Conventions**

- **Mock the boundary, not the world.** Prefer `vi.mock` of the API/axios layer
  over MSW unless real network behaviour is needed (Tier 4 pages).
- **Keep the in-memory tokenStore REAL.** AuthContext's subscribe/notify wiring
  depends on it.
- Use a small `<Probe/>` component + module-scoped `let probedAuth` pattern to
  assert on hook return values from the outside.
- `userEvent` for keyboard/mouse; `fireEvent` only for low-level cases.
- Canonical jasmin error body in MSW handlers: `{ code, message, field?, details? }`.
- Prefer 400 over 401 for credential/validation failures unless intentionally
  testing the silent-refresh chain — 401 has special-cased behaviour in
  `src/shared/services/api.ts`.
- Per-file `// @vitest-environment node` pragma for PDF tests (jsdom `Blob` lacks
  `arrayBuffer()`).
- **react-i18next mock:** minimal stub returning the fallback when given (or the
  key otherwise). Do NOT spread `vi.importActual('react-i18next')` — the real
  i18n isn't initialised inside vitest. Same when unit-testing a hook that calls
  `useTranslation()`: mock at module level, or it logs `NO_I18NEXT_INSTANCE`
  warnings.
- **AntD `Form.Item` with no `name`** does NOT wire the input to its label, so
  `getByLabelText` fails. Use `getByDisplayValue` or scope with
  `within(formItemEl)`.
- **AntD `Switch.onChange` is `(checked, event)`.** Use
  `expect(spy.mock.calls[0][0]).toBe(true)`, not `toHaveBeenCalledWith(true)`.
- **AntD `Form.useForm()` outside a rendered `<Form/>`** works for
  `setFieldsValue`, but `getFieldsValue()` returns `{}` (no fields registered).
  Pass `true` to read every entry in the internal store:
  `form.getFieldsValue(true)`.
- **Heavy pages** (lots of subcomponents): mock every child component with a
  `data-testid` stub + mock the modals to expose their `onSubmit` via the shim.
  Wrap renders in `QueryClientProvider` with `retry:false` + `gcTime:0`.
  Reference: `src/features/members/pages/__tests__/MemberDetail.test.tsx`.
- **`TableRecord` literals require a `key` field** — keep test fixtures honest
  with `{ key, id, ... }` so TS stays green.
- **`vi.mock()` factories are hoisted above imports.** A closed-over variable
  used as a DIRECT PROPERTY VALUE of the factory's returned object (e.g.
  `notify: notifyMock`, or shorthand `{ notify }`) MUST be declared via
  `vi.hoisted(() => ({...}))`, or the test fails with "Cannot access X before
  initialization" (the factory reads it before the module-scope `const`
  initialises). A variable dereferenced LAZILY — behind a `() => ...mock(...)`
  arrow, read only at call/render time — is safe as a plain module-scope `const`.
  Reference: `src/shared/ui/__tests__/BulkActionButton.test.tsx`.
- **`getErrorMessage` only inspects errors that look like axios errors** — mocks
  must include `isAxiosError: true` alongside `response.data`.
- **Render-loop smoke test pattern:** wrap the page in React's `<Profiler>` and
  assert a LOOSE upper bound on `onRender` call count. Healthy baselines so far:
  LoginPage ~6, MemberDetail ~5 commits on initial mount; bounds set to 50 / 80
  (10× headroom). A real setState-in-render loop produces thousands of commits,
  so loose bounds catch the bug while tolerating legitimate dep changes.
  References: `src/features/auth/pages/__tests__/LoginPage.test.tsx`,
  `src/features/members/pages/__tests__/MemberDetail.test.tsx`. Add this test to
  any new heavy page.

---

# Part 2 — Reference

## Architecture

jasmin Platform is a multi-tenant CSA (Community Supported Agriculture)
management system built with Django (backend) and React (frontend), deployed
with Docker and Nginx. The platform supports multiple independent tenant
organizations accessing the same codebase through multi-schema PostgreSQL
isolation (via django-tenants).

**Core stack:**

- Backend: Django 5.2, Django REST Framework, PostgreSQL (multi-tenant via
  django-tenants), Redis (cache/Huey broker)
- Frontend: React 18, Vite, TanStack Query, React Router, Material-UI / Ant Design
- Task queue: Huey (with Redis broker)
- Authentication: JWT (djangorestframework-simplejwt) with tenant-bound tokens
- Build/deploy: Docker Compose, Gunicorn, Nginx, Poetry (Python), npm (Node)

### Multi-tenant design

The platform uses django-tenants to isolate tenant data at the PostgreSQL schema
level:

- **Public schema** — shared data (Tenant definitions, Domains, super-admin users)
- **Tenant schemas** — each tenant (e.g. `test_tenant`) gets its own isolated
  schema containing all business data (users, members, payments, etc.)

**URL routing:**

- Super-admin platform: `marillen.localhost` (or `PLATFORM_SUBDOMAIN` in prod) →
  serves SuperAdminApp (tenant management, dashboards)
- Tenant subdomains: `tenant-name.localhost` → serves TapirApp with that tenant's
  data
- Backend detects the tenant via subdomain using `TenantMainMiddleware`

**django-tenants behaviour worth remembering:**

- Queries are automatically scoped to the active schema.
- `TenantMainMiddleware` resolves the tenant from the request (subdomain →
  `Tenant.domain_url` → `schema_name`).
- `SHARED_APPS` models live in the public schema; `TENANT_APPS` models live in
  tenant schemas.
- Migrations must run both `migrate_schemas --shared` (once) and
  `migrate_schemas --tenant` (for each tenant).
- Platform endpoints (tenant management) live on the public schema; super-admin
  users are stored there and don't have tenant-specific roles.

### Backend apps

Located in `jasmin-core/django-core/apps/`:

| App | Purpose |
| --- | ------- |
| `accounts` | User authentication, profiles, roles (member, staff, admin) |
| `authz` | Authorization, role-based permissions, tenant-bound JWT authentication |
| `commissioning` | Members, subscriptions, shares and weekly deliveries, stations and tours, resellers and orders, warehouse/stock |
| `cultivation` | Growing/planting data, sowing and planting lists, CP-SAT bed planner |
| `economics` | Financial reports, pricing, invoicing |
| `gdpr` | Data export/deletion for GDPR compliance |
| `notifications` | Email/SMS templates, notification dispatch (via Huey + Anymail) |
| `payments` | SEPA Direct Debit, billing runs, charge schedules, subscriptions |
| `staff` | Staff scheduling, permissions, admin dashboards |
| `shared.tenants` | Tenant and domain models, multi-tenancy bootstrap |
| `shared.super_admin` | Platform-wide admin endpoints (tenant CRUD, etc.) |

`apps/shared/` also holds standalone always-shared utility modules (importable
from `commissioning`): `auth_cookies.py`, `csp_report.py`, `csv_safety.py`,
`deferred_email.py`, `iban_validator.py`, `invitations.py`, `languages.py`,
`money.py`, `pii_logging.py`, `pii_masking.py`, `query_params.py`,
`request_utils.py`, `sepa_mandate_hooks.py`, `smtp_host_validator.py`,
`subscription_hooks.py`.

**Key Django patterns:**

- Multi-tenant migrations: `makemigrations` creates shared + tenant migrations;
  `migrate_schemas --shared` and `migrate_schemas --tenant` apply them separately
- Tests use pytest fixtures with session-scoped tenant setup (see
  `apps/commissioning/tests/conftest.py`)
- Settings split: `SHARED_APPS` (cross-tenant) and `TENANT_APPS` (per-tenant)
- Email via Anymail with a provider-agnostic interface (SendGrid/SMTP)
- Security: django-axes for account lockout, django-auditlog for audit trail,
  encrypted fields for PII

### Frontend structure

Located in `jasmin-core/react-core/src/`. **Domain-first ("feature-sliced")**:
everything lives under `app/`, `features/<app>/`, or `shared/` — there are NO
top-level `components/`, `hooks/`, `pages/`, `services/`, `contexts/` folders
anymore.

```
src/
  ├── app/                # bootstrap & shell: App, main, TapirApp, SuperAdminApp,
  │                       #   UnauthorizedPage, routing/ (AppRouter, ProtectedRoute, routes/)
  ├── shared/             # the COMMON layer — importable by any feature
  │   ├── ui/             # design-system primitives  ├── tables/  EditableTable & friends
  │   ├── selectors/      # generic Year/Week pickers ├── layout/  app shell (Sidebar, UserMenu…)
  │   ├── modals/         # generic + cross-feature modals
  │   ├── pdfs/           # PDF infra (shrinks as commissioning-specific docs move into the feature)
  │   ├── hooks/          # cross-cutting hooks + the `index.ts` barrel
  │   ├── contexts/       # Auth, Tenant, Locale, Menu …
  │   ├── services/       # the wire: api.ts, tokenStore, authEndpoints, stepUp
  │   └── utils/  styles/  i18n/  api/ (Orval client)  auth/ (role helpers)
  ├── features/           # ONE folder per app
  │   ├── commissioning/  members/  abos/  customer/  warehouse/   # commissioning bounded context
  │   ├── configuration/  cultivation/  economics/  staff/  auth/  public/  platform/
  │   │     └─ each: pages/  components/ (cards/sections)  modals/  hooks/  pdfs/  services/
  └── test/               # vitest setup, MSW, profileRenders helper
```

Import and boundary rules are in [Structure & imports](#structure--imports).

**Frontend architecture notes:**

- Single codebase with runtime tenant detection (`TenantContext.isPlatformDomain()`)
- `src/app/App.tsx` / `src/app/routing/AppRouter.tsx` dispatch to `SuperAdminApp`
  (platform) or `TapirApp` (tenant) via `isPlatformDomain()`
- Tenant resolution is subdomain-only (backend `TenantMainMiddleware`); the
  frontend sends no tenant header
- React Query is configured (in `src/app/App.tsx`) with `staleTime=0` and
  `refetchOnWindowFocus=true` to avoid stale data across tenant switches
  (`staleTime=0` means data is always stale, so it refetches on mount)

**Key frontend patterns:**

- Routing: React Router with lazy-loaded route components
- Data fetching: TanStack Query with the OpenAPI-generated client (Orval)
- State: React Context for auth/tenant/locale (no separate global state lib;
  Zustand was evaluated and not adopted)
- Forms: Ant Design Form (React Hook Form was evaluated and not adopted)
- PDF generation: @react-pdf/renderer (jsPDF was evaluated and not adopted)
- Auth: JWT tokens stored in httpOnly cookies (refresh tokens), localStorage for
  access tokens
- Locale: i18next with language detection and backend translation loader

### API generation

- Backend exposes the OpenAPI schema at `/api/schema/` (via drf-spectacular)
- Frontend runs `npm run generate-api` (orval) to generate the typed API client
- Regenerate after backend API changes: `make generate-api`

### Key dependencies & integrations

- **Payments**: SEPA Direct Debit via custom billing logic (no third-party
  processor in base)
- **Email**: Anymail (provider-agnostic) + SendGrid (production typical)
- **PDF generation**: WeasyPrint (backend) and @react-pdf/renderer (frontend)
- **Internationalization**: i18next (frontend), Django i18n (backend), supports
  de/en/fr/it (de is the primary locale and `fallbackLng`)
- **Security**: django-axes (brute force protection), auditlog (action audit
  trail), encrypted model fields (PII)
- **Task queue**: Huey + Redis (async email, notifications, reports)

## Commands

### Docker development

Uses `docker-compose.dev.yml` for a development environment with auto-reload and
bind-mounted source:

```bash
make dev-up                      # Start dev stack (postgres, redis, backend, frontend, nginx)
make dev-down                    # Stop dev stack
make dev-logs                    # Tail logs
make dev-rebuild                 # Rebuild images without cache
make dev-reset                   # Full reset (down -v, then up -d --build)
make dev-seed                    # Re-seed the test tenant
make dev-bash                    # Shell into backend container
make dev-shell                   # Django shell in backend container
make dev-migrate                 # Run shared + tenant migrations
make dev-makemigrations          # Create new migrations
```

**Access points:**

- Frontend: http://localhost:3000 (gateway nginx proxying frontend dev server + backend)
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/api/docs (Swagger) or http://localhost:8000/api/redoc (ReDoc)
- MailHog: http://localhost:8025 (email inbox)
- Postgres: localhost:5433 (host port, password in `.env.dev` — created via `cp .env.dev.example .env.dev`)

### Local development (no Docker)

**Backend:**

```bash
cd jasmin-core/django-core
poetry install                                        # Install dependencies
poetry run python manage.py migrate_schemas --shared  # Shared schema migration
poetry run python manage.py migrate_schemas --tenant  # Tenant schemas
poetry run python manage.py runserver 0.0.0.0:8000    # Dev server (port 8000)
poetry run python manage.py shell                     # Interactive shell
```

**Frontend:**

```bash
cd jasmin-core/react-core
npm install                      # Install dependencies
npm run dev -- --port 3000       # Dev server with HMR (port 3000)
npm run build                    # Production build
```

### API generation (after backend API changes)

```bash
make generate-schema             # Generate OpenAPI schema from Django
make generate-frontend-api       # Run orval to update React client
make generate-api                # Both steps combined
```

### Testing

**Backend (pytest):**

```bash
cd jasmin-core/django-core
poetry run pytest                           # Run all tests
poetry run pytest -k test_name              # Run single test by name
poetry run pytest apps/payments/tests/      # Run tests for a specific app
poetry run pytest apps/payments/tests/test_models.py::TestBillingProfile        # Test class
poetry run pytest apps/payments/tests/test_models.py::TestBillingProfile::test_foo  # Single test
poetry run pytest --maxfail=1 -q            # Stop after first failure, quiet mode
poetry run pytest --cov=apps --cov-report=html  # Coverage report
```

Pytest configuration lives in `pyproject.toml`:

- `DJANGO_SETTINGS_MODULE = "config.settings"`
- `testpaths = ["apps"]` — only discovers tests in `apps/`
- `python_files = ["test_*.py"]`, `python_classes = ["Test*"]`,
  `python_functions = ["test_*"]`
- Fixtures: session-scoped tenant setup in `apps/commissioning/tests/conftest.py`
  (re-exported by other apps)

**Frontend (Vitest):**

```bash
cd jasmin-core/react-core
npm run test:run                 # Run tests
npm run test:ui                  # Open test UI
npm run type-check               # TypeScript check (no emit)
```

### Linting & code quality

**Backend:**

```bash
poetry run black --check apps config          # Check formatting (CI)
poetry run black apps config                  # Auto-format
poetry run ruff check apps config             # Lint
poetry run ruff check apps config --fix       # Auto-fix what's fixable
poetry run pip-audit                          # Security audit (dependencies)
```

Ruff config lives in `pyproject.toml` (`[tool.ruff]` and `[tool.ruff.lint]`). The
selected rule set is `E,F,B,BLE,UP,I` with `__init__.py` re-exports, conftest
fixtures, Django settings star-imports, generated migrations, and the
`apps/cultivation/solver/**` research code allow-listed.

**Frontend:**

```bash
npm run lint                     # ESLint check
npm run lint:fix                 # Auto-fix issues
```

**CI/CD** — configured in `.github/workflows/ci.yml`:

- Runs on all pushes to main and all PRs
- Frontend job: type-check, lint, vitest, production build
- Backend job: black --check, ruff check, pytest (with a Postgres service for
  django-tenants tests)
- Concurrency-cancels in-flight runs when a new commit lands on the same branch/PR

### Production deployment

**Build & deploy:** there are **no `make prod-*` targets** — the Makefile only
defines `dev-*` plus generate/migrate helpers. Production is driven via
`docker-compose.yml` directly (build + `docker compose up -d`, then run
migrations through the backend container). Match your host's actual deploy flow.

**Database backups:** `pg_dump` against the `postgres` service (e.g.
`docker compose exec postgres pg_dump ...`) — there is no `make prod-backup`.

**Stack components** (`docker-compose.yml`):

- `postgres`: PostgreSQL 15, persistent volume
- `redis`: Redis 7 for cache and Huey broker
- `backend`: Django + Gunicorn
- `huey`: Background task worker (async jobs, notifications)
- `frontend`: React + Nginx (built SPA)
- `gateway`: Public Nginx with TLS, routes to backend/frontend
- `certbot`: Let's Encrypt renewal (wildcard certs via Linode DNS plugin)

## Test fixtures & patterns

Tests in `apps/*/tests/` use pytest with session-scoped database setup.

**Shared fixtures** (from `apps/commissioning/tests/conftest.py`):

| Fixture | What it gives you |
| ------- | ----------------- |
| `_tenant_schema` | Creates the `test_pytest` schema (session-scoped, shared across apps via get-or-create) |
| `tenant` | Switches the DB connection to the `test_pytest` schema |
| `user` | Authenticated TapirUser with `office` role |
| `member_user` | Authenticated TapirUser with `member` role only |
| `api_client` | DRF APIClient authenticated as `user` |
| `anon_client` | Unauthenticated APIClient |
| `api_request_factory` | DRF APIRequestFactory for unit-testing views without routing |

**App-specific fixtures** (e.g. `apps/payments/tests/conftest.py`) re-export the
shared fixtures and add domain-specific ones (`billing_profile`, `subscription`).

**Factories** — factory-boy for test data creation (see imports in conftest.py),
e.g. `MemberFactory(user=user)` creates a Member with a linked TapirUser.

**Key patterns:**

- Tests are isolated per app schema → safe to run in parallel
- Use `@pytest.mark.django_db` if needed (usually implicit with fixtures)
- Parametrize with `@pytest.mark.parametrize` for data-driven tests
- Time travel: the `time-machine` library for date/time testing (see
  [Backend testing](#backend-testing) for the mandatory freeze rule)
- Mock external calls (email, Huey, payments) with `unittest.mock`
- Several `commissioning/tests/` subdirectories contain an `OVERVIEW.txt` mapping
  test classes and methods (not all do — e.g. `tests_services` currently lacks
  one) — consult it when present before adding tests in that dir
- `apps/commissioning/services/recompute.py` provides `recompute_shares()` and
  `recompute_order_contents()` — call these at the end of any service operation
  that mutates `ShareContent`, `ShareDelivery`, or `Forecast`

## Configuration files

**Backend settings** — `jasmin-core/django-core/config/settings.py`

- Multi-tenant setup: `SHARED_APPS`, `TENANT_APPS`, `PUBLIC_SCHEMA_NAME`, `ROOT_URLCONF`
- Security: CSRF, CORS, rate limiting (django-axes)
- Email: Anymail provider config
- JWT: token lifetime (access 15m, refresh 7d), rotation enabled
- Logging: separate logs for security, auth, app, tenants

**Frontend config** — `jasmin-core/react-core/vite.config.js` (dev server) **and
`vite.config.production.js`** (the production build — `npm run build` uses this
one, easy to miss); `vitest.config.ts` for tests. ⚠️ `vite.config.ts` is an empty
**directory**, not a config. Aliases must stay in sync across all three +
`tsconfig.json`.

- Path aliases: `@`, `@app`, `@shared`, `@features`, `@hooks`, `@routing`
- API proxy: proxies `/api`, `/media`, `/static` to backend (tenant-aware)
- Build: code splitting by vendor, router, api, forms, pdf

**Docker Compose** — multi-stage builds, dev vs. runtime targets, health checks

- Frontend builds during image creation (production) or mounts source (dev)
- Backend entrypoint: `docker_entrypoint.sh` handles migrations, collectstatic,
  gunicorn/runserver selection

**Environment** — `.env.dev.example` (dev template — `cp .env.dev.example
.env.dev`), `.env.example` (prod template), `.env.local`

- Required in prod: `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `POSTGRES_*`,
  `FRONTEND_DOMAIN`
- Development defaults use insecure values (for convenience)

## Common workflows

**Add a new tenant-scoped feature:**

1. Create a new Django app in `apps/` with models
2. Add migrations (stored in `apps/myapp/migrations/`)
3. Run `make dev-migrate` to apply to shared + tenant schemas
4. Add DRF viewsets/views in the app's `viewsets.py`/`views.py` and wire routes in
   `apps/<app>/urls.py`; ensure the app is `include()`d in `config/tenant_urls.py`
5. Generate schema: `make generate-schema`
6. Generate React client: `make generate-frontend-api`
7. Build React pages under `src/features/<app>/pages/` (with co-located
   `components/`, and `modals/`/`hooks/` for app-specific ones; generic ones go
   in `src/shared/`)

**Update an existing API:**

1. Modify the Django viewset/serializer
2. Generate the new schema: `make generate-schema`
3. Regenerate the React client: `make generate-frontend-api`
4. Update the React components using the new API

**Add a migration after model changes:**

```bash
cd jasmin-core/django-core
poetry run python manage.py makemigrations
# Creates both shared and tenant migrations
poetry run python manage.py migrate_schemas --shared
poetry run python manage.py migrate_schemas --tenant
```

**Debug tenant issues:**

```bash
make dev-bash                                          # Enter backend container
python manage.py shell --schema=test_tenant            # Tenant-specific shell
python manage.py tenant_command showmigrations --schema=test_tenant
```

**Monitor background tasks:**

- Huey logs appear in `make dev-logs` output
- In dev docker-compose, check redis at `localhost:6379`
- Production: Huey is a separate service consuming the Redis queue

## Debugging & logs

- **Backend**: logs in `jasmin-core/django-core/logs/` (app.log, auth.log, security.log)
- **Frontend**: browser console + Vite HMR logs
- **Docker Compose**: `make dev-logs` tails all services
- **Database**: `docker exec -it jasmin-postgres psql -U jasmin -d jasmin`
- **API docs**: `/api/docs/` (Swagger) and `/api/redoc/` (ReDoc) during development
