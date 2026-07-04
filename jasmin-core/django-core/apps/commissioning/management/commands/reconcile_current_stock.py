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
        # Two independent drifts: the CURRENT balance projection, and the
        # StockSnapshot baselines that feed historical/cascade recomputes. Repair
        # only the former (the old behaviour) and a corrupt snapshot is left to
        # re-drift the balance on the next movement — so check both (audit #7).
        balance_drift = CurrentBalanceService.get_drift()
        snapshot_drift = CurrentBalanceService.get_snapshot_drift()

        if not balance_drift and not snapshot_drift:
            self.stdout.write(self.style.SUCCESS("No drift detected."))
            return

        if balance_drift:
            self.stdout.write(
                self.style.WARNING(f"Found {len(balance_drift)} drifted balance(s):")
            )
            for row in balance_drift:
                self.stdout.write(
                    f"  {row['entity']}  stored={row['stored']}  "
                    f"expected={row['expected']}"
                )

        snapshot_entities = {row["entity"] for row in snapshot_drift}
        if snapshot_drift:
            self.stdout.write(
                self.style.WARNING(
                    f"Found {len(snapshot_drift)} drifted snapshot(s) "
                    f"across {len(snapshot_entities)} entity(ies):"
                )
            )
            for row in snapshot_drift:
                self.stdout.write(
                    f"  {row['entity']} @ {row['snapshot_date']}  "
                    f"stored={row['stored']}  expected={row['expected']}"
                )

        if not options["fix"]:
            self.stdout.write(
                "Run again with --fix to repair (recomputes from the ledger)."
            )
            return

        for row in balance_drift:
            sa_id, unit, size, storage_id = row["entity"]
            # Repair from the raw ledger (not the snapshot baseline) so repair
            # converges even when the entity's snapshot is itself corrupt.
            CurrentBalanceService.recompute_for_entity(
                sa_id, unit, size, storage_id, from_ledger=True
            )
        for entity in snapshot_entities:
            sa_id, unit, size, storage_id = entity
            # Drop-all + reseed the entity's snapshots from the ledger so no corrupt
            # baseline survives to re-drift a future recompute or a historical query.
            CurrentBalanceService.repair_snapshots_for_entity(
                sa_id, unit, size, storage_id
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Repaired {len(balance_drift)} balance(s) and "
                f"{len(snapshot_entities)} entity snapshot(s)."
            )
        )
