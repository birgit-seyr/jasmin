"""Regenerate PLANNED ChargeSchedule rows for all subscriptions.

Idempotent. Safe to run on a cron / Celery beat. Schedule it weekly.

Usage:
    python manage.py regenerate_charge_schedules                 # all tenants
    python manage.py regenerate_charge_schedules --tenant <slug>  # one tenant
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from apps.payments.services import ChargeScheduleService
from apps.shared.tenants.models import Tenant


class Command(BaseCommand):
    help = "Regenerate PLANNED ChargeSchedule rows for all active subscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            help="Limit to one tenant (schema_name). Default: all active tenants.",
            default=None,
        )

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant")
        if tenant_slug:
            tenants = Tenant.objects.filter(schema_name=tenant_slug)
        else:
            tenants = Tenant.objects.filter(is_active=True).exclude(
                schema_name="public"
            )

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                self.stdout.write(f"Tenant {tenant.schema_name}: regenerating...")
                result = ChargeScheduleService.regenerate_all()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  done: {len(result)} subscriptions processed."
                    )
                )
