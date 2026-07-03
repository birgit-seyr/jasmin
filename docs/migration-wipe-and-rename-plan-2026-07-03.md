# Migration wipe + tapir→okapi rename — plan & audit (2026-07-03)

Goal: wipe all migrations, rebrand `tapir` → new name, regenerate clean
migrations, re-author the hand-written pieces, commit the license last.

This file answers: **after a wipe, what does `makemigrations` regenerate for
free, and what must be preserved by hand?** — and scopes the rename's real DB
impact.

---

## PRECONDITION (blocker)

CLAUDE.md: **migrations are forward-only in prod.** Wiping migration history
means an existing prod/tenant DB can no longer `migrate_schemas` forward against
the new tree. This plan is safe **only if there is no live database whose
migration history matters** (pre-release / dev-only), OR you are willing to
rebuild every schema from scratch (fresh public + tenant schemas).

If a real prod DB exists → do **not** wipe. Do the `TapirUser` rename as a
single `RenameModel` migration instead and keep history.

---

## Part A — Migration wipe

`makemigrations` regenerates **everything expressed on the model** (fields, FKs,
indexes, and every `Meta.constraints` entry — Check / Unique / Exclusion).
It does **not** regenerate raw SQL, triggers, or data. On a **fresh/empty DB**,
backfills and pre-constraint dedup steps are also no-ops.

### A.1 MUST be preserved by hand (will NOT come back on regenerate)

| # | What | Lives in today | Kind | Note |
|---|------|----------------|------|------|
| 1 | FinalizedProtection trigger fns + triggers | `commissioning/0002` | `RunSQL` CREATE FUNCTION/TRIGGER | `makemigrations` never emits triggers. Targets `commissioning_*` tables only — **does not touch the user table**, so it carries verbatim regardless of any `TapirUser` rename. |
| 2 | Reference seed: `PaymentCycle` choices + `Storage` rows | `commissioning/0002` `_seed` | `RunPython` | Seed data every install needs. |
| 3 | `season_one_open` partial unique index | `commissioning/0015` | `RunSQL` partial index | **Non-Meta constraint** (Season's overlap group is global → no column to key a Django `UniqueConstraint` on). **Not in 0002 — easy to forget.** |
| 4 | Default `Standard` OfferGroup seed | `commissioning/0014` `_seed_default_offer_group` | `RunPython` | Runs on new-tenant bootstrap; idempotent. Seed, not backfill → keep. |
| 5 | Ops-checklist seed | `shared/super_admin/0002` `_seed_checklist` | `RunPython` | Seed data (verify a fresh install needs it; if yes → keep). |

> **Key finding:** the manual pieces are scattered across **at least 5
> migrations in 3 apps** — NOT just `commissioning/0002`. Re-authoring only
> "0002" would silently drop items #3, #4, #5 (a missing partial index + two
> seeds). This is the main risk of the wipe.

Because no app_label changes (see Part B), every table/column name the RunSQL
and seeds reference is **unchanged**. So items #1–#5 can be **carried forward
near-verbatim** — copy the files, renumber their `dependencies` to sit after the
new squashed `0001`. It's "carry + re-point", not "rewrite from memory".

### A.2 Safe to DROP (auto-regenerated, or empty-DB no-op)

- **All `Meta.constraints`** (Check / Unique / Exclusion) across `0001, 0003,
  0004, 0006, 0007, 0008, 0010, 0012, 0013, 0019, 0030, 0036, 0042` +
  `payments 0001/0004`, `notifications 0002`, `gdpr 0003`, `accounts 0003`,
  `shared/tenants 0006/0011`. → regenerated into the fresh `0001`s.
  (Includes the `0042` ExclusionConstraint — it lives in `Meta.constraints`.)
- **All backfills** (existing-row migrations; nothing to migrate on empty DB):
  `commissioning 0011, 0032, 0033, 0034`, `shared/tenants 0006` dedupe.
- **All pre-constraint dedup `RunSQL`** (nothing to dedup on empty DB):
  `commissioning 0016, 0042`, `gdpr 0003`.
- **All rename/churn migrations** (collapse into fresh `0001`):
  `shared/tenants 0007/0008/0009/0013`, `commissioning 0003/0007` constraint
  swaps.

### A.3 Procedure

1. `git switch -c rename-okapi` (do this on a branch).
2. **Copy the 5 files in A.1 out of the tree** (to `/scratchpad` or a stash) —
   they are your re-author source of truth.
3. Delete `apps/**/migrations/0*.py` (keep every `__init__.py`).
4. Do the rename (Part B) **before** regenerating, so the fresh `0001`s bake in
   the new model name.
5. `poetry run python manage.py makemigrations` → one clean `0001` per app.
6. Re-add the A.1 items as follow-on migrations (mirror current style: one
   `0002_finalized_protection_and_reference_data` for the triggers+seed, plus
   small ones for the season index and the seeds — or fold sensibly). Re-point
   `dependencies` to the new `0001`s.
7. Rebuild: `migrate_schemas --shared` then `--tenant` on a fresh DB.
8. Oracle: `pytest` (the `test_pytest` schema rebuilds from the new tree) +
   `test_finalized_allowlist_sync.py` (proves triggers installed) green.

---

## Part B — The rename (tapir → okapi)

~258 files mention `tapir`. Almost all are **cosmetic** and DB-neutral. The DB
surface is tiny.

### B.1 DB-affecting (exactly one thing)

- **`TapirUser` → `OkapiUser`** (`apps/accounts/models.py`). Concrete model →
  table `accounts_tapiruser` becomes `accounts_okapiuser`. Also flips
  `AUTH_USER_MODEL = "accounts.TapirUser"` and **~847 code references**.
  During a wipe this table rename is **free** — the regenerated `0001` just
  `CreateModel`s it under the new name; no `RenameModel` needed. But the 847
  refs are a big mechanical surface → do it scripted, with `type-check` +
  `pytest` as the oracle.

### B.2 DB-neutral (pure Python / branding)

- **`TapirModel`** (abstract base, in 5 apps) → `OkapiModel`. Abstract → no
  table, not in migration state. Zero DB impact.
- `TapirError`, `TapirUserManager`, other `Tapir*` identifiers → find/replace.
- **No `db_table` override contains `tapir`** (they're `email_template`,
  `super_admin`, `tenant_email_config`, …) → untouched.
- **No schema name contains `tapir`** (`public`, tenant schemas, `test_pytest`)
  → tenant schema names are data/runtime, not migrations.
- Project package is **`config`**, not `tapir` (`config.settings`,
  `config.tenant_urls`, `config.wsgi`) → no package rename needed.
- Cosmetic: repo dir `tapir-core/`, `pyproject` name `tapir-django-core`, README,
  UI strings, docker/Makefile paths. Rename anytime; independent of migrations.

### B.3 Insight: the wipe and the rename are largely orthogonal

Table names derive from `app_label` (`accounts`, `commissioning`, …), none of
which contain `tapir`. So the rebrand does **not** require a migration wipe —
the only DB-coupled part is `TapirUser`, and even that is a single `RenameModel`
if you *didn't* wipe. Bundling them is fine (one clean-slate moment), but they
are separable, and the **wipe carries all the risk** (the forward-only rule +
the 5 scattered manual pieces). The rename alone is low-risk.

---

## Ordering vs. the license commit

Correct instinct to rename first: the `LICENSE` stays verbatim (brand-free), but
`README.md`'s title ("Tapir Platform") and the copyright line should reflect the
new name. So: **rename → regenerate → verify → then commit the license** in the
rebranded tree.
