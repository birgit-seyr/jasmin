"""Seed the tenants the Playwright suite in ``jasmin-core/e2e`` runs against.

Run against the dev stack (``make e2e`` does this before the suite):

    docker compose -f docker-compose.dev.yml exec backend \\
        python manage.py seed_e2e [--reset]

Creates (or refreshes) two tenants of their own, so the suite never reads or
writes the ``test`` tenant a developer works in:

  * ``e2e`` at ``e2e.localhost`` — the tenant every flow runs in;
  * ``e2e_other`` at ``e2e-other.localhost`` — a second tenant with the same
    persona logins, which a session from ``e2e`` must not be accepted on.

Each gets an admin ``admin@<domain>`` and the ``seed_test_users`` personas
(password ``Test-Test-2026``), all in English and without two-factor devices,
so a login through the UI never stops at a code prompt. ``e2e`` also sends its
mail to the dev stack's MailHog and keeps the ``de`` CSV format (``;`` as the
delimiter, ``dd.mm.yyyy`` dates) under its English UI.

The platform gets a super-admin ``e2e-superadmin@example.com`` with the same
password, for the super-admin flow on ``marillen.localhost``.

``--reset`` drops both E2E tenants (row and schema) and provisions them anew.
It only ever deletes the schemas named in ``E2E_TENANTS``.

Dev only: refuses to run when ``DEBUG`` is False, like the seed commands it
builds on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from apps.accounts.services.two_factor_service import remove_all_devices
from apps.shared.tenants.models import Tenant, TenantEmailConfig
from apps.shared.tenants.services import TenantService

E2E_LANGUAGE = "en"
# The dev stack's MailHog, as the backend container reaches it.
E2E_SMTP_HOST = "mailhog"
E2E_SMTP_PORT = 1025
E2E_CSV_FORMAT = "de"
E2E_SUPER_ADMIN_EMAIL = "e2e-superadmin@example.com"
E2E_PASSWORD = "Test-Test-2026"


@dataclass(frozen=True)
class E2ETenant:
    schema: str
    name: str
    domain: str
    # Whether the office flows' commissioning data and the MailHog SMTP
    # set-up go in.
    commissioning_data: bool

    @property
    def admin_email(self) -> str:
        return f"admin@{self.domain}"


E2E_TENANTS = (
    E2ETenant(
        schema="e2e",
        name="E2E Farm",
        domain="e2e.localhost",
        commissioning_data=True,
    ),
    E2ETenant(
        schema="e2e_other",
        name="E2E Other Farm",
        domain="e2e-other.localhost",
        commissioning_data=False,
    ),
)


class Command(BaseCommand):
    help = (
        "Seed the e2e / e2e_other tenants (e2e.localhost, e2e-other.localhost) "
        "with persona logins for the Playwright suite."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Drop the E2E tenants and provision them anew.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        if not settings.DEBUG:
            raise CommandError(
                "seed_e2e is a development helper and refuses to run with "
                "DEBUG=False. It mints fixed-password logins (incl. an ADMIN) "
                "that must never reach a production database."
            )

        if opts["reset"]:
            self._drop_e2e_tenants()

        for e2e_tenant in E2E_TENANTS:
            call_command(
                "seed_dev_tenant",
                schema=e2e_tenant.schema,
                name=e2e_tenant.name,
                domain=e2e_tenant.domain,
                admin_email=e2e_tenant.admin_email,
                language=E2E_LANGUAGE,
                stdout=self.stdout,
            )
            self._remove_two_factor(e2e_tenant.schema)
            if e2e_tenant.commissioning_data:
                self._mail_to_mailhog_and_csv_format(e2e_tenant.schema)
                with schema_context(e2e_tenant.schema):
                    call_command("seed_e2e_commissioning", stdout=self.stdout)

        with schema_context(get_public_schema_name()):
            call_command(
                "createsuperadmin",
                email=E2E_SUPER_ADMIN_EMAIL,
                password=E2E_PASSWORD,
                first_name="E2E",
                last_name="Super-Admin",
                update_if_exists=True,
                stdout=self.stdout,
            )

        self.stdout.write(self.style.SUCCESS("E2E tenants ready."))

    def _drop_e2e_tenants(self) -> None:
        schemas = [e2e_tenant.schema for e2e_tenant in E2E_TENANTS]
        with schema_context(get_public_schema_name()):
            tenants = list(Tenant.objects.filter(schema_name__in=schemas))
        for tenant in tenants:
            TenantService().drop_tenant(tenant)
            self.stdout.write(f"DROPPED tenant '{tenant.schema_name}'")

    def _mail_to_mailhog_and_csv_format(self, schema: str) -> None:
        # A tenant without its own SMTP host can't send at all, and the
        # invitation flow reads its mail from MailHog. The private host passes
        # the SMTP guard because SMTP_ALLOW_PRIVATE_HOSTS follows DEBUG.
        with schema_context(get_public_schema_name()):
            tenant = Tenant.objects.get(schema_name=schema)
            TenantEmailConfig.objects.update_or_create(
                tenant=tenant,
                defaults={
                    "smtp_host": E2E_SMTP_HOST,
                    "smtp_port": E2E_SMTP_PORT,
                    "smtp_username": "",
                    "smtp_password": "",
                    "smtp_use_tls": False,
                    "smtp_use_ssl": False,
                    "from_email": f"office@{tenant.schema_name}.example.com",
                    "from_name": tenant.name,
                    "is_active": True,
                },
            )
            if tenant.csv_format != E2E_CSV_FORMAT:
                tenant.csv_format = E2E_CSV_FORMAT
                tenant.save(update_fields=["csv_format"])

    def _remove_two_factor(self, schema: str) -> None:
        # A persona someone enrolled by hand would stop the suite's UI login at
        # the code prompt.
        with schema_context(schema):
            for user in get_user_model().objects.all():
                remove_all_devices(user=user)
