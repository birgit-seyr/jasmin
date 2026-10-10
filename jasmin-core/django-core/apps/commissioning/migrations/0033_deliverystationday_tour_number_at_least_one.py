"""Adds ``CHECK (tour_number >= 1)`` to the station-day table, as ``NOT VALID``.

Tours are numbered from 1. ``NOT VALID`` makes Postgres check every row
inserted or updated from now on while skipping the rows already stored, so the
migration cannot fail on a tenant that still holds a station day with tour 0.
Such a row can't be updated until it names a tour of 1 or more — any UPDATE
re-checks the whole row, not just the columns it changes. Once no schema holds
a 0 any more, a later migration runs ``VALIDATE CONSTRAINT``.

The constraint lives in the database only. Django's ``CheckConstraint`` has no
``NOT VALID``: declared in the model's Meta, it would make ``full_clean`` refuse
the remaining 0 rows, and any later change to it would be generated as a plain
``ADD CONSTRAINT``, which checks every stored row and fails while a 0 exists.
The serializers refuse a tour below 1 with their own coded error.

The reverse drops the constraint; no data is touched either way.
"""

from django.db import migrations

TABLE = "commissioning_deliverystationday"
CONSTRAINT = "commissioning_deliverystationday_tour_number_at_least_one"


class Migration(migrations.Migration):

    dependencies = [
        ("commissioning", "0032_remove_offergroup_is_active_from_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} "
                "CHECK (tour_number >= 1) NOT VALID;"
            ),
            reverse_sql=f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT};",
        ),
    ]
