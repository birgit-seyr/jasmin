"""Refuse moving a reseller-document content line onto or off a finalized parent.

The ``*_finalized_protect`` trigger functions (installed by 0002, made one-way
for the content tables by 0015) return early for any row that is not itself
finalized (``IF NOT OLD.is_finalized THEN RETURN NEW``) and never look at the
parent document. So a ``QuerySet.update()`` or raw ``UPDATE`` could re-point a
draft line's parent FK onto an already-finalized order / delivery note /
invoice — adding a line to a sealed document — or pull a line off one.

This rebuilds the trigger functions of the six content tables with an extra
block that runs on every UPDATE before that early return: for each parent FK
column (the model's ``PARENT_FK_FIELDS``), when ``NEW.<column> IS DISTINCT
FROM OLD.<column>`` and the old or the new parent row ``is_finalized``, it
raises ``check_violation``. ``FinalizedProtectedMixin.save`` refuses the same
move at the Python layer.

Everything else in the bodies is exactly the 0015 state: the allowlist is
still only ``is_finalized`` and the one-way unfinalize block is kept. The
trigger bindings from 0002 already point at these function names, so
``CREATE OR REPLACE FUNCTION`` swaps the bodies in place.

The parent lookup is schema-qualified with ``TG_TABLE_SCHEMA`` (dynamic SQL)
so it always reads the parent table of the tenant schema the updated row lives
in, independent of the session ``search_path``. It only runs when a parent FK
actually changes, so ordinary updates pay nothing but the column comparison.

Out of scope: the M2M provenance through-tables
(``InvoiceResellerContent.delivery_note_contents``,
``CrateContentInvoiceReseller.crate_delivery_note_contents``) have no trigger.

Self-contained (no imports from other migrations) so a later edit elsewhere
cannot change the SQL this migration emits. Any future rebuild of these
functions must keep the parent-move block — the live-trigger test in
``tests/tests_lifecycle/test_finalized_parent_move.py`` fails otherwise.
Reversible: a pure function-body swap touching no data, so the reverse
restores the 0015 bodies (without the parent-move block).
"""

from __future__ import annotations

from django.db import migrations

# Content table -> its parent FK columns and the finalizable table each points
# at. Mirrors ``PARENT_FK_FIELDS`` on the models (as DB columns).
CONTENT_TABLE_PARENTS: dict[str, list[tuple[str, str]]] = {
    "commissioning_ordercontent": [
        ("order_id", "commissioning_order"),
    ],
    "commissioning_crateordercontent": [
        ("order_id", "commissioning_order"),
        ("order_content_id", "commissioning_ordercontent"),
    ],
    "commissioning_cratedeliverynotecontent": [
        ("delivery_note_id", "commissioning_deliverynotereseller"),
    ],
    "commissioning_cratecontentinvoicereseller": [
        ("invoice_id", "commissioning_invoicereseller"),
    ],
    "commissioning_deliverynotecontent": [
        ("delivery_note_id", "commissioning_deliverynotereseller"),
    ],
    "commissioning_invoiceresellercontent": [
        ("invoice_id", "commissioning_invoicereseller"),
    ],
}


def _parent_move_block(table: str, column: str, parent_table: str) -> str:
    return f"""
        IF NEW.{column} IS DISTINCT FROM OLD.{column} THEN
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I.{parent_table} WHERE id IN ($1, $2) AND is_finalized)',
                TG_TABLE_SCHEMA
            )
            INTO parent_finalized
            USING OLD.{column}, NEW.{column};
            IF parent_finalized THEN
                RAISE EXCEPTION
                  'Cannot move row in {table} onto or off a finalized {parent_table} (column "{column}")'
                  USING ERRCODE = 'check_violation';
            END IF;
        END IF;
"""


def _function_sql(table: str, with_parent_move_block: bool) -> str:
    fn_name = f"{table}_finalized_protect"

    parent_move_declare = ""
    parent_move_blocks = ""
    if with_parent_move_block:
        parent_move_declare = "\n        parent_finalized boolean;"
        parent_move_blocks = "".join(
            _parent_move_block(table, column, parent_table)
            for column, parent_table in CONTENT_TABLE_PARENTS[table]
        )

    return f"""
    CREATE OR REPLACE FUNCTION {fn_name}() RETURNS trigger AS $$
    DECLARE
        changed_key text;
        old_json jsonb;
        new_json jsonb;
        allowed text[] := ARRAY['is_finalized']::text[];{parent_move_declare}
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.is_finalized THEN
                RAISE EXCEPTION
                  'Cannot delete row in {table}: it has been finalized'
                  USING ERRCODE = 'check_violation';
            END IF;
            RETURN OLD;
        END IF;
{parent_move_blocks}
        IF NOT OLD.is_finalized THEN
            RETURN NEW;
        END IF;

        IF OLD.is_finalized AND NOT NEW.is_finalized THEN
            RAISE EXCEPTION
              'Cannot unfinalize {table}: finalized documents of this type are legally immutable. To reverse, create a storno; to revise, issue a correction document.'
              USING ERRCODE = 'check_violation';
        END IF;

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


def _build(with_parent_move_block: bool) -> str:
    return "\n".join(
        _function_sql(table, with_parent_move_block) for table in CONTENT_TABLE_PARENTS
    )


class Migration(migrations.Migration):
    dependencies = [
        ("commissioning", "0023_relax_member_email_uniqueness"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_build(with_parent_move_block=True),
            reverse_sql=_build(with_parent_move_block=False),
        ),
    ]
