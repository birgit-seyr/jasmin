# Hand-written migrations — catalog (for a wipe / squash / rename)

`makemigrations` reproduces ordinary schema ops (AddField, AlterField, model
Meta constraints…) but it does **NOT** reproduce hand-written `RunSQL` /
`RunPython`. If you wipe the dev DB and squash to a fresh initial migration,
these are the ONLY things that need conscious handling — everything else
regenerates automatically.

Six migrations carry hand-written ops. They split into two groups.

> **Ready-made:** a consolidated, drop-in commissioning `0002` that already
> merges Group-A items **1, 2, and 4** (triggers + `season_one_open` index +
> the PaymentCycle/Storage/default-OfferGroup seed) is staged at
> `docs/staged-migrations/commissioning/0002_finalized_protection_and_reference_data.py`.
> After the wipe regenerates `0001_initial`, drop it in. The only Group-A op it
> can't carry is **item 3** (super_admin checklist) — different app / public
> schema.

## A. MUST re-port (a fresh DB needs them; makemigrations can't recreate them)

### 1. `commissioning/0002_finalized_protection_and_reference_data.py` — **CRITICAL**
Two ops:
- **`RunSQL(_build_forward_sql(), _build_reverse_sql())`** — installs the
  `FinalizedProtectedMixin` **Postgres BEFORE UPDATE / BEFORE DELETE triggers**.
  The `PROTECTED_TABLES` dict (top of the file) holds, per table, the
  column-allowlist baked into each trigger function body. This is the DB-level
  half of the finalize protection (Order, DeliveryNoteReseller, InvoiceReseller
  + the 6 content models). Without it, finalized rows can be silently mutated
  via `.update()` / raw SQL. **The whole installer (`PROTECTED_TABLES` +
  `_build_*_sql` helpers) is self-contained — copy it verbatim into the new
  initial migration.** (See CLAUDE.md "FinalizedProtectedMixin" — the Python
  allowlist `ALLOWED_FINALIZED_UPDATES` and this trigger allowlist must stay in
  sync.)
- **`RunPython(_seed, _unseed)`** — seeds default **PaymentCycles + Storage**
  reference data. This is seed data a fresh tenant schema needs, not a backfill
  of existing rows → **re-port.**

### 2. `commissioning/0015_season_one_open.py`
- **`RunSQL`** — creates the partial unique index `season_one_open`
  ("one open Season per …"). It is raw SQL *by necessity*: the condition can't
  be expressed as a Django `Meta.UniqueConstraint` (see the comment in
  `models/basics.py:37`). makemigrations will NOT regenerate it → **re-port the
  `_FORWARD` / `_REVERSE` SQL.**

### 3. `super_admin/0002_seed_ops_checklist.py`
- **`RunPython(_seed_checklist, _unseed_checklist)`** — seeds the super-admin
  **ops-checklist** rows (+ the password-rotation note text). Seed data a fresh
  public schema needs → **re-port.**

### 4. `commissioning/0014_offergroup_is_default_and_more.py` (the SEED half)
- **`RunPython(_seed_default_offer_group, noop)`** — on a fresh DB (no groups)
  it **creates** the default `OfferGroup` (`number=1, name="Standard",
  is_default=True`) — i.e. it seeds, it does NOT no-op. → **re-port the
  RunPython.** (The `AddConstraint` one-default-per-tenant is **confirmed on the
  `OfferGroup` Meta** at `models/resellers.py:55` → regenerates automatically,
  nothing to do.)

## B. CAN drop on a fresh wipe (backfills / dedupes — they no-op on an empty DB)

These only touch *pre-existing* rows. A freshly-created DB has none, so they do
nothing — safe to omit from the squashed migration. The **schema** they ride
alongside (columns, model-Meta constraints) regenerates normally.

### 5. `commissioning/0011_add_invoice_recipient_snapshot.py`
- `RunPython(backfill_recipient_snapshot, noop)` — freezes the §14 recipient on
  **already-finalized** v2 invoices (disables the finalize trigger, updates,
  re-enables). No finalized invoices on a fresh DB → no-op. **Drop the
  RunPython; keep the `recipient_snapshot` AddField (auto-regenerated).**

### 6. `tenants/0006_tenantsettings_..._one_current_per_tenant.py`
- `RunPython(_dedupe_current_settings, noop)` — closes duplicate "current"
  TenantSettings rows. No dups on a fresh DB → no-op. **Drop the RunPython.**
- `AddConstraint(tenantsettings_one_current_per_tenant)` — **confirmed declared
  on the model Meta** (`tenants/models.py:425-434`), so makemigrations
  regenerates it. **Nothing to re-port.**

## Wipe / squash / rename recipe (dev, no prod data)

On a fresh branch:
1. Do the code rename (sed) + `AUTH_USER_MODEL` + the `JasminUser`/`JasminModel`/
   `JasminError` renames if going full Tier-3.
2. Either keep history + add `RenameModel`/`RenameField` migrations, **or**
   squash to fresh initials — in which case, for commissioning, drop in the
   staged `0002` above (covers items 1, 2, 4), and re-port **item 3**
   (super_admin checklist) into the regenerated super_admin migration.
3. Drop & recreate the dev DB → `migrate_schemas --shared` + `--tenant`.
4. `make generate-api` → type-check / lint / build / pytest.

**The trap to avoid:** `rm migrations/* && makemigrations` silently drops the
Group-A ops (triggers, the `season_one_open` index, every seed), leaving a DB
with no finalize-protection triggers and missing seed/reference data. Always
re-port Group A — the staged `0002` does this for commissioning.
