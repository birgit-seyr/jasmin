"""Detect (and optionally repair) drift in ``CurrentStockBalance``.

The maintained balance is a projection over the ``MovementShareArticle``
ledger. If any code path mutates movements without going through the
chokepoint that updates the projection, the two diverge silently. This
command recomputes every balance from the ledger and reports the difference.

Usage:
    python manage.py reconcile_current_stock --schema=<tenant_schema>
    python manage.py reconcile_current_stock --schema=<tenant_schema> --fix
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.commissioning.services import CurrentBalanceService


class Command(BaseCommand):
    help = "Detect (and optionally repair) drift in CurrentStockBalance."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Repair drifted rows by recomputing them from the ledger.",
        )

    def handle(self, *args, **options) -> None:
        drift = CurrentBalanceService.get_drift()
        if not drift:
            self.stdout.write(self.style.SUCCESS("No drift detected."))
            return

        self.stdout.write(self.style.WARNING(f"Found {len(drift)} drifted entities:"))
        for row in drift:
            entity = row["entity"]
            self.stdout.write(
                f"  {entity}  stored={row['stored']}  expected={row['expected']}"
            )

        if not options["fix"]:
            self.stdout.write(
                "Run again with --fix to repair (recomputes from the ledger)."
            )
            return

        for row in drift:
            sa_id, unit, size, storage_id = row["entity"]
            # Repair from the raw ledger (not the snapshot baseline) so repair
            # converges even when the entity's snapshot is itself corrupt.
            CurrentBalanceService.recompute_for_entity(
                sa_id, unit, size, storage_id, from_ledger=True
            )
        self.stdout.write(self.style.SUCCESS(f"Repaired {len(drift)} rows."))
