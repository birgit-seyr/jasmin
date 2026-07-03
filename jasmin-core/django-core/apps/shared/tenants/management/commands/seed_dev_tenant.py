"""Seed a local DEV tenant reachable at http://test.localhost:3000.

Run after ``make dev-up``:

    make dev-seed            # -> docker compose exec backend python manage.py seed_dev_tenant

Creates (or refreshes) a ``test`` tenant with:
  * domain ``test.localhost`` (django-tenants resolves the subdomain),
  * an ADMIN login ``admin@test.localhost`` / ``Test-Test-2026`` (roles=[admin]),
  * the member / customer / staff / office persona logins (password
    ``Test-Test-2026``) via the existing ``seed_test_users`` command.

Idempotent: re-running resets the admin password + roles and refreshes the
personas — safe any number of times (e.g. after a plain ``make dev-up``; a
``make dev-reset`` wipes the volume, after which this re-creates everything).

Dev only: refuses to run when ``DEBUG`` is False so the fixed
``Test-Test-2026`` credentials can never be seeded into a production schema.

NOTE: ``test.localhost`` must resolve to your machine. Most setups already
map ``*.localhost`` to 127.0.0.1; if not, add to ``/etc/hosts``:

    127.0.0.1 test.localhost
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from apps.shared.tenants.models import Domain, Tenant
from apps.shared.tenants.services import TenantService


class Command(BaseCommand):
    help = "Seed a local dev tenant (test.localhost) with an admin + persona logins."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--schema", default="test")
        parser.add_argument("--name", default="Test Tenant")
        parser.add_argument("--domain", default="test.localhost")
        parser.add_argument("--admin-email", default="admin@test.localhost")
        parser.add_argument("--admin-password", default="Test-Test-2026")
        parser.add_argument("--language", default="de")
        parser.add_argument(
            "--no-personas",
            action="store_true",
            help="Skip seeding the member/customer/staff/office persona logins.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        # Dev-only: the fixed credentials below must never reach prod.
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev_tenant is a development helper and refuses to run "
                "with DEBUG=False. Provision real tenants via the super-admin "
                "endpoint (POST /tenants/)."
            )

        schema = opts["schema"]
        domain = opts["domain"]
        admin_email = opts["admin_email"]
        admin_password = opts["admin_password"]

        with schema_context(get_public_schema_name()):
            existed = Tenant.objects.filter(schema_name=schema).exists()

        if not existed:
            # Fresh provisioning: schema (auto-migrated) + domain + settings +
            # admin user, all via the same service the super-admin UI uses.
            TenantService().provision_tenant(
                schema_name=schema,
                name=opts["name"],
                domain=domain,
                tenant_language=opts["language"],
                admin_email=admin_email,
                admin_password=admin_password,
                admin_first_name="Test",
                admin_last_name="Admin",
            )
            self.stdout.write(
                self.style.SUCCESS(f"CREATED tenant '{schema}' + admin {admin_email}")
            )
        else:
            # Tenant already there — make sure the domain is mapped, the
            # language is (still) the requested one, and the admin is reset so
            # the documented credentials always work.
            with schema_context(get_public_schema_name()):
                tenant = Tenant.objects.get(schema_name=schema)
                if tenant.tenant_language != opts["language"]:
                    tenant.tenant_language = opts["language"]
                    tenant.save(update_fields=["tenant_language"])
                Domain.objects.get_or_create(
                    domain=domain,
                    defaults={"tenant": tenant, "is_primary": True},
                )
            self.stdout.write(
                self.style.SUCCESS(f"tenant '{schema}' exists — refreshing")
            )

        # Ensure the admin (roles / status / password / language) for both
        # paths — provision_tenant defaults user_language to "en", so this is
        # what makes the admin land in the tenant's language.
        self._reset_admin(schema, admin_email, admin_password, opts["language"])

        if not opts["no_personas"]:
            # member / customer / staff / office / staff+member, password
            # ``Test-Test-2026`` — runs inside the tenant schema. Match their UI
            # language to the tenant so the whole dev tenant is consistent.
            with schema_context(schema):
                call_command("seed_test_users")
                from apps.accounts.models import JasminUser

                JasminUser.objects.exclude(email=admin_email).update(
                    user_language=opts["language"]
                )

        self._print_summary(domain, admin_email, admin_password, opts["no_personas"])

    def _reset_admin(
        self, schema: str, email: str, password: str, language: str
    ) -> None:
        with schema_context(schema):
            from apps.accounts.models import JasminUser

            user, _ = JasminUser.objects.get_or_create(
                email=email,
                defaults={
                    "username": email.lower(),
                    "first_name": "Test",
                    "last_name": "Admin",
                    "roles": ["admin"],
                    "account_status": "active",
                    "user_language": language,
                },
            )
            user.roles = ["admin"]
            user.account_status = "active"
            user.is_active = True
            # provision_tenant creates the admin with the model default
            # user_language="en"; pin it to the tenant language so the admin
            # lands in the right UI locale.
            user.user_language = language
            user.set_password(password)
            user.save()

    def _print_summary(
        self, domain: str, admin_email: str, admin_password: str, no_personas: bool
    ) -> None:
        lines = [
            "",
            "Dev tenant ready:",
            f"  URL:    http://{domain}:3000",
            f"  Admin:  {admin_email} / {admin_password}   (roles: admin)",
        ]
        if not no_personas:
            lines.append(
                "  Also:   test-member@ / test-customer@ / test-staff@ / "
                "test-office@ example.com (password: Test-Test-2026)"
            )
        lines += [
            "",
            f"If {domain} does not resolve, add to /etc/hosts:",
            f"  127.0.0.1 {domain}",
            "",
        ]
        self.stdout.write("\n".join(lines))
