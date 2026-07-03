"""Seed 5 active JasminUsers + pending Member rows for manual UI testing.

Three ways to run it (all equivalent — pick whichever works for your
setup):

  A. As a standalone script with the tenant in an env var:

         JASMIN_SCHEMA=test poetry run python scripts/seed_pending_members.py

     This is the most reliable — no shell piping, no special
     django-tenants command wrapping.

  B. Via the tenant-aware shell (django-tenants wraps the stock
     ``shell``):

         poetry run python manage.py tenant_command shell --schema=test \\
             < scripts/seed_pending_members.py

  C. From inside an already-open shell:

         poetry run python manage.py tenant_command shell --schema=test
         >>> exec(open('scripts/seed_pending_members.py').read())

Refuses to run against the public schema so an accidental run without
a tenant set doesn't leak test rows into shared data.

Idempotent: re-running skips emails that already exist instead of
crashing on the unique constraint.

The cleanup snippet to delete the seeded rows is printed at the end
of every successful run.
"""

# Standalone-script bootstrap: ``manage.py shell`` already has Django
# loaded, but running this file via ``python`` directly does not. The
# try/except block handles both cases without breaking the shell-exec
# path (where ``DJANGO_SETTINGS_MODULE`` is already set and
# ``django.setup()`` has run).
import os
import sys

from django.apps import apps as _django_apps

if not _django_apps.ready:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()

from django.db import connection, transaction
from django_tenants.utils import schema_context

from apps.accounts.models import JasminUser
from apps.authz.roles import Role
from apps.commissioning.models import Member
from apps.shared.tenants.models import Tenant

PASSWORD = "Test-Test-2026"
EMAIL_DOMAIN = "example.com"
SEED_PREFIX = "pending"
COUNT = 5


def _seed():
    if connection.schema_name == "public":
        raise RuntimeError(
            "Refusing to seed test data into the public schema. "
            "Re-open the shell with --schema=<tenant_schema_name> "
            "or set JASMIN_SCHEMA=<schema> before invoking python."
        )

    print(f"Seeding into tenant schema: {connection.schema_name}")

    created = []
    with transaction.atomic():
        for i in range(1, COUNT + 1):
            first = f"Pending{i}"
            last = "Applicant"
            email = f"{SEED_PREFIX}{i}@{EMAIL_DOMAIN}"

            if JasminUser.objects.filter(email__iexact=email).exists():
                print(f"  skip {email} — JasminUser already exists")
                continue

            # ``create_user`` calls ``set_password()`` which bypasses
            # the zxcvbn validators applied at the form / serializer
            # layer — perfect for seed data; do NOT mirror this
            # shortcut in production code paths.
            user = JasminUser.objects.create_user(
                first_name=first,
                last_name=last,
                email=email,
                password=PASSWORD,
                account_status="active",
                roles=[Role.MEMBER],
            )

            member = Member.objects.create(
                first_name=first,
                last_name=last,
                email=email,
                user=user,
                admin_confirmed=False,
                is_active=True,
                is_trial=False,
            )
            created.append((email, user.pk, member.pk))
            print(f"  created {email}  user={user.pk}  member={member.pk}")

    print()
    print(f"Done. {len(created)} pending member(s) seeded.")
    if created:
        print(f"Login: any of the emails above with password '{PASSWORD}'")
        print(
            "Member portal should show the 'Your application is being "
            "reviewed' gate; office should see them at the top of "
            "Members.tsx after sorting by the admin-status column."
        )
        print()
        print("--- cleanup snippet (paste into the same shell to remove) ---")
        print("from apps.accounts.models import JasminUser")
        print("from apps.commissioning.models import Member")
        emails_repr = repr([row[0] for row in created])
        print(f"emails = {emails_repr}")
        print("Member.objects.filter(email__in=emails).delete()")
        print("JasminUser.objects.filter(email__in=emails).delete()")


def _run():
    """Resolve which schema to operate on, then call ``_seed``.

    Resolution order:
      1. ``JASMIN_SCHEMA`` env var — explicit override, wins over
         whatever the shell already activated. Useful for path (A).
      2. The schema currently active on ``connection.schema_name``
         (set by ``manage.py tenant_command shell`` or
         ``schema_context``).
      3. Otherwise ``public`` → ``_seed`` refuses, telling the caller
         what to set.
    """
    requested = os.environ.get("JASMIN_SCHEMA")
    if requested:
        if not Tenant.objects.filter(schema_name=requested).exists():
            print(
                f"No Tenant row with schema_name={requested!r}. "
                f"Available schemas: "
                f"{sorted(Tenant.objects.values_list('schema_name', flat=True))}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        with schema_context(requested):
            _seed()
    else:
        _seed()


_run()
