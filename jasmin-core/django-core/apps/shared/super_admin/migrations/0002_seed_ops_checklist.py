"""Consolidated handwritten super_admin migration (post-squash).

After regenerating ``0001_initial`` with ``makemigrations`` (which recreates
the OpsChecklistItem / OpsChecklistRun tables), this is the only handwritten
super_admin migration. It carries forward the ops-checklist SEED that the old
0002 ran — ``makemigrations`` regenerates the tables but never the seed rows.

MOVE-IN: place this in ``apps/shared/super_admin/migrations/`` (renamed to
``0002_seed_ops_checklist.py``) AFTER ``makemigrations`` created
``0001_initial``. If makemigrations produced more than one initial migration,
point the dependency below at the LAST one.
"""

from __future__ import annotations

from django.db import migrations

SEED_ITEMS = [
    # (kind, title, interval_days, description)
    (
        "rotate_django_secret",
        "Rotate DJANGO_SECRET_KEY",
        365,
        "Generate a new key with:\n"
        "  python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'\n"
        "Update .env on prod, redeploy. Active sessions get invalidated "
        "(sessions sign with SECRET_KEY) — communicate before rolling.",
    ),
    (
        "rotate_field_encryption",
        "Rotate FIELD_ENCRYPTION_KEY",
        730,
        "Expensive op: every encrypted column must be re-encrypted with "
        "the new key. Procedure (during a quiet window):\n"
        "  1. Generate the new key:\n"
        "       python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'\n"
        "  2. PREPEND it to FIELD_ENCRYPTION_KEY in .env:\n"
        "       FIELD_ENCRYPTION_KEY=<new>,<old>\n"
        "     and deploy. From now on new writes use the new key; old\n"
        "     reads still work via the old-key fallback.\n"
        "  3. Re-encrypt every existing row:\n"
        "       python manage.py rotate_field_encryption --dry-run   # preview\n"
        "       python manage.py rotate_field_encryption              # for real\n"
        "     Touches 6 fields across 4 models in every tenant schema\n"
        "     + the public schema. Iterator-based, chunked transactions.\n"
        "  4. After it finishes cleanly, drop the old key from .env:\n"
        "       FIELD_ENCRYPTION_KEY=<new>\n"
        "     and deploy again.\n"
        "Backup the DB before step 3 — that's the irreversible step.",
    ),
    (
        "rotate_db_password",
        "Rotate Postgres password",
        365,
        "Change POSTGRES_PASSWORD in .env, run\n"
        "  docker compose exec postgres psql -U postgres -c \\\n"
        "    \"ALTER USER jasmin WITH PASSWORD '<new>';\"\n"
        "then `docker compose up -d` to restart services with new env.",
    ),
    (
        "rotate_bunny_token",
        "Rotate Bunny CDN API token",
        365,
        "Bunny dashboard → Account → API tokens → revoke + regenerate. "
        "Update any tooling that uses it (deploy scripts, dashboards).",
    ),
    (
        "rotate_email_creds",
        "Rotate email-provider credentials",
        365,
        "EMAIL_HOST_USER / EMAIL_HOST_PASSWORD in .env. For SendGrid: "
        "create a new API key, paste, then revoke the old one once you "
        "see a successful email.",
    ),
    (
        "restore_drill",
        "Restore-from-backup drill",
        90,
        "Spin up a throwaway Postgres container, pull yesterday's "
        "backup from Hetzner Storage Box, decrypt, restore, run\n"
        "  SELECT COUNT(*) FROM commissioning_member;\n"
        "Add notes about anything that drifted (script breaks, missing "
        "credentials, etc.) — that's the whole point of the drill.",
    ),
    (
        "postgres_security_upgrade",
        "Postgres security upgrade",
        30,
        "Check https://www.postgresql.org/support/security/ for any "
        "new Postgres 15.x security advisory. If yes: pull the new "
        "image (`docker compose pull postgres`), brief downtime "
        "window, restart. Backups before, smoke test after.",
    ),
    (
        "apt_upgrade",
        "OS apt upgrade",
        30,
        "On the prod host:\n"
        "  sudo apt update && sudo apt upgrade -y\n"
        "If a kernel update lands, schedule the reboot for a quiet "
        "window. unattended-upgrades handles security patches "
        "automatically — this is the monthly catch-all.",
    ),
    (
        "user_account_review",
        "Review super-admin + admin accounts",
        90,
        "List every SuperAdmin row + every JasminUser with admin/office "
        "role across all tenants. Disable anyone who shouldn't have "
        "access anymore (left the project, role changed, etc.).",
    ),
    (
        "dependency_audit",
        "Manual dependency audit",
        90,
        "CI runs pip-audit + npm audit on every PR, but a periodic "
        "human-eyes review catches things the scanners miss (abandoned "
        "packages, license changes, suspicious new maintainers).\n"
        "  cd jasmin-core/django-core && poetry show --outdated\n"
        "  cd jasmin-core/react-core  && npm outdated",
    ),
    (
        "csp_audit",
        "CSP allowlist audit",
        90,
        "Grep csp.violation in security.log over the last quarter. "
        "Every legitimate new external source should already be in "
        "nginx/nginx.conf.template; if you see surprises, investigate.",
    ),
]


def _seed_checklist(apps, schema_editor):
    OpsChecklistItem = apps.get_model("super_admin", "OpsChecklistItem")
    for kind, title, interval, description in SEED_ITEMS:
        OpsChecklistItem.objects.get_or_create(
            kind=kind,
            defaults={
                "title": title,
                "interval_days": interval,
                "description": description,
            },
        )


def _unseed_checklist(apps, schema_editor):
    OpsChecklistItem = apps.get_model("super_admin", "OpsChecklistItem")
    OpsChecklistItem.objects.filter(
        kind__in=[kind for kind, _, _, _ in SEED_ITEMS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("super_admin", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_seed_checklist, _unseed_checklist),
    ]
