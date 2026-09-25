from django.db import migrations, models


class Migration(migrations.Migration):
    """Rename the ``roles`` ATTRIBUTE, leaving the column exactly where it is.

    ``JasminUser.roles`` is now a property backed by ``JasminProfile``, and a
    Django model cannot carry a field and a property of the same name — the
    second declaration silently wins and the first disappears. So the concrete
    field is renamed to ``legacy_roles`` while ``db_column`` pins it to the
    original column.

    State-only: the table is untouched, which is what makes this safe to run
    against a live database and trivially reversible.
    """

    dependencies = [
        ("accounts", "0005_backfill_jasminprofile"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="jasminuser",
                    old_name="roles",
                    new_name="legacy_roles",
                ),
                migrations.AlterField(
                    model_name="jasminuser",
                    name="legacy_roles",
                    field=models.JSONField(
                        blank=True, db_column="roles", default=list, null=True
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
