"""Removes two dead tenant settings from the model, keeping their columns.

``require_admin_approval_for_gdpr_deletion`` has no effect (every deletion
request waits for an admin's approval) and nothing reads ``uses_pledge_round``.
The code no longer reads or writes either, but both columns stay in the
database for now: a rollback to an earlier release still selects and writes
them, and a column dropped under that release would break every settings
query it makes. Only the model state forgets the fields here.

Both columns are ``NOT NULL`` with their default held in Python alone, so an
insert from this code, which leaves them out, needs a database default; the
migration gives each the value the old Python default wrote (``true`` and
``false``). Dropping the columns is a later migration, once no kept release
reads them any more.

The reverse removes the database defaults and puts the fields back into the
state; both are safe, since the columns and their rows were never touched.
"""

from django.db import migrations

TABLE = "tenants_tenantsettings"


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0021_tenantsettings_info_sentence_about_coop_shares"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="tenantsettings",
                    name="require_admin_approval_for_gdpr_deletion",
                ),
                migrations.RemoveField(
                    model_name="tenantsettings",
                    name="uses_pledge_round",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        f"ALTER TABLE {TABLE} ALTER COLUMN "
                        "require_admin_approval_for_gdpr_deletion SET DEFAULT true;"
                    ),
                    reverse_sql=(
                        f"ALTER TABLE {TABLE} ALTER COLUMN "
                        "require_admin_approval_for_gdpr_deletion DROP DEFAULT;"
                    ),
                ),
                migrations.RunSQL(
                    sql=(
                        f"ALTER TABLE {TABLE} ALTER COLUMN "
                        "uses_pledge_round SET DEFAULT false;"
                    ),
                    reverse_sql=(
                        f"ALTER TABLE {TABLE} ALTER COLUMN "
                        "uses_pledge_round DROP DEFAULT;"
                    ),
                ),
            ],
        ),
    ]
