"""Seed a realistic cultivation dataset so the placement solver can be tried.

    python manage.py seed_cultivation_demo --schema=<tenant_schema>
    python manage.py seed_cultivation_demo --schema=<tenant_schema> --year=2027
    python manage.py seed_cultivation_demo --schema=<tenant_schema> --clean

Creates a small market-garden: 3 outdoor plots + 1 greenhouse, a few bed types,
the usual rotation families, ~20 vegetables and ~30 finalized batches spread over
the season (including two overwintering crops and several successions of the same
crop). Also writes two years of hand-entered rotation history so the crop-rotation
constraint has something to bite on.

Everything is idempotent (get_or_create on the name) and tagged so ``--clean``
removes exactly what this command made and nothing else.

Dev/demo only — never run against production data.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from apps.cultivation.models import (
    BedType,
    CultivationBatch,
    CultivationBreakFamily,
    HistoricalPlanting,
    Plot,
    PlotContent,
    Vegetable,
)
from apps.shared.tenants.models import Tenant

# Everything this command creates carries the marker, so --clean is exact.
MARKER = "[demo]"

# name -> break years
FAMILIES = [
    ("Brassicas", 4),
    ("Nightshades", 3),
    ("Umbellifers", 3),
    ("Alliums", 3),
    ("Legumes", 2),
    ("Cucurbits", 2),
    ("Chenopods", 3),
]

# name, bed length m, bed width m
BED_TYPES = [
    ("Standard 50 m", 50, "0.75"),
    ("Short 25 m", 25, "0.75"),
    ("Greenhouse 30 m", 30, "1.20"),
]

# plot name, is_greenhouse, [(bed type name, how many beds)]
PLOTS = [
    ("Home field", False, [("Standard 50 m", 24)]),
    ("Brook field", False, [("Standard 50 m", 16), ("Short 25 m", 8)]),
    ("Orchard strip", False, [("Short 25 m", 12)]),
    ("Tunnel 1", True, [("Greenhouse 30 m", 6)]),
]

# name, family, unit, kg/piece, planting lines, spacing m, mode, feeder
VEGETABLES = [
    ("Cabbage", "Brassicas", "PCS", "1.400", 2, "0.50", "PLANTING", "STRONG"),
    ("Kohlrabi", "Brassicas", "PCS", "0.350", 3, "0.30", "PLANTING", "MIDDLE"),
    ("Broccoli", "Brassicas", "PCS", "0.450", 2, "0.45", "PLANTING", "STRONG"),
    ("Kale", "Brassicas", "KG", "0.300", 2, "0.50", "PLANTING", "STRONG"),
    ("Radish", "Brassicas", "BUNCH", "0.120", 5, "0.08", "SOWING", "WEAK"),
    ("Tomato", "Nightshades", "KG", "0.120", 2, "0.50", "PLANTING", "STRONG"),
    ("Potato", "Nightshades", "KG", "0.090", 2, "0.35", "PLANTING", "STRONG"),
    ("Pepper", "Nightshades", "PCS", "0.180", 2, "0.45", "PLANTING", "STRONG"),
    ("Carrot", "Umbellifers", "KG", "0.110", 4, "0.05", "SOWING", "MIDDLE"),
    ("Parsnip", "Umbellifers", "KG", "0.250", 3, "0.10", "SOWING", "MIDDLE"),
    ("Fennel", "Umbellifers", "PCS", "0.320", 3, "0.30", "PLANTING", "MIDDLE"),
    ("Onion", "Alliums", "KG", "0.110", 4, "0.12", "PLANTING", "MIDDLE"),
    ("Leek", "Alliums", "PCS", "0.280", 3, "0.15", "PLANTING", "MIDDLE"),
    ("Garlic", "Alliums", "KG", "0.060", 4, "0.12", "PLANTING", "MIDDLE"),
    ("Bush bean", "Legumes", "KG", "0.008", 3, "0.08", "SOWING", "WEAK"),
    ("Pea", "Legumes", "KG", "0.006", 3, "0.05", "SOWING", "WEAK"),
    ("Zucchini", "Cucurbits", "PCS", "0.400", 1, "0.90", "PLANTING", "STRONG"),
    ("Cucumber", "Cucurbits", "KG", "0.350", 1, "0.50", "PLANTING", "STRONG"),
    ("Spinach", "Chenopods", "KG", "0.030", 5, "0.06", "SOWING", "MIDDLE"),
    ("Chard", "Chenopods", "KG", "0.250", 3, "0.30", "PLANTING", "MIDDLE"),
    ("Lettuce", None, "PCS", "0.300", 4, "0.30", "PLANTING", "WEAK"),
]

# Which bed type each crop is sized for. ``amount_of_beds`` counts beds OF THIS
# TYPE, so the planner keeps these crops inside that type's block.
#
# The split is the usual one: the long beds carry the big field crops, the short
# beds the quick leafy/small stuff that gets picked over by hand. Peak demand
# lands at ~164 of 200 long cells and ~71 of 100 short ones, so there is real
# headroom to plan into rather than a puzzle with one solution.
#
# Lettuce is deliberately left unset — it is the filler crop that goes wherever a
# gap opens, and it shows what "no bed type" means: place it anywhere.
BED_TYPE_FOR_CROP = {
    "Carrot": "Standard 50 m",
    "Parsnip": "Standard 50 m",
    "Cabbage": "Standard 50 m",
    "Broccoli": "Standard 50 m",
    "Kale": "Standard 50 m",
    "Onion": "Standard 50 m",
    "Leek": "Standard 50 m",
    "Garlic": "Standard 50 m",
    "Potato": "Standard 50 m",
    "Tomato": "Standard 50 m",
    "Zucchini": "Standard 50 m",
    "Cucumber": "Standard 50 m",
    "Radish": "Short 25 m",
    "Spinach": "Short 25 m",
    "Kohlrabi": "Short 25 m",
    "Fennel": "Short 25 m",
    "Chard": "Short 25 m",
    "Pea": "Short 25 m",
    "Bush bean": "Short 25 m",
    "Pepper": "Short 25 m",
}

# vegetable, planting week, end week (ground free again), beds, fleece-off week
# Successions of one crop share a vegetable; two crops overwinter (end < planting).
BATCHES = [
    ("Lettuce", 14, 22, "1.4", 18),
    ("Lettuce", 18, 26, "1.4", None),
    ("Lettuce", 22, 30, "1.6", None),
    ("Lettuce", 28, 36, "1.6", None),
    ("Radish", 12, 18, "0.8", 15),
    ("Radish", 16, 22, "0.8", None),
    ("Spinach", 11, 19, "1.2", 15),
    ("Spinach", 34, 42, "1.2", None),
    ("Carrot", 16, 34, "3.0", None),
    ("Carrot", 20, 40, "3.0", None),
    ("Parsnip", 18, 44, "2.0", None),
    ("Fennel", 26, 36, "1.4", None),
    ("Kohlrabi", 15, 24, "1.2", 19),
    ("Kohlrabi", 24, 33, "1.2", None),
    ("Cabbage", 19, 40, "3.0", None),
    ("Broccoli", 17, 30, "2.0", None),
    ("Broccoli", 26, 38, "2.0", None),
    ("Kale", 24, 48, "2.2", None),
    ("Onion", 14, 32, "2.6", None),
    ("Leek", 22, 46, "3.0", None),
    ("Chard", 18, 40, "1.6", None),
    ("Bush bean", 21, 31, "2.0", None),
    ("Bush bean", 26, 36, "2.0", None),
    ("Pea", 13, 26, "1.8", None),
    ("Zucchini", 20, 38, "2.4", None),
    ("Cucumber", 21, 37, "1.6", None),
    ("Potato", 15, 33, "4.0", None),
    ("Tomato", 20, 40, "2.0", None),
    ("Pepper", 21, 39, "1.2", None),
    # Overwintering: planted in autumn, ground free again the NEXT spring.
    ("Garlic", 43, 26, "1.6", None),
    ("Spinach", 38, 14, "1.2", None),
]

# Protected cultivation — same shape, but flagged is_greenhouse so the outdoor
# optimizer skips them and they show on the indoor page instead.
GREENHOUSE_BATCHES = [
    ("Tomato", 12, 44, "2.0", None),
    ("Cucumber", 14, 42, "1.4", None),
    ("Pepper", 13, 43, "1.2", None),
    ("Lettuce", 6, 14, "0.8", None),
]

# Rotation history: (years back, plot name, family, start cell, cell count)
HISTORY = [
    (1, "Home field", "Brassicas", 0, 25),
    (1, "Home field", "Nightshades", 40, 20),
    (1, "Brook field", "Alliums", 0, 20),
    (2, "Home field", "Umbellifers", 25, 15),
    (2, "Brook field", "Brassicas", 20, 25),
    (2, "Orchard strip", "Legumes", 0, 20),
]


class Command(BaseCommand):
    help = "Seed a demo cultivation dataset (plots, vegetables, batches) — dev only"

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Tenant schema name")
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="Planning year for the batches (default: next calendar year)",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Only remove the demo data created by this command",
        )

    def handle(self, *args, **options):
        schema = options["schema"]
        clean = options["clean"]

        try:
            Tenant.objects.get(schema_name=schema)
        except Tenant.DoesNotExist:
            self.stderr.write(f"Tenant with schema '{schema}' not found.")
            return

        with schema_context(schema):
            if clean:
                removed = self._clean()
                self.stdout.write(
                    self.style.SUCCESS(f"Demo data removed ({removed} rows).")
                )
                return

            from datetime import date

            year = options["year"] or date.today().year + 1
            counts = self._seed(year)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded for {year}: {counts['plots']} plots "
                    f"({counts['beds']} beds / {counts['cells']} cells), "
                    f"{counts['vegetables']} vegetables, "
                    f"{counts['batches']} outdoor batches "
                    f"({counts['demand_beds']} beds of demand) + "
                    f"{counts['greenhouse_batches']} greenhouse, "
                    f"{counts['history']} history rows."
                )
            )
            self.stdout.write(
                "Run the solver from Cultivation → Planner, or:\n"
                f"  python manage.py shell --schema={schema}\n"
                "  >>> from apps.cultivation.optimizer import optimize_year\n"
                f"  >>> optimize_year({year})"
            )

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #
    def _clean(self) -> int:
        removed = 0
        for model in (CultivationBatch, HistoricalPlanting):
            qs = model.objects.filter(note__startswith=MARKER)
            removed += qs.count()
            qs.delete()
        plots = Plot.objects.filter(name__endswith=MARKER)
        removed += PlotContent.objects.filter(plot__in=plots).count() + plots.count()
        PlotContent.objects.filter(plot__in=plots).delete()
        plots.delete()
        for model, field in ((Vegetable, "name"), (BedType, "name")):
            qs = model.objects.filter(**{f"{field}__endswith": MARKER})
            removed += qs.count()
            qs.delete()
        families = CultivationBreakFamily.objects.filter(name__endswith=MARKER)
        removed += families.count()
        families.delete()
        return removed

    # ------------------------------------------------------------------ #
    # Seed
    # ------------------------------------------------------------------ #
    @transaction.atomic
    def _seed(self, year: int) -> dict:
        families = {
            name: CultivationBreakFamily.objects.get_or_create(
                name=f"{name} {MARKER}",
                defaults={"cultivation_break_in_years": break_years},
            )[0]
            for name, break_years in FAMILIES
        }

        bed_types = {
            name: BedType.objects.get_or_create(
                name=f"{name} {MARKER}",
                defaults={
                    "length_in_m": length,
                    "width_in_m": Decimal(width),
                },
            )[0]
            for name, length, width in BED_TYPES
        }

        plots, total_beds = {}, 0
        for name, is_greenhouse, contents in PLOTS:
            plot, _ = Plot.objects.get_or_create(
                name=f"{name} {MARKER}", defaults={"is_greenhouse": is_greenhouse}
            )
            plots[name] = plot
            for order, (bed_type_name, amount) in enumerate(contents, start=1):
                # `position` is the layout order the plot's cells are numbered
                # in, so the blocks must be numbered in the order PLOTS lists
                # them rather than left on the default.
                PlotContent.objects.get_or_create(
                    plot=plot,
                    bed_type=bed_types[bed_type_name],
                    defaults={"amount": amount, "position": order},
                )
                if not is_greenhouse:
                    total_beds += amount

        vegetables = {}
        for (
            name,
            family,
            unit,
            kg_per_piece,
            lines,
            spacing,
            mode,
            feeder,
        ) in VEGETABLES:
            vegetables[name] = Vegetable.objects.get_or_create(
                name=f"{name} {MARKER}",
                defaults={
                    "unit": unit,
                    "average_kg_per_piece": Decimal(kg_per_piece),
                    "default_planting_lines": lines,
                    "default_distance_in_row": Decimal(spacing),
                    "default_planting_mode": mode,
                    "fertilizer_requirement": feeder,
                    "cultivation_break_family": families.get(family),
                },
            )[0]

        demand = Decimal("0")
        made = 0
        greenhouse_made = 0
        for veg_name, planting, end, beds, fleece in BATCHES + GREENHOUSE_BATCHES:
            under_glass = (veg_name, planting, end, beds, fleece) in GREENHOUSE_BATCHES
            vegetable = vegetables[veg_name]
            harvest_start = end if end > planting else 52
            _, created = CultivationBatch.objects.get_or_create(
                year=year,
                vegetable=vegetable,
                planting_week=planting,
                defaults={
                    "end_week": end,
                    "harvesting_start_week": max(planting + 1, harvest_start - 2),
                    "harvesting_end_week": harvest_start,
                    "week_when_fleece_is_removed": fleece,
                    "planting_lines": vegetable.default_planting_lines,
                    "distance_in_row_in_m": vegetable.default_distance_in_row,
                    "planting_mode": vegetable.default_planting_mode,
                    "pieces_per_plant": Decimal("1.0"),
                    "yield_kg_per_m2": Decimal("2.50"),
                    # Under glass everything sits on the tunnel's own beds;
                    # outdoors it follows the long/short split, and an unlisted
                    # crop stays unset ("place me anywhere").
                    "used_bed_type": (
                        bed_types["Greenhouse 30 m"]
                        if under_glass
                        else bed_types.get(BED_TYPE_FOR_CROP.get(veg_name))
                    ),
                    "amount_of_beds": Decimal(beds),
                    "is_final": True,
                    "is_greenhouse": under_glass,
                    "note": f"{MARKER} seeded",
                },
            )
            if under_glass:
                greenhouse_made += 1
            else:
                demand += Decimal(beds)
            made += 1 if created else 0

        history_rows = 0
        for years_back, plot_name, family, start_cell, cell_count in HISTORY:
            _, created = HistoricalPlanting.objects.get_or_create(
                year=year - years_back,
                plot=plots[plot_name],
                cultivation_break_family=families[family],
                start_cell=start_cell,
                defaults={
                    "cell_count": cell_count,
                    "note": f"{MARKER} seeded",
                },
            )
            history_rows += 1

        return {
            "plots": len(plots),
            "beds": total_beds,
            "cells": total_beds * 5,
            "vegetables": len(vegetables),
            "batches": len(BATCHES),
            "greenhouse_batches": greenhouse_made,
            "batches_created": made,
            "demand_beds": demand,
            "history": history_rows,
        }
