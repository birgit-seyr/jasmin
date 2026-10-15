"""Removes ``InvoiceReseller.document_hash_version`` from the model, keeping its
column.

Every invoice is sealed with one payload shape now, so nothing reads the
version. The column stays in the database for now: a rollback to an earlier
release still selects and writes it, and a column dropped under that release
would break every invoice query it makes. Only the model state forgets the
field here.

The column is ``NOT NULL`` with the default held in Python alone, so an insert
from this code, which leaves the column out, needs a database default; the
migration gives it one (``1``, the value the old default wrote). Dropping the
column is a later migration, once no kept release reads it any more.

The reverse removes the database default and puts the field back into the
state; both are safe, since the column and its rows were never touched.
"""

from django.db import migrations

TABLE = "commissioning_invoicereseller"


class Migration(migrations.Migration):
    dependencies = [
        ("commissioning", "0033_deliverystationday_tour_number_at_least_one"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="invoicereseller",
                    name="document_hash_version",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        f"ALTER TABLE {TABLE} ALTER COLUMN "
                        "document_hash_version SET DEFAULT 1;"
                    ),
                    reverse_sql=(
                        f"ALTER TABLE {TABLE} ALTER COLUMN "
                        "document_hash_version DROP DEFAULT;"
                    ),
                ),
            ],
        ),
    ]
