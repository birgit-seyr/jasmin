"""Removes ``OfferGroup.is_active`` from the model, keeping its column.

The code no longer reads or writes the flag, but the column stays in the
database for now: a rollback to an earlier release still selects and writes
it, and a column dropped under that release would break every offer group
query it makes. Only the model state forgets the field here.

The column is ``NOT NULL`` with the default held in Python alone, so an insert
from this code, which leaves the column out, needs a database default; the
migration gives it one (``true``, the value the old default wrote). Dropping
the column is a later migration, once no kept release reads it any more.

The reverse removes the database default and puts the field back into the
state; both are safe, since the column and its rows were never touched.
"""

from django.db import migrations

TABLE = "commissioning_offergroup"


class Migration(migrations.Migration):

    dependencies = [
        ("commissioning", "0031_waste_unique_per_storage"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="offergroup",
                    name="is_active",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=f"ALTER TABLE {TABLE} ALTER COLUMN is_active SET DEFAULT true;",
                    reverse_sql=f"ALTER TABLE {TABLE} ALTER COLUMN is_active DROP DEFAULT;",
                ),
            ],
        ),
    ]
