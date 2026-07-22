"""Consolidated handwritten commissioning migration (post-squash).

After deleting the old migration history and regenerating a single
``0001_initial`` with ``makemigrations``, this file is the ONLY handwritten
commissioning migration. It reproduces, in their FINAL state, the things
``makemigrations`` cannot regenerate:

  1. The PostgreSQL finalized-protection triggers (functions with the current
     allowlists incl. ``note`` on invoicereseller, plus the trigger bindings).
  2. The reference-data seed (PaymentCycles + Storage).
  3. The ``season_one_open`` partial unique index — Season's overlap group is
     GLOBAL, so its "at most one OPEN season" invariant has no grouping column
     to key a Django ``UniqueConstraint`` on; it is a raw partial index that
     ``makemigrations`` never regenerates.
  4. The default OfferGroup seed (every fresh tenant needs exactly one).

Fresh-DB-only data backfills are intentionally DROPPED — on a brand-new
database there are no legacy rows to transform and the regenerated
0001_initial already carries the end-state schema.

KEEP IN SYNC: each table's allowlist below must match that model's
``FinalizedProtectedMixin.ALLOWED_FINALIZED_UPDATES`` (see CLAUDE.md). A future
allowlist change needs a follow-up migration that rebuilds the function.
"""

from __future__ import annotations

from django.db import migrations

# table -> {allowed columns when finalized, one-way (cannot unfinalize)}.
# ``is_finalized`` itself is always implicitly allowed.
#
# ⚠️ THIS DICT IS THE INSTALL-TIME STATE, NOT THE EFFECTIVE STATE. The six
# ``*content*`` tables below record ``one_way: False`` — that is the trigger
# body this migration originally installed. Migration
# ``0015_content_finalized_one_way`` LATER rebuilds those six trigger functions
# with ``one_way=True`` (GoBD / HGB §257 / UStG §14: a finalized content line is
# legally immutable, mirroring ``IS_FINALIZED_ONE_WAY = True`` on the models).
# So the LIVE database has all six content tables one-way; this ``False`` is
# stale history kept only because migrations are frozen + forward-only.
#
# DO NOT copy a content row's ``one_way: False`` when building a NEW trigger
# migration — doing so would silently un-protect legally-immutable lines. The
# authoritative "does the model match the installed trigger?" check is the drift
# test ``tests/tests_lifecycle/test_finalized_allowlist_sync.py`` (model ↔ LIVE
# trigger) plus ``tests/tests_lifecycle/test_finalized_protection_dict_ssot.py``
# (this dict + the 0015 override ↔ model).
PROTECTED_TABLES: dict[str, dict] = {
    "commissioning_offer": {"allowed": ["amount"], "one_way": False},
    "commissioning_order": {"allowed": ["note"], "one_way": True},
    # one_way flipped to True by 0015 (effective state); see the warning above.
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


# ---- reference data seed (PaymentCycles + Storage) ------------------------
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


# No reverse for the reference-data seed. Forward-only: prod never un-seeds, and
# a naive delete of the Storage rows would CASCADE into real documentation
# (Harvest/Purchase/Wash/Clean/Waste/Forecast all FK Storage with on_delete=
# CASCADE) — silently destroying data on a local `migrate ... zero`. A `noop`
# reverse keeps the migration reversible for dev resets without that data loss.


# ---- season "one open" partial unique index (raw SQL — non-Meta) ----------
# The indexed expression is the column-derived ``(valid_until IS NULL)`` (always
# TRUE under the partial WHERE), so all open rows collide on one key → at most
# one open season globally. handle_succession enforces the same in Python, but
# that is a TOCTOU check that bulk_create / QuerySet.update bypass.
_SEASON_INDEX_FORWARD = (
    "CREATE UNIQUE INDEX season_one_open "
    "ON commissioning_season ((valid_until IS NULL)) "
    "WHERE valid_until IS NULL;"
)
_SEASON_INDEX_REVERSE = "DROP INDEX IF EXISTS season_one_open;"


# ---- default OfferGroup seed ----------------------------------------------
def _seed_default_offer_group(apps, schema_editor):
    """Ensure every tenant has exactly one default offer group: flag the
    lowest-numbered existing group, or create a fresh ``Standard`` one. A no-op
    once a default exists, so it is safe on both new-tenant bootstrap (run when
    the schema is created) and existing tenants (next migrate_schemas)."""
    OfferGroup = apps.get_model("commissioning", "OfferGroup")
    if OfferGroup.objects.filter(is_default=True).exists():
        return
    existing = OfferGroup.objects.order_by("number").first()
    if existing is not None:
        existing.is_default = True
        existing.save(update_fields=["is_default"])
    else:
        OfferGroup.objects.create(number=1, name="Standard", is_default=True)


class Migration(migrations.Migration):
    dependencies = [
        ("commissioning", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=_build_forward_sql(), reverse_sql=_build_reverse_sql()),
        migrations.RunPython(_seed, migrations.RunPython.noop),
        migrations.RunSQL(sql=_SEASON_INDEX_FORWARD, reverse_sql=_SEASON_INDEX_REVERSE),
        # Forward-only: reverse is a no-op (we never un-seed in prod).
        migrations.RunPython(_seed_default_offer_group, migrations.RunPython.noop),
    ]
