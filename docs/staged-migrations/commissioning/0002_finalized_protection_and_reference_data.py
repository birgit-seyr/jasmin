"""Consolidated handwritten commissioning migration (post-WIPE / post-squash).

DROP-IN PROCEDURE (dev wipe, no prod data):
  1. Delete the whole commissioning migration history (0001..00NN).
  2. `python manage.py makemigrations commissioning` → a single `0001_initial`
     that carries the FULL end-state schema (incl. OfferGroup.is_default + the
     `offergroup_single_default` constraint, the Season model, PaymentCycle,
     Storage, and every FinalizedProtected table).
  3. Copy THIS file to `apps/commissioning/migrations/` as
     `0002_finalized_protection_and_reference_data.py`. If makemigrations split
     commissioning into more than one initial migration, point the dependency
     below at the LAST one.
  4. Drop & recreate the DB → `migrate_schemas --shared` + `--tenant`.

This file is the ONLY handwritten commissioning migration. It reproduces, in
their FINAL state, the things `makemigrations` cannot regenerate:

  1. The PostgreSQL finalized-protection triggers (BEFORE UPDATE / DELETE), with
     the current per-table allowlists (incl. `note` on invoicereseller).
  2. The `season_one_open` partial unique index — raw SQL by necessity: Season's
     overlap group is GLOBAL (no column to scope a Django Meta UniqueConstraint
     on), so makemigrations will never emit it.
  3. The reference-data + bootstrap seed: PaymentCycles, Storages, and the
     single default OfferGroup ("Standard").

What is intentionally NOT here:
  - `is_default` field + `offergroup_single_default` constraint → regenerated
    into 0001_initial (they live on the OfferGroup model Meta).
  - Fresh-DB-only data backfills / dedupes (old recipient_snapshot backfill,
    TenantSettings dedupe, etc.) → no legacy rows on a brand-new DB.
  - The super-admin ops-checklist seed → that's a PUBLIC-schema (`super_admin`)
    app; it stays in `apps/shared/super_admin/migrations/` and cannot live here.

KEEP IN SYNC: each table's allowlist below must match that model's
`FinalizedProtectedMixin.ALLOWED_FINALIZED_UPDATES` (see CLAUDE.md). A future
allowlist change needs a follow-up migration that rebuilds the function.
"""

from __future__ import annotations

from django.db import migrations

# table -> {allowed columns when finalized, one-way (cannot unfinalize)}.
# ``is_finalized`` itself is always implicitly allowed.
PROTECTED_TABLES: dict[str, dict] = {
    "commissioning_offer": {"allowed": ["amount"], "one_way": False},
    "commissioning_order": {"allowed": ["note"], "one_way": True},
    "commissioning_ordercontent": {"allowed": [], "one_way": False},
    "commissioning_crateordercontent": {"allowed": [], "one_way": False},
    "commissioning_cratedeliverynotecontent": {"allowed": [], "one_way": False},
    "commissioning_cratecontentinvoicereseller": {"allowed": [], "one_way": False},
    "commissioning_deliverynotecontent": {"allowed": [], "one_way": False},
    "commissioning_invoiceresellercontent": {"allowed": [], "one_way": False},
    "commissioning_deliverynotereseller": {
        "allowed": ["file", "has_been_sent_to_reseller_at"],
        "one_way": True,
    },
    "commissioning_invoicereseller": {
        "allowed": [
            "has_been_paid",
            "paid_at",
            "cancelled_by_invoice_id",
            "has_been_sent_to_reseller_at",
            "has_been_sent_to_accounting_at",
            "file",
            "xml_file",
            "note",
        ],
        "one_way": True,
    },
}


# ---- trigger SQL builders (final-state, one-way aware) --------------------
def _build_allowed_array_literal(allowed_columns: list[str]) -> str:
    quoted = ", ".join(f"'{c}'" for c in allowed_columns + ["is_finalized"])
    return quoted or "''"


def _build_function_sql(table: str, allowed_columns: list[str], one_way: bool) -> str:
    allowed_array_literal = _build_allowed_array_literal(allowed_columns)
    fn_name = f"{table}_finalized_protect"

    one_way_block = ""
    if one_way:
        one_way_block = f"""
        IF OLD.is_finalized AND NOT NEW.is_finalized THEN
            RAISE EXCEPTION
              'Cannot unfinalize {table}: finalized documents of this type are legally immutable. To reverse, create a storno; to revise, issue a correction document.'
              USING ERRCODE = 'check_violation';
        END IF;
"""

    return f"""
    CREATE OR REPLACE FUNCTION {fn_name}() RETURNS trigger AS $$
    DECLARE
        changed_key text;
        old_json jsonb;
        new_json jsonb;
        allowed text[] := ARRAY[{allowed_array_literal}]::text[];
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.is_finalized THEN
                RAISE EXCEPTION
                  'Cannot delete row in {table}: it has been finalized'
                  USING ERRCODE = 'check_violation';
            END IF;
            RETURN OLD;
        END IF;

        IF NOT OLD.is_finalized THEN
            RETURN NEW;
        END IF;
{one_way_block}
        old_json := to_jsonb(OLD);
        new_json := to_jsonb(NEW);

        FOR changed_key IN
            SELECT key
            FROM jsonb_each(old_json)
            WHERE old_json->key IS DISTINCT FROM new_json->key
        LOOP
            IF NOT (changed_key = ANY(allowed)) THEN
                RAISE EXCEPTION
                  'Cannot update column "%" on {table}: row has been finalized. Allowed columns: %',
                  changed_key, allowed
                  USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def _build_trigger_sql(table: str) -> str:
    fn_name = f"{table}_finalized_protect"
    trg_name = f"{table}_finalized_protect_trg"
    return f"""
    DROP TRIGGER IF EXISTS {trg_name} ON {table};
    CREATE TRIGGER {trg_name}
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION {fn_name}();
    """


def _build_drop_sql(table: str) -> str:
    fn_name = f"{table}_finalized_protect"
    trg_name = f"{table}_finalized_protect_trg"
    return f"""
    DROP TRIGGER IF EXISTS {trg_name} ON {table};
    DROP FUNCTION IF EXISTS {fn_name}();
    """


def _build_forward_sql() -> str:
    parts = []
    for table, spec in PROTECTED_TABLES.items():
        parts.append(_build_function_sql(table, spec["allowed"], spec["one_way"]))
        parts.append(_build_trigger_sql(table))
    return "\n".join(parts)


def _build_reverse_sql() -> str:
    return "\n".join(_build_drop_sql(t) for t in PROTECTED_TABLES)


# ---- season_one_open partial unique index (DB backstop) -------------------
# Season's overlap group is GLOBAL (overlap_unique_fields = ()), so its "at most
# one OPEN season" invariant has no grouping column to scope a Django Meta
# UniqueConstraint on. All open rows collide on one key → at most one open
# season globally. handle_succession enforces it in Python, but that is a TOCTOU
# check that bulk_create / QuerySet.update bypass; this is the DB backstop.
_SEASON_FORWARD = (
    "CREATE UNIQUE INDEX season_one_open "
    "ON commissioning_season ((valid_until IS NULL)) "
    "WHERE valid_until IS NULL;"
)
_SEASON_REVERSE = "DROP INDEX IF EXISTS season_one_open;"


# ---- reference data + bootstrap seed --------------------------------------
PAYMENT_CYCLE_CHOICES = [
    "WEEKLY",
    "BIWEEKLY",
    "MONTHLY",
    "QUARTERLY",
    "SEMI_ANNUALLY",
    "ANNUALLY",
]

STORAGE_DEFAULTS = [
    # (name, description, is_short_term, is_long_term)
    ("Kurz", "Kurzzeitlager", True, False),
    ("Lang", "Langzeitlager", False, True),
]


def _seed(apps, schema_editor):
    PaymentCycle = apps.get_model("commissioning", "PaymentCycle")
    Storage = apps.get_model("commissioning", "Storage")
    OfferGroup = apps.get_model("commissioning", "OfferGroup")

    for choice in PAYMENT_CYCLE_CHOICES:
        PaymentCycle.objects.get_or_create(choice=choice, defaults={"is_active": True})

    for name, description, short_term, long_term in STORAGE_DEFAULTS:
        Storage.objects.get_or_create(
            name=name,
            defaults={
                "description": description,
                "is_active": True,
                "is_short_term_harvest_storage": short_term,
                "is_long_term_harvest_storage": long_term,
            },
        )

    # Exactly one default offer group ("Standard"). Idempotent: a no-op once a
    # default exists, so it is safe on both new-tenant bootstrap and re-runs.
    if not OfferGroup.objects.filter(is_default=True).exists():
        existing = OfferGroup.objects.order_by("number").first()
        if existing is not None:
            existing.is_default = True
            existing.save(update_fields=["is_default"])
        else:
            OfferGroup.objects.create(number=1, name="Standard", is_default=True)


def _unseed(apps, schema_editor):
    # Dev-sanity reverse only. The OfferGroup default is forward-only (we never
    # un-seed it): unflagging/deleting it could orphan offers, and a reverse is
    # not a production rollback path anyway.
    PaymentCycle = apps.get_model("commissioning", "PaymentCycle")
    Storage = apps.get_model("commissioning", "Storage")
    PaymentCycle.objects.filter(choice__in=PAYMENT_CYCLE_CHOICES).delete()
    Storage.objects.filter(name__in=[n for n, _, _, _ in STORAGE_DEFAULTS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("commissioning", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=_build_forward_sql(), reverse_sql=_build_reverse_sql()),
        migrations.RunSQL(sql=_SEASON_FORWARD, reverse_sql=_SEASON_REVERSE),
        migrations.RunPython(_seed, _unseed),
    ]
