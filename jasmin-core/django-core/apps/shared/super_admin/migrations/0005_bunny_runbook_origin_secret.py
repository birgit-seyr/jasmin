"""Add the origin secret to the Bunny rotation runbook.

The gateway can refuse tenant traffic that doesn't come through the platform's
Bunny pull zone, recognised by a secret Bunny sends with every request
(BUNNY_ORIGIN_SECRET in .env). The description 0003 gave the existing row
covers only the account's API key and says the server uses no Bunny
credential, so it is rewritten here.
"""

from django.db import migrations

BUNNY_RUNBOOK = (
    '"Run rotation" lists the steps. Two credentials, each rotated on its own. '
    "The account's API key, which nothing on the server uses: reset it in the "
    "Bunny dashboard, update any tool outside this platform that uses it, save "
    "it in the password manager and check that two-factor login is still on. "
    "The origin secret, while BUNNY_ORIGIN_SECRET in .env is set: put a new "
    "one (openssl rand -hex 32) in .env as BUNNY_ORIGIN_SECRET_NEXT and run\n"
    "  ./scripts/validate_gateway_config.sh\n"
    "  docker compose up -d gateway\n"
    "set it in every tenant pull zone's edge rule for the X-Origin-Secret "
    "header, wait a few minutes, then move it to BUNNY_ORIGIN_SECRET, empty "
    "BUNNY_ORIGIN_SECRET_NEXT and run both commands again. The check stops a "
    "mistyped secret from taking the gateway, and every host with it, down."
)


def _update_runbook(apps, schema_editor):
    OpsChecklistItem = apps.get_model("super_admin", "OpsChecklistItem")
    OpsChecklistItem.objects.filter(kind="rotate_bunny_token").update(
        description=BUNNY_RUNBOOK
    )


class Migration(migrations.Migration):

    dependencies = [
        ("super_admin", "0004_db_password_runbook_app_role"),
    ]

    operations = [
        # Going back keeps this text: the origin secret it adds may already be
        # set in .env, which a rollback of the code doesn't undo.
        migrations.RunPython(_update_runbook, migrations.RunPython.noop),
    ]
