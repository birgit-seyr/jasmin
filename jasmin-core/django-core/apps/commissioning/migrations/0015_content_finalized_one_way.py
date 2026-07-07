"""Make the six reseller-document *content* tables one-way finalized.

Their parents (Order / DeliveryNoteReseller / InvoiceReseller) are already
one-way — legally immutable once issued (GoBD / HGB §257 / UStG §14). The
content lines carry the amount / price / rabatt / tax that sum into the
parent's sealed ``document_hash``, so a finalized line must be equally
immutable: otherwise it could be unfinalized, its amount edited, and
re-finalized while the parent stays "immutable", silently breaking the
integrity of a document the system reports as final.

This rebuilds the Postgres ``*_finalized_protect`` trigger FUNCTIONS for the
six content tables with the one-way RAISE block (``OLD.is_finalized AND NOT
NEW.is_finalized`` → reject), mirroring the Python ``IS_FINALIZED_ONE_WAY =
True`` now set on the models. The trigger bindings from 0002 already point at
these function names; ``CREATE OR REPLACE FUNCTION`` swaps the body in place,
so no trigger re-binding is needed.

Self-contained (copies the 0002 builder shape) so a later edit to 0002 cannot
silently change the SQL this migration emits. Fully reversible — a pure
function-body swap, touching no data — so the reverse restores the prior
non-one-way body rather than a noop.
"""

from __future__ import annotations

from django.db import migrations

# The six line-item content tables. Each keeps its finalized allowlist EMPTY
# (nothing but ``is_finalized`` may change once finalized); only the one-way
# flag flips, so the allowed array is always just ``is_finalized``.
CONTENT_TABLES = [
    "commissioning_ordercontent",
    "commissioning_crateordercontent",
    "commissioning_cratedeliverynotecontent",
    "commissioning_cratecontentinvoicereseller",
    "commissioning_deliverynotecontent",
    "commissioning_invoiceresellercontent",
]


def _function_sql(table: str, one_way: bool) -> str:
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
        allowed text[] := ARRAY['is_finalized']::text[];
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


def _build(one_way: bool) -> str:
    return "\n".join(_function_sql(table, one_way) for table in CONTENT_TABLES)


class Migration(migrations.Migration):
    dependencies = [
        ("commissioning", "0014_reseller_contact_required"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_build(one_way=True),
            reverse_sql=_build(one_way=False),
        ),
    ]
