"""Name the app's own database role in the Postgres password runbook.

backend and huey log in as APP_DB_USER, a role that owns the database without
being a superuser; the superuser POSTGRES_USER is left to backups and restores.
The description 0003 gave the existing row names only the superuser, so it is
rewritten here.
"""

from django.db import migrations

DB_PASSWORD_RUNBOOK = (
    '"Run rotation" generates the new password and lists the steps. The '
    "database has two logins, each rotated on its own: the app's role "
    "(APP_DB_USER in .env), which backend and huey use, and the superuser "
    "(POSTGRES_USER), which backups and restores use. In short: set the "
    "password with psql's \\password <role> in\n"
    '  docker compose exec postgres sh -c \'psql -U "$POSTGRES_USER" -d '
    '"$POSTGRES_DB"\'\n'
    "set APP_DB_PASSWORD or POSTGRES_PASSWORD in .env, then\n"
    "  docker compose up -d backend huey backup\n"
    "  docker compose restart gateway\n"
    "and check that docker compose exec backup /usr/local/bin/backup.sh now "
    "still writes a backup."
)


def _update_runbook(apps, schema_editor):
    OpsChecklistItem = apps.get_model("super_admin", "OpsChecklistItem")
    OpsChecklistItem.objects.filter(kind="rotate_db_password").update(
        description=DB_PASSWORD_RUNBOOK
    )


class Migration(migrations.Migration):

    dependencies = [
        ("super_admin", "0003_ops_checklist_runbooks"),
    ]

    operations = [
        # Going back keeps this text: the one it replaces leaves out the app's
        # role, which outlives a rollback of the code.
        migrations.RunPython(_update_runbook, migrations.RunPython.noop),
    ]
