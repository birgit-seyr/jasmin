"""Manually reap support tickets whose tenant no longer exists.

Same logic as the Huey periodic task — handy on hosts without a worker, or to
run once right after a tenant teardown.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.shared.support.services import prune_orphan_support_tickets


class Command(BaseCommand):
    help = "Delete support tickets belonging to tenants that no longer exist."

    def handle(self, *args, **options):
        deleted = prune_orphan_support_tickets()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} orphan ticket(s)."))
