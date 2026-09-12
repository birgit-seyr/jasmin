"""One-shot: recompute shares whose weeks contain donation jokers.

Donation jokers used to be counted in PRODUCTION demand (theoreticals,
movements, share_type_variation amounts). They are now excluded — a donation
joker is billed but not grown/packed. Existing ``TheoreticalHarvest`` /
``MovementShareArticle`` rows were built with the old, inflated counts, so this
recomputes the affected shares to drop those contributions. Run ONCE after
deploying the counting change.

Idempotent (``recompute_shares`` is) — no data migration, forward-only-safe.
Recomputes per (year, week) so each transaction stays bounded.

Usage:
    python manage.py recompute_donation_joker_shares                  # all tenants
    python manage.py recompute_donation_joker_shares --tenant <slug>  # one tenant
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from apps.shared.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "Recompute shares in weeks that contain donation jokers, so existing "
        "theoreticals/movements drop the now-excluded donation-joker demand."
    )

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
                self._recompute_tenant(tenant.schema_name)

    def _recompute_tenant(self, schema_name: str) -> None:
        from apps.commissioning.models import ShareContent, ShareDelivery
        from apps.commissioning.services.recompute import recompute_shares

        donation_weeks = sorted(
            set(
                ShareDelivery.objects.filter(donation_joker_taken=True).values_list(
                    "share__year", "share__delivery_week"
                )
            )
        )
        if not donation_weeks:
            self.stdout.write(f"Tenant {schema_name}: no donation jokers — skip.")
            return

        total = 0
        for year, week in donation_weeks:
            # Every share WITH content in the week — a superset of the strictly
            # affected ones (recompute is idempotent, so recomputing an
            # unchanged share is a no-op). One call per week keeps the
            # select_for_update transaction bounded.
            share_ids = list(
                ShareContent.objects.filter(share__year=year, share__delivery_week=week)
                .values_list("share_id", flat=True)
                .distinct()
            )
            if share_ids:
                recompute_shares(share_ids)
                total += len(share_ids)

        self.stdout.write(
            self.style.SUCCESS(
                f"Tenant {schema_name}: recomputed {total} share(s) across "
                f"{len(donation_weeks)} donation week(s)."
            )
        )
